from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import (
    AmazonEvidenceFactType,
    AmazonListingContext,
    AmazonProductEvidence,
    AmazonProductEvidenceBundle,
    ChannelSignal,
    CommunityDiscussionContext,
    CommunityDiscussionEvidence,
    CommunityDiscussionEvidenceBundle,
    Confidence,
    ConfidenceLevel,
    ConflictSeverity,
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceConflict,
    EvidenceType,
    ExtractionStatus,
    FieldSource,
    IKEAEvidenceFactType,
    IKEAStoreContext,
    IKEAStoreEvidence,
    IKEAStoreEvidenceBundle,
    Money,
    ProviderMetadata,
    RegionalStoreAvailability,
    ReusableSourceIntelligenceRequest,
    SearchIntent,
    SearchPlan,
    SearchQuery,
    SearchResult,
    SourceEvidence,
    SourceEvidenceGap,
    SourceId,
    SourceIntelligenceCapability,
    SourceIntelligenceCapabilityDescriptor,
    SourceQuality,
    SourceQualityLevel,
    SourceReference,
    SourceSnapshot,
    SourceType,
    TimestampReference,
    TranscriptAvailability,
    VideoReviewEvidence,
    VideoReviewEvidenceBundle,
    VideoSource,
    VideoTranscriptSegment,
    new_id,
    ShoppingBrief,
)


def make_provider() -> ProviderMetadata:
    return ProviderMetadata(
        provider_name="fixture-search",
        provider_result_id="result-123",
        raw={"rank": 1, "safe_search": True},
    )


def make_search_query() -> SearchQuery:
    return SearchQuery(
        query="best travel laptop reviews",
        intent=SearchIntent.REVIEW,
        region_code="US",
        required_source_types=(SourceType.PROFESSIONAL_REVIEW,),
    )


def make_confidence() -> Confidence:
    return Confidence(score=0.74, level=ConfidenceLevel.MEDIUM)


def make_quality(level: SourceQualityLevel = SourceQualityLevel.ADEQUATE) -> SourceQuality:
    return SourceQuality(
        level=level,
        score=0.7,
        rationale="Known review source with product-specific evidence.",
    )


def make_video(
    transcript_availability: TranscriptAvailability = TranscriptAvailability.UNAVAILABLE,
) -> VideoSource:
    return VideoSource(
        video_id="video-123",
        url="https://www.youtube.com/watch?v=video-123",
        title="Long-term laptop review",
        channel_name="Review Channel",
        published_at="2026-05-29T00:00:00Z",
        transcript_availability=transcript_availability,
    )


def make_source_reference(source_id: SourceId) -> SourceReference:
    return SourceReference(
        source_id=source_id,
        url="https://www.youtube.com/watch?v=video-123",
        title="Long-term laptop review",
        accessed_at="2026-05-29T00:30:00Z",
    )


def make_product_target() -> EvidenceTarget:
    return EvidenceTarget(target_type=EvidenceTargetType.PRODUCT, product_id=new_id())


def make_listing_target() -> EvidenceTarget:
    return EvidenceTarget(target_type=EvidenceTargetType.LISTING, listing_id=new_id())


def make_source_metadata_target(source_id: SourceId) -> EvidenceTarget:
    return EvidenceTarget(
        target_type=EvidenceTargetType.SOURCE_METADATA,
        source_id=source_id,
    )


def make_review_target() -> EvidenceTarget:
    return EvidenceTarget(
        target_type=EvidenceTargetType.REVIEW,
        review_id="review-summary",
    )


def make_region_target(region_code: str = "US") -> EvidenceTarget:
    return EvidenceTarget(
        target_type=EvidenceTargetType.REGION,
        region_code=region_code,
    )


def make_brief() -> ShoppingBrief:
    return ShoppingBrief(
        original_query="Find a compact desk chair",
        category="office chair",
        category_source=FieldSource.INFERRED,
    )


def test_search_plan_requires_at_least_one_query() -> None:
    plan = SearchPlan(queries=(make_search_query(),), rationale="Find review evidence.")

    assert plan.queries[0].region_code == "US"
    assert plan.queries[0].intent == SearchIntent.REVIEW

    with pytest.raises(ValidationError):
        SearchPlan(queries=())


def test_reusable_source_intelligence_request_preserves_capabilities_and_targets() -> None:
    product_id = new_id()
    listing_id = new_id()
    request = ReusableSourceIntelligenceRequest(
        brief=make_brief(),
        target_region_code="US",
        product_ids=(product_id,),
        listing_ids=(listing_id,),
        query_hints=("long-term owner complaints",),
        requested_capabilities=(
            SourceIntelligenceCapability.VIDEO_REVIEW,
            SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
            SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
            SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
        ),
        allowed_capabilities=(
            SourceIntelligenceCapabilityDescriptor(
                capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
                provider_name="fixture-search",
                domain_scoped_search=True,
                compliance_notes=("Public reddit.com results only.",),
            ),
        ),
    )

    assert request.brief.category == "office chair"
    assert request.product_ids == (product_id,)
    assert request.listing_ids == (listing_id,)
    assert request.target_region_code == "US"
    assert (
        request.allowed_capabilities[0].capability
        == SourceIntelligenceCapability.COMMUNITY_DISCUSSION
    )

    with pytest.raises(ValidationError):
        ReusableSourceIntelligenceRequest(
            brief=make_brief(),
            requested_capabilities=(),
        )


def test_search_result_requires_source_url_and_provider_metadata() -> None:
    result = SearchResult(
        query=make_search_query(),
        url="https://example.com/reviews/travel-laptop",
        title="Best travel laptops",
        snippet="A source-backed review roundup.",
        source_type=SourceType.PROFESSIONAL_REVIEW,
        provider=make_provider(),
        quality=make_quality(),
    )

    assert result.provider.provider_name == "fixture-search"
    assert result.provider.raw["rank"] == 1
    assert str(result.url) == "https://example.com/reviews/travel-laptop"

    with pytest.raises(ValidationError):
        SearchResult(
            query=make_search_query(),
            url="not-a-url",
            title="Bad URL",
            provider=make_provider(),
        )

    with pytest.raises(ValidationError):
        SearchResult(
            query=make_search_query(),
            url="https://example.com/reviews/travel-laptop",
            title="Missing provider",
        )


def test_source_snapshot_requires_url_provider_quality_and_video_details() -> None:
    snapshot = SourceSnapshot(
        url="https://example.com/product",
        source_type=SourceType.RETAILER_LISTING,
        provider=make_provider(),
        title="Retail listing",
        captured_at="2026-05-29T00:00:00Z",
        extraction_status=ExtractionStatus.PARTIAL,
        quality=make_quality(SourceQualityLevel.MIXED),
    )

    assert snapshot.quality.level == SourceQualityLevel.MIXED
    assert snapshot.captured_at == datetime(2026, 5, 29, 0, 0, tzinfo=UTC)

    with pytest.raises(ValidationError):
        SourceSnapshot(
            url="https://www.youtube.com/watch?v=video-123",
            source_type=SourceType.VIDEO,
            provider=make_provider(),
        )


def test_source_evidence_preserves_evidence_type_confidence_and_source_quality() -> None:
    source_id = new_id()
    evidence = SourceEvidence(
        source_id=source_id,
        target=make_listing_target(),
        evidence_type=EvidenceType.PRICE,
        claim="The listed price is 999 USD.",
        confidence=make_confidence(),
        source_quality=make_quality(SourceQualityLevel.STRONG),
    )

    assert evidence.source_id == source_id
    assert evidence.target.target_type == EvidenceTargetType.LISTING
    assert evidence.evidence_type == EvidenceType.PRICE
    assert evidence.confidence.score == 0.74
    assert evidence.source_quality.level == SourceQualityLevel.STRONG

    with pytest.raises(ValidationError):
        SourceEvidence(
            source_id=source_id,
            target=make_listing_target(),
            evidence_type="unsupported",
            claim="The listed price is 999 USD.",
            confidence=make_confidence(),
            source_quality=make_quality(),
        )


def test_video_evidence_requires_video_context_and_supports_timestamp_references() -> None:
    video = make_video()
    evidence = SourceEvidence(
        source_id=new_id(),
        target=make_product_target(),
        evidence_type=EvidenceType.VIDEO_CLAIM,
        claim="The reviewer says battery life dropped after six months.",
        confidence=make_confidence(),
        source_quality=make_quality(SourceQualityLevel.ADEQUATE),
        video=video,
        timestamp_references=(
            TimestampReference(start_seconds=92.5, end_seconds=104.0, label="Battery"),
        ),
    )

    assert evidence.video is not None
    assert evidence.target.target_type == EvidenceTargetType.PRODUCT
    assert evidence.video.transcript_availability == TranscriptAvailability.UNAVAILABLE
    assert evidence.timestamp_references[0].start_seconds == 92.5

    with pytest.raises(ValidationError):
        SourceEvidence(
            source_id=new_id(),
            target=make_product_target(),
            evidence_type=EvidenceType.VIDEO_CLAIM,
            claim="A video claim without video context.",
            confidence=make_confidence(),
            source_quality=make_quality(),
        )

    with pytest.raises(ValidationError):
        SourceEvidence(
            source_id=new_id(),
            target=make_product_target(),
            evidence_type=EvidenceType.REVIEW_CLAIM,
            claim="A timestamped claim without video context.",
            confidence=make_confidence(),
            source_quality=make_quality(),
            timestamp_references=(TimestampReference(start_seconds=3.0),),
        )


def test_timestamp_reference_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError):
        TimestampReference(start_seconds=30.0, end_seconds=29.9)


def test_video_review_bundle_supports_transcripts_and_timestamped_evidence() -> None:
    source_id = new_id()
    video = make_video(TranscriptAvailability.AVAILABLE)
    segment = VideoTranscriptSegment(
        video_id=video.video_id,
        start_seconds=92.5,
        end_seconds=104.0,
        text="After six months the battery life dropped by about an hour.",
    )
    evidence = VideoReviewEvidence(
        source_id=source_id,
        target=make_product_target(),
        video_id=video.video_id,
        claim="The reviewer says battery life dropped after six months.",
        confidence=make_confidence(),
        source_quality=make_quality(),
        timestamp_references=(
            TimestampReference(start_seconds=92.5, end_seconds=104.0, label="Battery"),
        ),
        transcript_segment_ids=(segment.segment_id,),
        sponsorship_disclosed=False,
        affiliate_links_disclosed=True,
        affiliate_bias_risk=Confidence(
            score=0.28,
            level=ConfidenceLevel.LOW,
            rationale="Affiliate links are disclosed but the claim is transcript-backed.",
        ),
    )
    bundle = VideoReviewEvidenceBundle(
        videos=(video,),
        source_references=(make_source_reference(source_id),),
        transcript_segments=(segment,),
        evidence=(evidence,),
    )

    assert bundle.videos[0].transcript_availability == TranscriptAvailability.AVAILABLE
    assert bundle.transcript_segments[0].text is not None
    assert bundle.evidence[0].timestamp_references[0].start_seconds == 92.5
    assert bundle.evidence[0].affiliate_links_disclosed is True


def test_video_review_bundle_supports_videos_without_transcripts_as_metadata_only() -> None:
    source_id = new_id()
    video = VideoSource(
        video_id="video-456",
        url="https://www.youtube.com/watch?v=video-456",
        title="Sponsored launch overview",
        channel_name="Brand Review Channel",
        transcript_availability=TranscriptAvailability.UNAVAILABLE,
        channel_signals=(
            ChannelSignal.REVIEW_FOCUSED,
            ChannelSignal.SPONSORSHIP_DISCLOSED,
            ChannelSignal.AFFILIATE_LINKS_DISCLOSED,
        ),
        sponsorship_disclosed=True,
        affiliate_links_disclosed=True,
        affiliate_bias_risk=Confidence(
            score=0.7,
            level=ConfidenceLevel.HIGH,
            rationale="The video discloses sponsorship and affiliate links.",
        ),
        bias_notes="Treat as metadata-only due to unavailable transcript.",
    )
    evidence = VideoReviewEvidence(
        source_id=source_id,
        target=make_source_metadata_target(source_id),
        video_id=video.video_id,
        claim=(
            "The video exists as a sponsored overview, but no "
            "transcript-backed claim was extracted."
        ),
        confidence=Confidence(
            score=0.42,
            level=ConfidenceLevel.LOW,
            rationale="Only title, channel, and disclosure metadata are available.",
        ),
        source_quality=make_quality(SourceQualityLevel.WEAK),
        metadata_only=True,
        sponsorship_disclosed=True,
        affiliate_links_disclosed=True,
        affiliate_bias_risk=video.affiliate_bias_risk,
    )
    bundle = VideoReviewEvidenceBundle(
        videos=(video,),
        source_references=(
            SourceReference(
                source_id=source_id,
                url=video.url,
                title=video.title,
            ),
        ),
        evidence=(evidence,),
    )

    assert bundle.transcript_segments == ()
    assert bundle.evidence[0].metadata_only is True
    assert bundle.videos[0].channel_signals[0] == ChannelSignal.REVIEW_FOCUSED

    with pytest.raises(ValidationError):
        VideoReviewEvidence(
            source_id=source_id,
            target=make_source_metadata_target(source_id),
            video_id=video.video_id,
            claim="Metadata-only evidence cannot cite a timestamp.",
            confidence=make_confidence(),
            source_quality=make_quality(),
            metadata_only=True,
            timestamp_references=(TimestampReference(start_seconds=15.0),),
        )


def test_video_review_bundle_preserves_explicit_transcript_gaps() -> None:
    source_id = new_id()
    video = make_video(TranscriptAvailability.PARTIAL)
    gap = VideoTranscriptSegment(
        video_id=video.video_id,
        start_seconds=210.0,
        end_seconds=245.0,
        availability=TranscriptAvailability.RESTRICTED,
        gap_reason="Captions are unavailable for the long-term durability discussion.",
    )
    evidence = VideoReviewEvidence(
        source_id=source_id,
        target=make_product_target(),
        video_id=video.video_id,
        claim=(
            "The video appears to discuss durability, but the transcript is "
            "missing for that section."
        ),
        confidence=Confidence(
            score=0.25,
            level=ConfidenceLevel.LOW,
            rationale="Timestamp is known, but the transcript text is unavailable.",
        ),
        source_quality=make_quality(SourceQualityLevel.MIXED),
        timestamp_references=(
            TimestampReference(start_seconds=210.0, end_seconds=245.0),
        ),
        transcript_segment_ids=(gap.segment_id,),
        transcript_gap="Missing transcript text prevents extracting a durability claim.",
    )
    bundle = VideoReviewEvidenceBundle(
        videos=(video,),
        source_references=(make_source_reference(source_id),),
        transcript_segments=(gap,),
        evidence=(evidence,),
        transcript_gap_notes=("Durability segment transcript is restricted.",),
    )

    assert bundle.videos[0].transcript_availability == TranscriptAvailability.PARTIAL
    assert bundle.transcript_segments[0].text is None
    assert bundle.transcript_segments[0].gap_reason is not None
    assert bundle.evidence[0].transcript_gap is not None

    with pytest.raises(ValidationError):
        VideoTranscriptSegment(
            video_id=video.video_id,
            start_seconds=210.0,
            availability=TranscriptAvailability.RESTRICTED,
        )


def test_evidence_targets_distinguish_product_listing_seller_and_source_metadata() -> None:
    product_id = new_id()
    listing_id = new_id()
    candidate_id = new_id()
    source_id = new_id()

    product_target = EvidenceTarget(
        target_type=EvidenceTargetType.PRODUCT,
        product_id=product_id,
    )
    listing_target = EvidenceTarget(
        target_type=EvidenceTargetType.LISTING,
        listing_id=listing_id,
    )
    seller_target = EvidenceTarget(
        target_type=EvidenceTargetType.SELLER,
        listing_id=listing_id,
    )
    candidate_target = EvidenceTarget(
        target_type=EvidenceTargetType.CANDIDATE,
        candidate_id=candidate_id,
    )
    metadata_target = EvidenceTarget(
        target_type=EvidenceTargetType.SOURCE_METADATA,
        source_id=source_id,
    )

    assert product_target.product_id == product_id
    assert listing_target.listing_id == listing_id
    assert seller_target.listing_id == listing_id
    assert candidate_target.candidate_id == candidate_id
    assert metadata_target.source_id == source_id

    with pytest.raises(ValidationError):
        EvidenceTarget(target_type=EvidenceTargetType.PRODUCT)

    with pytest.raises(ValidationError):
        EvidenceTarget(
            target_type=EvidenceTargetType.SOURCE_METADATA,
            source_id=source_id,
            product_id=product_id,
        )


def test_metadata_only_video_evidence_must_target_source_metadata() -> None:
    source_id = new_id()
    video = make_video(TranscriptAvailability.UNAVAILABLE)

    metadata_evidence = VideoReviewEvidence(
        source_id=source_id,
        target=make_source_metadata_target(source_id),
        video_id=video.video_id,
        claim=(
            "The source metadata discloses sponsorship, but no product claim "
            "was extracted."
        ),
        confidence=make_confidence(),
        source_quality=make_quality(SourceQualityLevel.WEAK),
        metadata_only=True,
    )

    assert metadata_evidence.target.target_type == EvidenceTargetType.SOURCE_METADATA

    with pytest.raises(ValidationError):
        VideoReviewEvidence(
            source_id=source_id,
            target=make_product_target(),
            video_id=video.video_id,
            claim="Metadata-only evidence cannot target a product claim.",
            confidence=make_confidence(),
            source_quality=make_quality(SourceQualityLevel.WEAK),
            metadata_only=True,
        )

    with pytest.raises(ValidationError):
        VideoReviewEvidence(
            source_id=source_id,
            target=make_source_metadata_target(new_id()),
            video_id=video.video_id,
            claim="Metadata-only evidence must target the same source.",
            confidence=make_confidence(),
            source_quality=make_quality(SourceQualityLevel.WEAK),
            metadata_only=True,
        )


def test_community_discussion_bundle_preserves_reddit_context_and_quality_gaps() -> None:
    source_id = new_id()
    product_id = new_id()
    discussion = CommunityDiscussionContext(
        source_id=source_id,
        url="https://www.reddit.com/r/BuyItForLife/comments/thread123/example/",
        community_name="r/BuyItForLife",
        thread_id="thread123",
        thread_title="Long-term desk chair experiences",
        comment_id="comment456",
        posted_at="2026-05-20T00:00:00Z",
        engagement_score=42,
        comment_count=18,
        extracted_public_summary="Multiple owners mention armrest wobble.",
    )
    evidence = CommunityDiscussionEvidence(
        source_id=source_id,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.PRODUCT,
            product_id=product_id,
        ),
        claim="Owners repeatedly mention armrest wobble after extended use.",
        confidence=Confidence(
            score=0.58,
            level=ConfidenceLevel.MEDIUM,
            rationale="Recurring community signal, but still anecdotal.",
        ),
        source_quality=make_quality(SourceQualityLevel.MIXED),
        context_source_ids=(source_id,),
        recurring_signal=True,
        qualitative_signal=True,
        evidence_quality_warnings=("Community discussion is anecdotal.",),
    )
    bundle = CommunityDiscussionEvidenceBundle(
        source_references=(
            SourceReference(
                source_id=source_id,
                url=discussion.url,
                title=discussion.thread_title,
            ),
        ),
        discussions=(discussion,),
        evidence=(evidence,),
        evidence_gaps=(
            SourceEvidenceGap(
                capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.PRODUCT,
                    product_id=product_id,
                ),
                source_id=source_id,
                summary="No official warranty fact was available from Reddit.",
                reason="Community threads are not authoritative warranty sources.",
                source_quality=make_quality(SourceQualityLevel.WEAK),
            ),
        ),
    )

    assert bundle.evidence[0].qualitative_signal is True
    assert bundle.evidence[0].target.target_type == EvidenceTargetType.PRODUCT
    assert bundle.discussions[0].community_name == "r/BuyItForLife"
    assert bundle.evidence_gaps[0].source_id == source_id


def test_source_evidence_bundles_reject_claims_without_bundled_source_references() -> None:
    source_id = new_id()
    unsupported_source_id = new_id()

    with pytest.raises(ValidationError):
        CommunityDiscussionEvidenceBundle(
            source_references=(
                SourceReference(
                    source_id=source_id,
                    url="https://www.reddit.com/r/example/comments/thread/example/",
                ),
            ),
            discussions=(
                CommunityDiscussionContext(
                    source_id=source_id,
                    url="https://www.reddit.com/r/example/comments/thread/example/",
                ),
            ),
            evidence=(
                CommunityDiscussionEvidence(
                    source_id=unsupported_source_id,
                    target=make_product_target(),
                    claim="This unsupported claim cites a source outside the bundle.",
                    confidence=make_confidence(),
                    source_quality=make_quality(),
                ),
            ),
        )


def test_amazon_product_bundle_keeps_product_listing_seller_review_and_region_facts_distinct() -> None:
    source_id = new_id()
    product_id = new_id()
    listing_id = new_id()
    listing_context = AmazonListingContext(
        source_id=source_id,
        marketplace_name="Amazon",
        marketplace_domain="amazon.com",
        marketplace_country_code="US",
        listing_url="https://www.amazon.com/dp/B012345678",
        asin="B012345678",
        product_title="Fixture Desk Chair",
        seller_name="Third Party Seller",
        fulfillment="Fulfilled by Amazon",
        ships_to_region_code="US",
        ships_to_region=True,
        review_count=128,
        average_rating=4.2,
    )
    bundle = AmazonProductEvidenceBundle(
        source_references=(
            SourceReference(
                source_id=source_id,
                url=listing_context.listing_url,
                title="Fixture Desk Chair",
            ),
        ),
        listing_contexts=(listing_context,),
        evidence=(
            AmazonProductEvidence(
                source_id=source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.PRODUCT,
                    product_id=product_id,
                ),
                fact_type=AmazonEvidenceFactType.PRODUCT_PAGE_FACT,
                claim="The product page describes adjustable armrests.",
                confidence=make_confidence(),
                source_quality=make_quality(SourceQualityLevel.ADEQUATE),
                listing_context_source_id=source_id,
            ),
            AmazonProductEvidence(
                source_id=source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.LISTING,
                    listing_id=listing_id,
                ),
                fact_type=AmazonEvidenceFactType.LISTING_IDENTITY,
                claim="The listing is identified by ASIN B012345678.",
                confidence=make_confidence(),
                source_quality=make_quality(SourceQualityLevel.ADEQUATE),
                listing_context_source_id=source_id,
            ),
            AmazonProductEvidence(
                source_id=source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.SELLER,
                    listing_id=listing_id,
                ),
                fact_type=AmazonEvidenceFactType.SELLER_FULFILLMENT,
                claim="The listing names a third-party seller with FBA fulfillment.",
                confidence=make_confidence(),
                source_quality=make_quality(SourceQualityLevel.MIXED),
                listing_context_source_id=source_id,
            ),
            AmazonProductEvidence(
                source_id=source_id,
                target=make_review_target(),
                fact_type=AmazonEvidenceFactType.REVIEW_SUMMARY,
                claim="The listing shows 128 reviews with a 4.2 average rating.",
                confidence=make_confidence(),
                source_quality=make_quality(SourceQualityLevel.MIXED),
                listing_context_source_id=source_id,
            ),
            AmazonProductEvidence(
                source_id=source_id,
                target=make_region_target("US"),
                fact_type=AmazonEvidenceFactType.REGIONAL_AVAILABILITY,
                claim="The listing is marked as shipping to the US.",
                confidence=make_confidence(),
                source_quality=make_quality(SourceQualityLevel.ADEQUATE),
                listing_context_source_id=source_id,
            ),
        ),
        evidence_gaps=(
            SourceEvidenceGap(
                capability=SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
                target=make_review_target(),
                source_id=source_id,
                summary="Individual review text was not available in the fixture.",
            ),
        ),
    )

    target_types = {item.target.target_type for item in bundle.evidence}
    assert EvidenceTargetType.PRODUCT in target_types
    assert EvidenceTargetType.LISTING in target_types
    assert EvidenceTargetType.SELLER in target_types
    assert EvidenceTargetType.REVIEW in target_types
    assert EvidenceTargetType.REGION in target_types
    assert bundle.listing_contexts[0].asin == "B012345678"
    assert bundle.evidence_gaps[0].target is not None

    with pytest.raises(ValidationError):
        AmazonProductEvidence(
            source_id=source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product_id,
            ),
            fact_type=AmazonEvidenceFactType.REVIEW_SUMMARY,
            claim="Review summaries cannot be collapsed into product facts.",
            confidence=make_confidence(),
            source_quality=make_quality(),
        )


def test_ikea_store_bundle_keeps_official_product_and_region_facts_distinct() -> None:
    source_id = new_id()
    product_id = new_id()
    store_context = IKEAStoreContext(
        source_id=source_id,
        country_code="US",
        official_url="https://www.ikea.com/us/en/p/example-chair-12345678/",
        product_code="12345678",
        product_name="Example chair",
        store_name="IKEA US",
        delivery_area="US online delivery",
        price=Money(amount="129.99", currency="USD"),
        availability=RegionalStoreAvailability.AVAILABLE,
    )
    bundle = IKEAStoreEvidenceBundle(
        source_references=(
            SourceReference(
                source_id=source_id,
                url=store_context.official_url,
                title="Example chair",
            ),
        ),
        store_contexts=(store_context,),
        evidence=(
            IKEAStoreEvidence(
                source_id=source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.PRODUCT,
                    product_id=product_id,
                ),
                fact_type=IKEAEvidenceFactType.OFFICIAL_PRODUCT_FACT,
                claim="The official IKEA US page identifies product code 12345678.",
                confidence=make_confidence(),
                source_quality=make_quality(SourceQualityLevel.STRONG),
                store_context_source_id=source_id,
            ),
            IKEAStoreEvidence(
                source_id=source_id,
                target=make_region_target("US"),
                fact_type=IKEAEvidenceFactType.REGIONAL_PRICE,
                claim="The IKEA US page lists the regional price as 129.99 USD.",
                confidence=make_confidence(),
                source_quality=make_quality(SourceQualityLevel.STRONG),
                store_context_source_id=source_id,
            ),
            IKEAStoreEvidence(
                source_id=source_id,
                target=make_region_target("US"),
                fact_type=IKEAEvidenceFactType.REGIONAL_AVAILABILITY,
                claim="The IKEA US page marks the product as available.",
                confidence=make_confidence(),
                source_quality=make_quality(SourceQualityLevel.STRONG),
                store_context_source_id=source_id,
            ),
        ),
        evidence_gaps=(
            SourceEvidenceGap(
                capability=SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
                target=make_region_target("PH"),
                summary="No IKEA Philippines official-store evidence was checked.",
                reason="Fixture only covers the US regional store.",
            ),
        ),
    )

    assert bundle.store_contexts[0].country_code == "US"
    assert bundle.store_contexts[0].price is not None
    assert bundle.evidence[0].target.target_type == EvidenceTargetType.PRODUCT
    assert bundle.evidence[1].target.target_type == EvidenceTargetType.REGION
    assert bundle.evidence_gaps[0].target is not None

    with pytest.raises(ValidationError):
        IKEAStoreEvidence(
            source_id=source_id,
            target=make_listing_target(),
            fact_type=IKEAEvidenceFactType.REGIONAL_PRICE,
            claim="Regional IKEA prices cannot be collapsed into listing facts.",
            confidence=make_confidence(),
            source_quality=make_quality(),
        )


def test_material_conflict_requires_multiple_evidence_records() -> None:
    first_evidence_id = new_id()
    second_evidence_id = new_id()
    conflict = EvidenceConflict(
        evidence_ids=(first_evidence_id, second_evidence_id),
        summary="One source reports a two-year warranty while another reports one year.",
        severity=ConflictSeverity.MATERIAL,
        affects_decision=True,
    )

    assert conflict.severity == ConflictSeverity.MATERIAL
    assert conflict.affects_decision is True
    assert conflict.evidence_ids == (first_evidence_id, second_evidence_id)

    with pytest.raises(ValidationError):
        EvidenceConflict(
            evidence_ids=(first_evidence_id,),
            summary="Only one evidence record cannot form a conflict.",
            severity=ConflictSeverity.HIGH,
        )
