from pathlib import Path

import httpx
from pydantic import AnyHttpUrl

from app.providers.contracts import ExtractionProviderOptions
from app.schemas.search_sources import ProviderMetadata, SourceSnapshot, SourceType
from app.services.source_extraction import StaticPageTextExtractor
from app.services.source_fetch import HttpSourceFetcher


class HttpStaticExtractionProvider:
    """Fetch an HTML page, persist it, and run the static extractor."""

    provider_name = "http-static-extraction"

    def __init__(
        self,
        *,
        snapshot_dir: Path,
        timeout_seconds: float = 10.0,
        max_content_bytes: int = 2 * 1024 * 1024,
        user_agent: str = "CartCart/0.1 source-fetcher",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._fetcher = HttpSourceFetcher(
            snapshot_dir=snapshot_dir,
            timeout_seconds=timeout_seconds,
            max_content_bytes=max_content_bytes,
            user_agent=user_agent,
            client=client,
        )
        self._extractor = StaticPageTextExtractor(snapshot_dir=snapshot_dir)

    async def extract(
        self,
        url: AnyHttpUrl,
        options: ExtractionProviderOptions | None = None,
    ) -> SourceSnapshot:
        source_type = (
            options.source_type if options is not None else SourceType.PRODUCT_PAGE
        )
        snapshot = await self._fetcher.fetch(url, source_type=source_type)
        fetch_provider = snapshot.provider.provider_name
        snapshot.provider = ProviderMetadata(
            provider_name=self.provider_name,
            raw={**snapshot.provider.raw, "fetch_provider": fetch_provider},
        )
        return self._extractor.extract(snapshot)
