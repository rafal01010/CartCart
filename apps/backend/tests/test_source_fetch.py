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
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            headers={"Content-Type": "text/html"},
            content=b"<html>Error</html>",
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = HttpSourceFetcher(snapshot_dir=tmp_path, client=client)
        with pytest.raises(expected_error):
            await fetcher.fetch(AnyHttpUrl("https://example.com/error"))

    assert list(tmp_path.rglob("*")) == []
