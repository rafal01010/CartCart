from pathlib import Path

import httpx
import pytest
from pydantic import AnyHttpUrl

from app.schemas.search_sources import ExtractionStatus, SourceType
from app.services.source_fetch import (
    HttpSourceFetcher,
    SourceFetchBlockedError,
    SourceFetchContentTooLargeError,
    SourceFetchHttpError,
    SourceFetchTimeoutError,
    SourceFetchUnsafeUrlError,
    SourceFetchUnsupportedContentTypeError,
)


HTML_BODY = b"<html><body>Fixture page</body></html>"


@pytest.mark.asyncio
async def test_http_source_fetcher_persists_successful_html_snapshot(
    tmp_path: Path,
) -> None:
    requested_headers: httpx.Headers | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested_headers
        requested_headers = request.headers
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=HTML_BODY,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = HttpSourceFetcher(
            snapshot_dir=tmp_path,
            user_agent="CartCart-Test/1.0",
            client=client,
        )
        snapshot = await fetcher.fetch(
            AnyHttpUrl("https://example.com/products/monitor"),
            source_type=SourceType.PRODUCT_PAGE,
        )

    assert requested_headers is not None
    assert requested_headers["User-Agent"] == "CartCart-Test/1.0"
    assert requested_headers["Accept"] == "text/html,application/xhtml+xml"
    assert snapshot.source_type == SourceType.PRODUCT_PAGE
    assert snapshot.extraction_status == ExtractionStatus.NOT_ATTEMPTED
    assert snapshot.http_status_code == 200
    assert snapshot.provider.provider_name == "http-fetch"
    assert snapshot.raw_artifact is not None
    assert snapshot.raw_artifact.content_type == "text/html"
    assert snapshot.raw_artifact.size_bytes == len(HTML_BODY)
    artifact_path = tmp_path / snapshot.raw_artifact.path
    assert artifact_path.read_bytes() == HTML_BODY
    assert len(snapshot.raw_artifact.sha256) == 64


@pytest.mark.asyncio
async def test_http_source_fetcher_reports_timeout_without_storing_snapshot(
    tmp_path: Path,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("fixture timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = HttpSourceFetcher(snapshot_dir=tmp_path, client=client)
        with pytest.raises(SourceFetchTimeoutError):
            await fetcher.fetch(AnyHttpUrl("https://example.com/slow"))

    assert list(tmp_path.rglob("*")) == []


@pytest.mark.asyncio
async def test_http_source_fetcher_rejects_non_html_response(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            content=b"%PDF fixture",
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = HttpSourceFetcher(snapshot_dir=tmp_path, client=client)
        with pytest.raises(SourceFetchUnsupportedContentTypeError):
            await fetcher.fetch(AnyHttpUrl("https://example.com/manual.pdf"))

    assert list(tmp_path.rglob("*")) == []


@pytest.mark.asyncio
async def test_http_source_fetcher_rejects_large_content(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"0123456789",
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = HttpSourceFetcher(
            snapshot_dir=tmp_path,
            max_content_bytes=8,
            client=client,
        )
        with pytest.raises(SourceFetchContentTooLargeError):
            await fetcher.fetch(AnyHttpUrl("https://example.com/large"))

    assert list(tmp_path.rglob("*")) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    ((403, SourceFetchBlockedError), (500, SourceFetchHttpError)),
)
async def test_http_source_fetcher_rejects_blocked_and_error_responses(
    tmp_path: Path,
    status_code: int,
    expected_error: type[Exception],
) -> None:
    request_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            status_code,
            headers={"Content-Type": "text/html"},
            content=b"<html>Error</html>",
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = HttpSourceFetcher(
            snapshot_dir=tmp_path,
            client=client,
            retry_backoff_seconds=0,
        )
        with pytest.raises(expected_error):
            await fetcher.fetch(AnyHttpUrl("https://example.com/error"))

    assert list(tmp_path.rglob("*")) == []
    assert request_count == (1 if status_code == 403 else 2)


@pytest.mark.asyncio
async def test_http_source_fetcher_retries_rate_limit_then_succeeds(
    tmp_path: Path,
) -> None:
    request_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(
                429,
                headers={"Content-Type": "text/html", "Retry-After": "0"},
                request=request,
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=HTML_BODY,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await HttpSourceFetcher(
            snapshot_dir=tmp_path,
            client=client,
            retry_backoff_seconds=0,
        ).fetch(AnyHttpUrl("https://example.com/rate-limited"))

    assert request_count == 2
    assert snapshot.http_status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    (
        "http://127.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/private",
        "http://localhost/private",
    ),
)
async def test_http_source_fetcher_rejects_non_public_urls_before_request(
    tmp_path: Path,
    url: str,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unsafe request was sent: {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceFetchUnsafeUrlError):
            await HttpSourceFetcher(snapshot_dir=tmp_path, client=client).fetch(
                AnyHttpUrl(url)
            )


@pytest.mark.asyncio
async def test_http_source_fetcher_validates_redirect_target_before_request(
    tmp_path: Path,
) -> None:
    requested_urls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"Location": "http://127.0.0.1/private"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceFetchUnsafeUrlError):
            await HttpSourceFetcher(snapshot_dir=tmp_path, client=client).fetch(
                AnyHttpUrl("https://example.com/redirect")
            )

    assert requested_urls == ["https://example.com/redirect"]


@pytest.mark.asyncio
async def test_http_source_fetcher_rejects_hostname_resolving_to_private_address(
    tmp_path: Path,
) -> None:
    async def resolver(hostname: str, port: int) -> tuple[str, ...]:
        assert hostname == "internal.invalid"
        assert port == 443
        return ("10.0.0.5",)

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unsafe request was sent: {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceFetchUnsafeUrlError):
            await HttpSourceFetcher(
                snapshot_dir=tmp_path,
                client=client,
                host_resolver=resolver,
            ).fetch(AnyHttpUrl("https://internal.invalid/product"))
