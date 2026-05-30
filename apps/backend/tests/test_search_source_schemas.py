from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import (
    ChannelSignal,
    Confidence,
    ConfidenceLevel,
    ConflictSeverity,
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceConflict,
    EvidenceType,
    ExtractionStatus,
    ProviderMetadata,
    SearchIntent,
    SearchPlan,
    SearchQuery,
    SearchResult,
    SourceEvidence,
    SourceId,
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


def test_search_plan_requires_at_least_one_query() -> None:
    plan = SearchPlan(queries=(make_search_query(),), rationale="Find review evidence.")

    assert plan.queries[0].region_code == "US"
    assert plan.queries[0].intent == SearchIntent.REVIEW

    with pytest.raises(ValidationError):
        SearchPlan(queries=())


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
