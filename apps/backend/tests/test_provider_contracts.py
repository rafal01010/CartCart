from inspect import Signature, signature

import pytest
from pydantic import ValidationError

from app.providers import (
    AmazonProductIntelligenceProvider,
    AmazonProductIntelligenceProviderOptions,
    CommunityDiscussionProvider,
    CommunityDiscussionProviderOptions,
    ExtractionProvider,
    FakeAmazonProductIntelligenceProvider,
    FakeCommunityDiscussionProvider,
    FakeExtractionProvider,
    FakeIKEAStoreIntelligenceProvider,
    FakeMarketplaceAvailabilityProvider,
    FakeOfficialStoreProvider,
    FakeSearchProvider,
    FakeShoppingProvider,
    FakeTranscriptProvider,
    FakeVideoSearchProvider,
    IKEAStoreIntelligenceProvider,
    IKEAStoreIntelligenceProviderOptions,
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
from app.schemas.ids import new_id
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.schemas.search_sources import (
    AmazonProductEvidenceBundle,
    CommunityDiscussionEvidenceBundle,
    IKEAStoreEvidenceBundle,
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
        CommunityDiscussionProvider.search_discussions,
        AmazonProductIntelligenceProvider.fetch_product_evidence,
        IKEAStoreIntelligenceProvider.fetch_store_evidence,
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
async def test_fake_source_intelligence_providers_return_evidence_bundles() -> None:
    product = CanonicalProduct(name="Fixture Monitor")
    listing = ProductListing(
        product_id=product.product_id,
        title="Fixture Monitor Amazon listing",
        url="https://www.amazon.com/dp/B012345678",
        seller=SellerProfile(seller_name="Fixture Marketplace Seller"),
        source_ids=(new_id(),),
    )

    community_provider: CommunityDiscussionProvider = (
        FakeCommunityDiscussionProvider()
    )
    community_result = await community_provider.search_discussions(
        "fixture monitor reddit",
        products=(product,),
        options=CommunityDiscussionProviderOptions(max_results=2),
    )
    assert community_result.status == ProviderRunStatus.SUCCEEDED
    assert community_result.capabilities.supports_domain_scoped_search is True
    assert community_result.capabilities.supports_public_page_extraction is True
    assert community_result.capabilities.supports_community_discussion_retrieval is True
    assert isinstance(community_result.bundle, CommunityDiscussionEvidenceBundle)
    assert community_result.bundle.evidence
    assert community_result.bundle.evidence_gaps

    amazon_provider: AmazonProductIntelligenceProvider = (
        FakeAmazonProductIntelligenceProvider()
    )
    amazon_result = await amazon_provider.fetch_product_evidence(
        product,
        listings=(listing,),
        options=AmazonProductIntelligenceProviderOptions(region_code="US"),
    )
    assert amazon_result.status == ProviderRunStatus.SUCCEEDED
    assert amazon_result.capabilities.supports_amazon_product_intelligence is True
    assert amazon_result.capabilities.supports_amazon_listing_identity is True
    assert amazon_result.capabilities.supports_amazon_review_signals is True
    assert amazon_result.capabilities.supports_regional_ship_to_evidence is True
    assert isinstance(amazon_result.bundle, AmazonProductEvidenceBundle)
    assert amazon_result.bundle.listing_contexts
    assert amazon_result.bundle.evidence
    assert amazon_result.bundle.evidence_gaps

    ikea_provider: IKEAStoreIntelligenceProvider = (
        FakeIKEAStoreIntelligenceProvider()
    )
    ikea_result = await ikea_provider.fetch_store_evidence(
        product,
        IKEAStoreIntelligenceProviderOptions(region_code="US"),
    )
    assert ikea_result.status == ProviderRunStatus.SUCCEEDED
    assert ikea_result.capabilities.supports_ikea_regional_store_lookup is True
    assert ikea_result.capabilities.supports_ikea_product_pages is True
    assert ikea_result.capabilities.supports_ikea_store_delivery_context is True
    assert isinstance(ikea_result.bundle, IKEAStoreEvidenceBundle)
    assert ikea_result.bundle.store_contexts
    assert ikea_result.bundle.evidence
    assert ikea_result.bundle.evidence_gaps


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

    disabled_community = await FakeCommunityDiscussionProvider(
        disabled=True,
    ).search_discussions("fixture reddit")
    assert disabled_community.status == ProviderRunStatus.DISABLED
    assert disabled_community.capabilities.enabled is False
    assert disabled_community.bundle is None

    disabled_amazon = await FakeAmazonProductIntelligenceProvider(
        disabled=True,
    ).fetch_product_evidence(product)
    assert disabled_amazon.status == ProviderRunStatus.DISABLED
    assert disabled_amazon.capabilities.enabled is False
    assert disabled_amazon.bundle is None

    disabled_ikea = await FakeIKEAStoreIntelligenceProvider(
        disabled=True,
    ).fetch_store_evidence(product)
    assert disabled_ikea.status == ProviderRunStatus.DISABLED
    assert disabled_ikea.capabilities.enabled is False
    assert disabled_ikea.bundle is None

    official_store_provider: OfficialStoreProvider = FakeOfficialStoreProvider()
    official_store_result = await official_store_provider.find_official_sources(product)
    assert official_store_result.status == ProviderRunStatus.SUCCEEDED
    assert official_store_result.capabilities.supports_official_store_lookup is True
    assert official_store_result.source_snapshots[0].source_type == (
        SourceType.OFFICIAL_BRAND_PAGE
    )
