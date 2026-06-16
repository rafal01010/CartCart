from pathlib import Path

import httpx
import pytest

from app.core.settings import (
    IKEAStoreIntelligenceProviderName,
    SearchProviderName,
    Settings,
)
from app.providers import (
    FakeIKEAStoreIntelligenceProvider,
    IKEARegionalStoreDiscoveryProvider,
    IKEAStoreIntelligenceProviderOptions,
    ProviderRunStatus,
    SearchProviderOptions,
    TavilySearchProvider,
    build_ikea_store_intelligence_provider,
)
from app.providers.fixtures import load_provider_fixture, provider_fixture_transport
from app.schemas.products import CanonicalProduct
from app.schemas.search_sources import (
    IKEAEvidenceFactType,
    RegionalStoreAvailability,
    SearchQuery,
    SearchResult,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "providers"


@pytest.mark.asyncio
async def test_ikea_fixture_replay_returns_regional_official_store_evidence() -> None:
    fixture = load_provider_fixture(FIXTURE_DIR / "ikea_available.json")
    product = CanonicalProduct(name="MICKE desk", brand="IKEA", model="MICKE")

    async with httpx.AsyncClient(
        transport=provider_fixture_transport(fixture)
    ) as client:
        provider = IKEARegionalStoreDiscoveryProvider(
            search_provider=TavilySearchProvider(
                api_key="recorded-test-key",
                client=client,
            )
        )
        result = await provider.fetch_store_evidence(
            product,
            IKEAStoreIntelligenceProviderOptions(region_code="PH"),
        )

    assert result.status == ProviderRunStatus.SUCCEEDED
    assert result.capabilities.supports_ikea_regional_store_lookup is True
    assert result.bundle is not None
    assert len(result.bundle.source_references) == 1
    assert len(result.bundle.store_contexts) == 1

    source = result.bundle.source_references[0]
    context = result.bundle.store_contexts[0]
    assert str(source.url) == (
        "https://ikea.com/ph/en/p/micke-desk-white-90214308/"
    )
    assert context.country_code == "PH"
    assert context.product_code == "902.143.08"
    assert context.product_name == "MICKE desk, white"
    assert context.store_name == "IKEA Pasay City"
    assert context.price is not None
    assert str(context.price.amount) == "3990"
    assert context.price.currency == "PHP"
    assert context.availability == RegionalStoreAvailability.AVAILABLE
    assert context.delivery_area == "Available for delivery in Metro Manila."

    fact_types = {item.fact_type for item in result.bundle.evidence}
    assert IKEAEvidenceFactType.OFFICIAL_PRODUCT_FACT in fact_types
    assert IKEAEvidenceFactType.REGIONAL_PRICE in fact_types
    assert IKEAEvidenceFactType.REGIONAL_AVAILABILITY in fact_types
    assert IKEAEvidenceFactType.STORE_DELIVERY_CONTEXT in fact_types
    assert all(
        item.target.region_code in {None, "PH"}
        for item in result.bundle.evidence
    )
    assert all("global" not in item.claim.casefold() for item in result.bundle.evidence)


@pytest.mark.asyncio
async def test_ikea_fixture_replay_preserves_unavailable_product_gap() -> None:
    fixture = load_provider_fixture(FIXTURE_DIR / "ikea_unavailable.json")
    product = CanonicalProduct(
        name="KALLAX shelf unit",
        brand="IKEA",
        model="KALLAX",
    )

    async with httpx.AsyncClient(
        transport=provider_fixture_transport(fixture)
    ) as client:
        provider = IKEARegionalStoreDiscoveryProvider(
            search_provider=TavilySearchProvider(
                api_key="recorded-test-key",
                client=client,
            )
        )
        result = await provider.fetch_store_evidence(
            product,
            IKEAStoreIntelligenceProviderOptions(region_code="US"),
        )

    assert result.bundle is not None
    assert result.bundle.store_contexts[0].availability == (
        RegionalStoreAvailability.OUT_OF_STOCK
    )
    assert result.bundle.store_contexts[0].price is not None
    assert result.bundle.store_contexts[0].price.currency == "USD"
    assert any(
        "out of stock" in gap.summary.casefold()
        for gap in result.bundle.evidence_gaps
    )


@pytest.mark.asyncio
async def test_ikea_no_regional_presence_returns_gap_without_search() -> None:
    class SearchMustNotRun:
        async def search(
            self,
            query: SearchQuery,
            options: SearchProviderOptions | None = None,
        ) -> tuple[SearchResult, ...]:
            raise AssertionError("Unsupported IKEA regions must not call search.")

    provider = IKEARegionalStoreDiscoveryProvider(
        search_provider=SearchMustNotRun(),
    )
    result = await provider.fetch_store_evidence(
        CanonicalProduct(name="Desk"),
        IKEAStoreIntelligenceProviderOptions(region_code="AQ"),
    )

    assert result.status == ProviderRunStatus.SUCCEEDED
    assert result.bundle is not None
    assert result.bundle.source_references == ()
    assert result.bundle.store_contexts == ()
    assert "No supported IKEA regional presence" in (
        result.bundle.evidence_gaps[0].summary
    )


def test_ikea_runtime_selects_fixture_disabled_and_search_modes() -> None:
    default_provider = build_ikea_store_intelligence_provider(
        Settings(_env_file=None)  # type: ignore[call-arg]
    )
    disabled_provider = build_ikea_store_intelligence_provider(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            ikea_store_intelligence_provider=(
                IKEAStoreIntelligenceProviderName.DISABLED
            ),
        )
    )
    live_provider = build_ikea_store_intelligence_provider(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            ikea_store_intelligence_provider=IKEAStoreIntelligenceProviderName.SEARCH,
            ikea_store_intelligence_provider_enabled=True,
            search_provider=SearchProviderName.TAVILY,
            search_provider_enabled=True,
            tavily_api_key="fixture-key",
        )
    )
    missing_search_provider = build_ikea_store_intelligence_provider(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            ikea_store_intelligence_provider=IKEAStoreIntelligenceProviderName.SEARCH,
            ikea_store_intelligence_provider_enabled=True,
        )
    )
    fixture_search_provider = build_ikea_store_intelligence_provider(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            ikea_store_intelligence_provider=IKEAStoreIntelligenceProviderName.SEARCH,
            ikea_store_intelligence_provider_enabled=True,
            search_provider=SearchProviderName.FIXTURE,
            search_provider_enabled=True,
        )
    )

    assert isinstance(default_provider, FakeIKEAStoreIntelligenceProvider)
    assert isinstance(disabled_provider, FakeIKEAStoreIntelligenceProvider)
    assert disabled_provider.disabled is True
    assert isinstance(live_provider, IKEARegionalStoreDiscoveryProvider)
    assert isinstance(missing_search_provider, FakeIKEAStoreIntelligenceProvider)
    assert isinstance(fixture_search_provider, FakeIKEAStoreIntelligenceProvider)


def test_ikea_search_mode_warns_when_general_search_is_disabled() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        ikea_store_intelligence_provider=IKEAStoreIntelligenceProviderName.SEARCH,
        ikea_store_intelligence_provider_enabled=True,
    )

    warnings = settings.provider_readiness_warnings()

    assert len(warnings) == 1
    assert warnings[0].provider == "ikea_store_intelligence:search"
    assert warnings[0].code == "provider_dependency_disabled"
