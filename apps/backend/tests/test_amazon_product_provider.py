import json
import os
from pathlib import Path

import httpx
import pytest

from app.core.settings import AmazonProductIntelligenceProviderName, Settings
from app.providers import (
    AmazonProductIntelligenceError,
    AmazonProductIntelligenceProviderOptions,
    FakeAmazonProductIntelligenceProvider,
    ProviderRunStatus,
    SerpApiAmazonProductIntelligenceProvider,
    build_amazon_product_intelligence_provider,
)
from app.providers.fixtures import load_provider_fixture, provider_fixture_transport
from app.schemas.products import CanonicalProduct
from app.schemas.search_sources import AmazonEvidenceFactType, EvidenceTargetType


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "providers"


@pytest.mark.asyncio
async def test_amazon_fixture_replay_returns_neutral_listing_and_review_evidence() -> None:
    fixtures = (
        load_provider_fixture(FIXTURE_DIR / "amazon_search.json"),
        load_provider_fixture(FIXTURE_DIR / "amazon_product.json"),
    )
    product = CanonicalProduct(
        name="Portable Monitor",
        brand="Acme",
        model="View 15",
    )

    async with httpx.AsyncClient(
        transport=provider_fixture_transport(fixtures)
    ) as client:
        provider = SerpApiAmazonProductIntelligenceProvider(
            api_key="recorded-test-key",
            client=client,
        )
        result = await provider.fetch_product_evidence(
            product,
            options=AmazonProductIntelligenceProviderOptions(region_code="PH"),
        )

    assert result.status == ProviderRunStatus.SUCCEEDED
    assert result.capabilities.supports_amazon_product_intelligence is True
    assert result.capabilities.supports_amazon_review_signals is True
    assert result.bundle is not None
    assert len(result.bundle.source_references) == 1
    assert len(result.bundle.listing_contexts) == 1

    source = result.bundle.source_references[0]
    context = result.bundle.listing_contexts[0]
    assert str(source.url) == "https://www.amazon.com/dp/B0CART5901"
    assert "tag=" not in str(source.url)
    assert "serpapi" not in str(source.url)
    assert context.asin == "B0CART5901"
    assert context.marketplace_domain == "amazon.com"
    assert context.marketplace_country_code == "US"
    assert context.seller_name == "Acme Deals"
    assert context.fulfillment == "Fulfilled or shipped by Amazon"
    assert context.ships_to_region_code == "PH"
    assert context.ships_to_region is True
    assert context.review_count == 1287
    assert context.average_rating == 4.4
    assert context.variant_label == "Size: 15.6 inch"

    fact_types = {item.fact_type for item in result.bundle.evidence}
    assert AmazonEvidenceFactType.PRODUCT_PAGE_FACT in fact_types
    assert AmazonEvidenceFactType.LISTING_IDENTITY in fact_types
    assert AmazonEvidenceFactType.SELLER_FULFILLMENT in fact_types
    assert AmazonEvidenceFactType.REGIONAL_AVAILABILITY in fact_types
    assert AmazonEvidenceFactType.REVIEW_SUMMARY in fact_types
    assert AmazonEvidenceFactType.REVIEW_QUALITY_WARNING in fact_types
    assert AmazonEvidenceFactType.MARKETPLACE_WARNING in fact_types
    assert any(
        item.target.target_type == EvidenceTargetType.REVIEW
        and "multiple Amazon variants" in " ".join(item.evidence_quality_warnings)
        for item in result.bundle.evidence
    )
    assert "recorded-test-key" not in json.dumps(
        [fixture.model_dump(mode="json") for fixture in fixtures]
    )


def test_amazon_runtime_selects_fixture_disabled_and_serpapi_modes() -> None:
    default_provider = build_amazon_product_intelligence_provider(
        Settings(_env_file=None)  # type: ignore[call-arg]
    )
    disabled_provider = build_amazon_product_intelligence_provider(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            amazon_product_intelligence_provider=(
                AmazonProductIntelligenceProviderName.DISABLED
            ),
        )
    )
    live_provider = build_amazon_product_intelligence_provider(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            amazon_product_intelligence_provider=(
                AmazonProductIntelligenceProviderName.SERPAPI
            ),
            amazon_product_intelligence_provider_enabled=True,
            serpapi_api_key="fixture-key",
        )
    )
    missing_key_provider = build_amazon_product_intelligence_provider(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            amazon_product_intelligence_provider=(
                AmazonProductIntelligenceProviderName.SERPAPI
            ),
            amazon_product_intelligence_provider_enabled=True,
        )
    )

    assert isinstance(default_provider, FakeAmazonProductIntelligenceProvider)
    assert isinstance(disabled_provider, FakeAmazonProductIntelligenceProvider)
    assert disabled_provider.disabled is True
    assert isinstance(live_provider, SerpApiAmazonProductIntelligenceProvider)
    assert isinstance(missing_key_provider, FakeAmazonProductIntelligenceProvider)


@pytest.mark.asyncio
async def test_amazon_search_returns_explicit_gap_without_conservative_match() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "search_metadata": {"id": "no-match", "status": "Success"},
                "organic_results": [
                    {"asin": "B0CART5901", "title": "Different Brand Coffee Maker"}
                ],
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = SerpApiAmazonProductIntelligenceProvider(
            api_key="test-key",
            client=client,
        )
        result = await provider.fetch_product_evidence(
            CanonicalProduct(name="Portable Monitor", brand="Acme", model="View 15")
        )

    assert result.status == ProviderRunStatus.SUCCEEDED
    assert result.bundle is not None
    assert result.bundle.source_references == ()
    assert result.bundle.evidence == ()
    assert "No sufficiently matching Amazon product" in (
        result.bundle.evidence_gaps[0].summary
    )


@pytest.mark.asyncio
async def test_amazon_provider_raises_sanitized_http_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": "invalid secret test-key"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = SerpApiAmazonProductIntelligenceProvider(
            api_key="test-key",
            client=client,
        )
        with pytest.raises(AmazonProductIntelligenceError, match="HTTP 403") as exc:
            await provider.fetch_product_evidence(CanonicalProduct(name="Monitor"))

    assert "test-key" not in str(exc.value)
    assert "invalid secret" not in str(exc.value)


@pytest.mark.live_provider
@pytest.mark.asyncio
async def test_amazon_product_intelligence_live_opt_in() -> None:
    if os.getenv("CARTCART_RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("Set CARTCART_RUN_LIVE_PROVIDER_TESTS=1 to allow live calls.")

    settings = Settings()
    if settings.serpapi_api_key is None:
        pytest.skip("CARTCART_SERPAPI_API_KEY is not configured.")

    provider = SerpApiAmazonProductIntelligenceProvider(
        api_key=settings.serpapi_api_key.get_secret_value(),
        timeout_seconds=settings.provider_timeout_seconds,
    )
    result = await provider.fetch_product_evidence(
        CanonicalProduct(name="Logitech MX Master 3S", brand="Logitech", model="MX Master 3S"),
        options=AmazonProductIntelligenceProviderOptions(region_code="US"),
    )

    assert result.status == ProviderRunStatus.SUCCEEDED
    assert result.bundle is not None
    assert result.bundle.source_references
    assert all("tag=" not in str(item.url) for item in result.bundle.source_references)
