import asyncio
from collections.abc import Awaitable, Callable, Iterable
from hashlib import sha256
from ipaddress import ip_address
from pathlib import Path
import socket
from urllib.parse import urljoin, urlsplit

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
REDIRECT_HTTP_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_DOCUMENTATION_HOSTS = frozenset({"example.com", "example.net", "example.org"})

HostResolver = Callable[[str, int], Awaitable[Iterable[str]]]


class SourceFetchError(RuntimeError):
    """Base error for source fetch failures that should not persist a body."""

    failure_code = "request_failed"
    retryable = True

    def __init__(
        self,
        message: str,
        *,
        http_status_code: int | None = None,
        retry_after_seconds: float | None = None,
        retryable: bool | None = None,
        failure_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status_code = http_status_code
        self.retry_after_seconds = retry_after_seconds
        if retryable is not None:
            self.retryable = retryable
        if failure_code is not None:
            self.failure_code = failure_code


class SourceFetchTimeoutError(SourceFetchError):
    """Raised when the source request exceeds its configured timeout."""

    failure_code = "timeout"


class SourceFetchBlockedError(SourceFetchError):
    """Raised when a source explicitly blocks or rate-limits the request."""

    failure_code = "blocked"
    retryable = False


class SourceFetchHttpError(SourceFetchError):
    """Raised for unsuccessful HTTP responses other than blocked responses."""

    failure_code = "http_error"


class SourceFetchUnsupportedContentTypeError(SourceFetchError):
    """Raised when a successful response is not HTML."""

    failure_code = "unsupported_content_type"
    retryable = False


class SourceFetchContentTooLargeError(SourceFetchError):
    """Raised when a response exceeds the configured decoded-body limit."""

    failure_code = "content_too_large"
    retryable = False


class SourceSnapshotStorageError(SourceFetchError):
    """Raised when a completed HTML response cannot be persisted."""

    failure_code = "snapshot_storage_failed"
    retryable = False


class SourceFetchUnsafeUrlError(SourceFetchError):
    """Raised before fetching a URL that could reach a non-public network."""

    failure_code = "unsafe_url"
    retryable = False


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
        max_attempts: int = 2,
        retry_backoff_seconds: float = 0.25,
        max_redirects: int = 10,
        host_resolver: HostResolver | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Source fetch timeout must be greater than zero.")
        if max_content_bytes <= 0:
            raise ValueError("Source fetch content limit must be greater than zero.")
        if not user_agent.strip():
            raise ValueError("Source fetch user agent must not be empty.")
        if max_attempts <= 0:
            raise ValueError("Source fetch attempts must be greater than zero.")
        if retry_backoff_seconds < 0:
            raise ValueError("Source fetch retry backoff must not be negative.")
        if max_redirects < 0:
            raise ValueError("Source fetch redirect limit must not be negative.")

        self._snapshot_dir = snapshot_dir
        self._timeout_seconds = timeout_seconds
        self._max_content_bytes = max_content_bytes
        self._user_agent = user_agent.strip()
        self._client = client
        self._max_attempts = max_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._max_redirects = max_redirects
        self._host_resolver = host_resolver or _resolve_host_addresses

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
        response, content, redirect_count = await self._fetch_html_with_retries(url)
        artifact = self._persist(snapshot, content, response)

        snapshot.url = str(response.url)
        snapshot.http_status_code = response.status_code
        snapshot.raw_artifact = artifact
        snapshot.provider.raw.update(
            {
                "redirect_count": redirect_count,
                "user_agent": self._user_agent,
            }
        )
        return snapshot

    async def _fetch_html_with_retries(
        self,
        url: AnyHttpUrl,
    ) -> tuple[httpx.Response, bytes, int]:
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await self._fetch_html(url)
            except SourceFetchError as exc:
                if not exc.retryable or attempt >= self._max_attempts:
                    raise
                delay = max(
                    self._retry_backoff_seconds * (2 ** (attempt - 1)),
                    exc.retry_after_seconds or 0,
                )
                if delay > 0:
                    await asyncio.sleep(min(delay, 5.0))
        raise AssertionError("source fetch retry loop did not return or raise")

    async def _fetch_html(
        self,
        url: AnyHttpUrl,
    ) -> tuple[httpx.Response, bytes, int]:
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
    ) -> tuple[httpx.Response, bytes, int]:
        current_url = str(url)
        redirect_count = 0
        while True:
            await self._validate_public_url(current_url)
            async with client.stream(
                "GET",
                current_url,
                headers=headers,
                follow_redirects=False,
                timeout=self._timeout_seconds,
            ) as response:
                if (
                    response.status_code in REDIRECT_HTTP_STATUS_CODES
                    and response.headers.get("Location")
                ):
                    if redirect_count >= self._max_redirects:
                        raise SourceFetchHttpError(
                            "Source fetch exceeded the configured redirect limit.",
                            retryable=False,
                            failure_code="redirect_limit_exceeded",
                        )
                    current_url = urljoin(str(response.url), response.headers["Location"])
                    redirect_count += 1
                    continue

                self._validate_response(response)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > self._max_content_bytes:
                        raise SourceFetchContentTooLargeError(
                            "Source response exceeded the configured content limit of "
                            f"{self._max_content_bytes} bytes."
                        )
                    content.extend(chunk)
                return response, bytes(content), redirect_count

    async def _validate_public_url(self, url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
            raise SourceFetchUnsafeUrlError(
                "Source URL must use HTTP or HTTPS and include a hostname."
            )
        if parsed.username is not None or parsed.password is not None:
            raise SourceFetchUnsafeUrlError(
                "Source URL must not contain embedded credentials."
            )

        hostname = parsed.hostname.rstrip(".").casefold()
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise SourceFetchUnsafeUrlError(
                "Source URL resolves to a non-public network."
            )
        if hostname in _DOCUMENTATION_HOSTS or hostname.endswith(".example"):
            return

        try:
            literal_address = ip_address(hostname)
        except ValueError:
            port = parsed.port or (443 if parsed.scheme.casefold() == "https" else 80)
            try:
                resolved_addresses = tuple(await self._host_resolver(hostname, port))
            except OSError as exc:
                raise SourceFetchError(
                    f"Source hostname could not be resolved for {url}."
                ) from exc
            if not resolved_addresses:
                raise SourceFetchError(
                    f"Source hostname could not be resolved for {url}."
                )
            addresses = tuple(ip_address(address) for address in resolved_addresses)
        else:
            addresses = (literal_address,)

        if any(not address.is_global for address in addresses):
            raise SourceFetchUnsafeUrlError(
                "Source URL resolves to a non-public network."
            )

    def _validate_response(self, response: httpx.Response) -> None:
        if response.status_code in BLOCKED_HTTP_STATUS_CODES:
            if response.status_code == 429:
                raise SourceFetchError(
                    "Source fetch was rate-limited with HTTP 429.",
                    http_status_code=429,
                    retry_after_seconds=_retry_after_seconds(response),
                    failure_code="rate_limited",
                )
            raise SourceFetchBlockedError(
                f"Source fetch was blocked with HTTP {response.status_code}.",
                http_status_code=response.status_code,
            )
        if not response.is_success:
            raise SourceFetchHttpError(
                f"Source fetch failed with HTTP {response.status_code}.",
                http_status_code=response.status_code,
                retryable=response.status_code >= 500,
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


async def _resolve_host_addresses(hostname: str, port: int) -> tuple[str, ...]:
    loop = asyncio.get_running_loop()
    results = await loop.getaddrinfo(
        hostname,
        port,
        type=socket.SOCK_STREAM,
    )
    return tuple({result[4][0] for result in results})


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return max(parsed, 0)
