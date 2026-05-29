from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import (
    Confidence,
    ConfidenceLevel,
    ConflictSeverity,
    EvidenceConflict,
    EvidenceType,
    ExtractionStatus,
    ProviderMetadata,
    SearchIntent,
    SearchPlan,
    SearchQuery,
    SearchResult,
    SourceEvidence,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
    TimestampReference,
    TranscriptAvailability,
    VideoSource,
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


def make_video() -> VideoSource:
    return VideoSource(
        video_id="video-123",
        url="https://www.youtube.com/watch?v=video-123",
        title="Long-term laptop review",
        channel_name="Review Channel",
        published_at="2026-05-29T00:00:00Z",
        transcript_availability=TranscriptAvailability.UNAVAILABLE,
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
        evidence_type=EvidenceType.PRICE,
        claim="The listed price is 999 USD.",
        confidence=make_confidence(),
        source_quality=make_quality(SourceQualityLevel.STRONG),
    )

    assert evidence.source_id == source_id
    assert evidence.evidence_type == EvidenceType.PRICE
    assert evidence.confidence.score == 0.74
    assert evidence.source_quality.level == SourceQualityLevel.STRONG

    with pytest.raises(ValidationError):
        SourceEvidence(
            source_id=source_id,
            evidence_type="unsupported",
            claim="The listed price is 999 USD.",
            confidence=make_confidence(),
            source_quality=make_quality(),
        )


def test_video_evidence_requires_video_context_and_supports_timestamp_references() -> None:
    video = make_video()
    evidence = SourceEvidence(
        source_id=new_id(),
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
    assert evidence.video.transcript_availability == TranscriptAvailability.UNAVAILABLE
    assert evidence.timestamp_references[0].start_seconds == 92.5

    with pytest.raises(ValidationError):
        SourceEvidence(
            source_id=new_id(),
            evidence_type=EvidenceType.VIDEO_CLAIM,
            claim="A video claim without video context.",
            confidence=make_confidence(),
            source_quality=make_quality(),
        )

    with pytest.raises(ValidationError):
        SourceEvidence(
            source_id=new_id(),
            evidence_type=EvidenceType.REVIEW_CLAIM,
            claim="A timestamped claim without video context.",
            confidence=make_confidence(),
            source_quality=make_quality(),
            timestamp_references=(TimestampReference(start_seconds=3.0),),
        )


def test_timestamp_reference_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError):
        TimestampReference(start_seconds=30.0, end_seconds=29.9)


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
