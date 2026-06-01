from inspect import Signature, signature

import pytest
from pydantic import ValidationError

from app.providers import (
    ExtractionProvider,
    FakeExtractionProvider,
    FakeMarketplaceAvailabilityProvider,
    FakeOfficialStoreProvider,
    FakeSearchProvider,
    FakeShoppingProvider,
    FakeTranscriptProvider,
    FakeVideoSearchProvider,
    MarketplaceAvailabilityProvider,
    OfficialStoreProvider,
    ProviderRunStatus,
    SearchProvider,
    SearchProviderOptions,
    ShoppingProvider,
    ShoppingProviderOptions,
    SourceAllowAvoidPolicy,
    SourcePolicyAction,
    SourcePolicyRule,
    TranscriptProvider,
    VideoSearchProvider,
)
from app.schemas.products import CanonicalProduct, ProductListing
from app.schemas.search_sources import (
    SearchIntent,
    SearchQuery,
    SourceSnapshot,
    SourceType,
    TranscriptAvailability,
    VideoReviewEvidenceBundle,
    VideoSource,
)


def test_provider_protocols_declare_typed_boundaries() -> None:
    protocol_methods = (
        SearchProvider.search,
        ExtractionProvider.extract,
        ShoppingProvider.search_products,
        VideoSearchProvider.search_videos,
        TranscriptProvider.fetch_transcript,
        MarketplaceAvailabilityProvider.check_availability,
        OfficialStoreProvider.find_official_sources,
    )

    for method in protocol_methods:
        method_signature = signature(method)

        assert method_signature.return_annotation is not Signature.empty
        assert all(
            parameter.annotation is not Signature.empty
            for name, parameter in method_signature.parameters.items()
            if name != "self"
        )


def test_source_allow_avoid_policy_keeps_buckets_explicit() -> None:
    policy = SourceAllowAvoidPolicy(
        allow=(
            SourcePolicyRule(
                action=SourcePolicyAction.ALLOW,
                domain="example.com",
                reason="Approved fixture domain.",
            ),
        ),
        avoid=(
            SourcePolicyRule(
                action=SourcePolicyAction.AVOID,
                source_type=SourceType.COMMUNITY_DISCUSSION,
                reason="Low-confidence source type for this query.",
            ),
        ),
    )

    assert policy.allow[0].domain == "example.com"
    assert policy.avoid[0].source_type == SourceType.COMMUNITY_DISCUSSION

    with pytest.raises(ValidationError):
        SourcePolicyRule(action=SourcePolicyAction.AVOID, reason="No selector.")

    with pytest.raises(ValidationError):
        SourceAllowAvoidPolicy(allow=(policy.avoid[0],))


@pytest.mark.asyncio
async def test_fake_providers_can_be_swapped_through_interfaces() -> None:
    search_provider: SearchProvider = FakeSearchProvider()
    extraction_provider: ExtractionProvider = FakeExtractionProvider()
    shopping_provider: ShoppingProvider = FakeShoppingProvider()

    query = SearchQuery(
        query="best monitor reviews",
        intent=SearchIntent.REVIEW,
        required_source_types=(SourceType.PROFESSIONAL_REVIEW,),
    )
    search_results = await search_provider.search(
        query,
        SearchProviderOptions(max_results=2),
    )
    assert len(search_results) == 2
    assert search_results[0].query == query
    assert search_results[0].provider.provider_name == "fixture-search"

    snapshot = await extraction_provider.extract(search_results[0].url)
    assert isinstance(snapshot, SourceSnapshot)
    assert snapshot.provider.provider_name == "fixture-extraction"

    listings = await shopping_provider.search_products(
        "fixture monitor",
        ShoppingProviderOptions(region_code="us", max_results=1),
    )
    assert len(listings) == 1
    assert isinstance(listings[0], ProductListing)


@pytest.mark.asyncio
async def test_fake_source_intelligence_providers_model_video_transcript_states() -> None:
    video_provider: VideoSearchProvider = FakeVideoSearchProvider(
        transcript_availability=TranscriptAvailability.UNAVAILABLE,
        metadata_only=True,
    )
    video_result = await video_provider.search_videos("fixture monitor review")

    assert video_result.status == ProviderRunStatus.SUCCEEDED
    assert video_result.capabilities.supports_video_search is True
    assert isinstance(video_result.bundle, VideoReviewEvidenceBundle)
    assert video_result.bundle.videos[0].transcript_availability == (
        TranscriptAvailability.UNAVAILABLE
    )
    assert video_result.bundle.evidence[0].metadata_only is True

    video = video_result.bundle.videos[0]
    transcript_provider: TranscriptProvider = FakeTranscriptProvider()
    available_transcript = await transcript_provider.fetch_transcript(video)
    assert available_transcript.status == ProviderRunStatus.SUCCEEDED
    assert available_transcript.availability == TranscriptAvailability.AVAILABLE
    assert available_transcript.segments[0].text is not None
    assert available_transcript.capabilities.permits_transcript_text is True

    unavailable_transcript = await FakeTranscriptProvider(
        availability=TranscriptAvailability.UNAVAILABLE,
    ).fetch_transcript(video)
    assert unavailable_transcript.availability == TranscriptAvailability.UNAVAILABLE
    assert unavailable_transcript.segments == ()
    assert unavailable_transcript.gap_notes


@pytest.mark.asyncio
async def test_fake_source_intelligence_providers_model_disabled_providers() -> None:
    disabled_video_provider: VideoSearchProvider = FakeVideoSearchProvider(
        disabled=True,
    )
    disabled_video = await disabled_video_provider.search_videos("fixture review")
    assert disabled_video.status == ProviderRunStatus.DISABLED
    assert disabled_video.capabilities.enabled is False
    assert disabled_video.bundle is None

    disabled_transcript = await FakeTranscriptProvider(disabled=True).fetch_transcript(
        VideoSource(
            video_id="fixture-video-1",
            url="https://www.youtube.com/watch?v=fixture-video-1",
        ),
    )
    assert disabled_transcript.status == ProviderRunStatus.DISABLED
    assert disabled_transcript.capabilities.enabled is False

    product = CanonicalProduct(name="Fixture Monitor")
    marketplace_provider: MarketplaceAvailabilityProvider = (
        FakeMarketplaceAvailabilityProvider(disabled=True)
    )
    marketplace_result = await marketplace_provider.check_availability(product)
    assert marketplace_result.status == ProviderRunStatus.DISABLED
    assert marketplace_result.capabilities.supports_marketplace_availability is True

    official_store_provider: OfficialStoreProvider = FakeOfficialStoreProvider()
    official_store_result = await official_store_provider.find_official_sources(product)
    assert official_store_result.status == ProviderRunStatus.SUCCEEDED
    assert official_store_result.capabilities.supports_official_store_lookup is True
    assert official_store_result.source_snapshots[0].source_type == (
        SourceType.OFFICIAL_BRAND_PAGE
    )
