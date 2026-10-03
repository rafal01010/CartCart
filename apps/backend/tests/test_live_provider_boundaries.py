import pytest
from pydantic import AnyHttpUrl

from app.core.settings import AgentWorkflowMode, Settings
from app.providers.runtime import (
    build_amazon_product_intelligence_provider,
    build_community_discussion_provider,
    build_extraction_provider,
    build_ikea_store_intelligence_provider,
    build_search_provider,
    build_transcript_provider,
    build_video_search_provider,
)
from app.providers.contracts import ProviderRunStatus
from app.schemas.products import CanonicalProduct
from app.schemas.search_sources import (
    ExtractionStatus,
    SearchIntent,
    SearchQuery,
    TranscriptAvailability,
    VideoSource,
)


@pytest.fixture(params=["unconfigured", "missing_credentials"])
def live_settings(request: pytest.FixtureRequest) -> Settings:
    configuration = (
        {
            "search_provider": "tavily",
            "search_provider_enabled": True,
            "video_search_provider": "youtube",
            "video_search_provider_enabled": True,
            "amazon_product_intelligence_provider": "serpapi",
            "amazon_product_intelligence_provider_enabled": True,
            "ikea_store_intelligence_provider": "search",
            "ikea_store_intelligence_provider_enabled": True,
        }
        if request.param == "missing_credentials"
        else {}
    )
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        agent_workflow_mode=AgentWorkflowMode.LIVE,
        tavily_api_key=None,
        youtube_data_api_key=None,
        serpapi_api_key=None,
        **configuration,
    )


@pytest.mark.asyncio
async def test_unavailable_live_search_does_not_invent_sources(
    live_settings: Settings,
) -> None:
    results = await build_search_provider(live_settings).search(
        SearchQuery(query="current iPhone Philippines", intent=SearchIntent.DISCOVERY)
    )
    assert results == ()


@pytest.mark.asyncio
async def test_unavailable_live_extraction_does_not_invent_page_content(
    live_settings: Settings,
) -> None:
    snapshot = await build_extraction_provider(live_settings).extract(
        AnyHttpUrl("https://www.apple.com/ph/iphone/")
    )
    assert snapshot.extraction_status == ExtractionStatus.EXCLUDED
    assert snapshot.extracted_content is None


@pytest.mark.asyncio
async def test_unavailable_live_transcript_does_not_invent_review_text(
    live_settings: Settings,
) -> None:
    result = await build_transcript_provider(live_settings).fetch_transcript(
        VideoSource(
            video_id="BaW_jenozKc",
            url="https://www.youtube.com/watch?v=BaW_jenozKc",
            title="Phone review",
        )
    )
    assert result.status == ProviderRunStatus.DISABLED
    assert result.availability == TranscriptAvailability.NOT_CHECKED
    assert result.segments == ()
    assert result.gap_notes == ("Transcript provider is disabled.",)


@pytest.mark.asyncio
async def test_unavailable_live_video_search_does_not_invent_videos(
    live_settings: Settings,
) -> None:
    result = await build_video_search_provider(live_settings).search_videos(
        "current iPhone reviews"
    )
    assert result.status == ProviderRunStatus.DISABLED
    assert result.bundle is None


@pytest.mark.asyncio
async def test_unavailable_live_amazon_does_not_invent_offers(
    live_settings: Settings,
) -> None:
    result = await build_amazon_product_intelligence_provider(
        live_settings
    ).fetch_product_evidence(CanonicalProduct(name="iPhone", category="smartphone"))
    assert result.status == ProviderRunStatus.DISABLED
    assert result.bundle is None


@pytest.mark.asyncio
async def test_unavailable_live_ikea_does_not_invent_store_evidence(
    live_settings: Settings,
) -> None:
    result = await build_ikea_store_intelligence_provider(
        live_settings
    ).fetch_store_evidence(CanonicalProduct(name="Desk", category="furniture"))
    assert result.status == ProviderRunStatus.DISABLED
    assert result.bundle is None


@pytest.mark.asyncio
async def test_unavailable_live_community_search_reports_an_evidence_gap(
    live_settings: Settings,
) -> None:
    result = await build_community_discussion_provider(
        live_settings
    ).search_discussions("current iPhone reviews")
    assert result.bundle is not None
    assert result.bundle.discussions == ()
    assert result.bundle.source_references == ()
    assert result.bundle.evidence_gaps[0].summary == (
        "No accessible public Reddit discussions were returned."
    )
