from hashlib import sha256
from pathlib import Path

import httpx
from pydantic import AnyHttpUrl

from app.schemas.search_sources import (
    ProviderMetadata,
    RawSourceSnapshotArtifact,
    SourceSnapshot,
    SourceType,
)


HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
BLOCKED_HTTP_STATUS_CODES = frozenset({401, 403, 407, 429, 451})


class SourceFetchError(RuntimeError):
    """Base error for source fetch failures that should not persist a body."""


class SourceFetchTimeoutError(SourceFetchError):
    """Raised when the source request exceeds its configured timeout."""


class SourceFetchBlockedError(SourceFetchError):
    """Raised when a source explicitly blocks or rate-limits the request."""


class SourceFetchHttpError(SourceFetchError):
    """Raised for unsuccessful HTTP responses other than blocked responses."""


class SourceFetchUnsupportedContentTypeError(SourceFetchError):
    """Raised when a successful response is not HTML."""


class SourceFetchContentTooLargeError(SourceFetchError):
    """Raised when a response exceeds the configured decoded-body limit."""


class SourceSnapshotStorageError(SourceFetchError):
    """Raised when a completed HTML response cannot be persisted."""


class HttpSourceFetcher:
    provider_name = "http-fetch"

    def __init__(
        self,
        *,
        snapshot_dir: Path,
        timeout_seconds: float = 10.0,
        max_content_bytes: int = 2 * 1024 * 1024,
        user_agent: str = "CartCart/0.1 source-fetcher",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Source fetch timeout must be greater than zero.")
        if max_content_bytes <= 0:
            raise ValueError("Source fetch content limit must be greater than zero.")
        if not user_agent.strip():
            raise ValueError("Source fetch user agent must not be empty.")

        self._snapshot_dir = snapshot_dir
        self._timeout_seconds = timeout_seconds
        self._max_content_bytes = max_content_bytes
        self._user_agent = user_agent.strip()
        self._client = client

    async def fetch(
        self,
        url: AnyHttpUrl,
        *,
        source_type: SourceType = SourceType.OTHER,
    ) -> SourceSnapshot:
        snapshot = SourceSnapshot(
            url=url,
            source_type=source_type,
            provider=ProviderMetadata(
                provider_name=self.provider_name,
                raw={"requested_url": str(url)},
            ),
        )
        response, content = await self._fetch_html(url)
        artifact = self._persist(snapshot, content, response)

        snapshot.url = str(response.url)
        snapshot.http_status_code = response.status_code
        snapshot.raw_artifact = artifact
        snapshot.provider.raw.update(
            {
                "redirect_count": len(response.history),
                "user_agent": self._user_agent,
            }
        )
        return snapshot

    async def _fetch_html(
        self,
        url: AnyHttpUrl,
    ) -> tuple[httpx.Response, bytes]:
        headers = {
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": self._user_agent,
        }
        try:
            if self._client is not None:
                return await self._stream_response(self._client, url, headers)
            async with httpx.AsyncClient() as client:
                return await self._stream_response(client, url, headers)
        except httpx.TimeoutException as exc:
            raise SourceFetchTimeoutError(
                f"Source fetch timed out for {url}."
            ) from exc
        except httpx.RequestError as exc:
            raise SourceFetchError(f"Source fetch request failed for {url}.") from exc

    async def _stream_response(
        self,
        client: httpx.AsyncClient,
        url: AnyHttpUrl,
        headers: dict[str, str],
    ) -> tuple[httpx.Response, bytes]:
        async with client.stream(
            "GET",
            str(url),
            headers=headers,
            follow_redirects=True,
            timeout=self._timeout_seconds,
        ) as response:
            self._validate_response(response)
            content = bytearray()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > self._max_content_bytes:
                    raise SourceFetchContentTooLargeError(
                        "Source response exceeded the configured content limit of "
                        f"{self._max_content_bytes} bytes."
                    )
                content.extend(chunk)
            return response, bytes(content)

    def _validate_response(self, response: httpx.Response) -> None:
        if response.status_code in BLOCKED_HTTP_STATUS_CODES:
            raise SourceFetchBlockedError(
                f"Source fetch was blocked with HTTP {response.status_code}."
            )
        if not response.is_success:
            raise SourceFetchHttpError(
                f"Source fetch failed with HTTP {response.status_code}."
            )

        content_type = _normalized_content_type(response)
        if content_type not in HTML_CONTENT_TYPES:
            shown_content_type = content_type or "missing"
            raise SourceFetchUnsupportedContentTypeError(
                f"Source response is not HTML ({shown_content_type})."
            )

        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                declared_length = None
            if (
                declared_length is not None
                and declared_length > self._max_content_bytes
            ):
                raise SourceFetchContentTooLargeError(
                    "Source response exceeded the configured content limit of "
                    f"{self._max_content_bytes} bytes."
                )

    def _persist(
        self,
        snapshot: SourceSnapshot,
        content: bytes,
        response: httpx.Response,
    ) -> RawSourceSnapshotArtifact:
        relative_path = (
            Path(f"{snapshot.captured_at:%Y}")
            / f"{snapshot.captured_at:%m}"
            / f"{snapshot.captured_at:%d}"
            / f"{snapshot.source_id}.html"
        )
        target = self._snapshot_dir / relative_path
        temporary = target.with_suffix(".html.tmp")

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(content)
            temporary.replace(target)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise SourceSnapshotStorageError(
                "Fetched source could not be stored."
            ) from exc

        return RawSourceSnapshotArtifact(
            path=relative_path.as_posix(),
            content_type=_normalized_content_type(response),
            size_bytes=len(content),
            sha256=sha256(content).hexdigest(),
        )


def _normalized_content_type(response: httpx.Response) -> str:
    return response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
