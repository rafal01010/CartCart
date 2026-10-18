from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid5

from app.schemas.ids import SourceId
from app.schemas.search_sources import (
    AmazonEvidenceContext,
    AmazonProductEvidence,
    AmazonProductEvidenceBundle,
    CommunityDiscussionEvidence,
    CommunityDiscussionEvidenceBundle,
    CommunityEvidenceContext,
    EvidenceType,
    IKEAEvidenceContext,
    IKEAStoreEvidence,
    IKEAStoreEvidenceBundle,
    SourceEvidence,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
    ReusableSourceEvidenceContext,
    VideoEvidenceContext,
    VideoReviewEvidenceBundle,
    VideoTranscriptSupport,
)

ReusableSourceBundle = (
    VideoReviewEvidenceBundle
    | CommunityDiscussionEvidenceBundle
    | AmazonProductEvidenceBundle
    | IKEAStoreEvidenceBundle
)


@dataclass(frozen=True)
class ReusableSourceProjection:
    evidence: tuple[SourceEvidence, ...] = ()
    gaps: tuple[SourceEvidenceGap, ...] = ()


_FACT_TYPES = {
    "product_page_fact": EvidenceType.MARKETPLACE_PRODUCT_FACT,
    "official_product_fact": EvidenceType.OFFICIAL_STORE_FACT,
    "listing_identity": EvidenceType.LISTING_IDENTITY,
    "seller_fulfillment": EvidenceType.SELLER_TRUST,
    "review_summary": EvidenceType.REVIEW_SUMMARY,
    "review_quality_warning": EvidenceType.WARNING,
    "marketplace_warning": EvidenceType.WARNING,
    "regional_availability": EvidenceType.REGION_AVAILABILITY,
    "price": EvidenceType.PRICE,
    "regional_price": EvidenceType.PRICE,
    "store_delivery_context": EvidenceType.REGION_AVAILABILITY,
}


def project_reusable_source_bundle(
    bundle: ReusableSourceBundle,
) -> ReusableSourceProjection:
    references = {item.source_id: item for item in bundle.source_references}
    evidence: list[SourceEvidence] = []
    if isinstance(bundle, VideoReviewEvidenceBundle):
        videos = {item.video_id: item for item in bundle.videos}
        segments = {item.segment_id: item for item in bundle.transcript_segments}
        for record in bundle.evidence:
            evidence.append(
                SourceEvidence(
                    evidence_id=record.evidence_id,
                    source_id=record.source_id,
                    target=record.target,
                    evidence_type=EvidenceType.OTHER
                    if record.metadata_only
                    else EvidenceType.VIDEO_CLAIM,
                    claim=record.claim,
                    confidence=record.confidence,
                    source_quality=record.source_quality,
                    timestamp_references=record.timestamp_references,
                    video=videos[record.video_id],
                    metadata_only=record.metadata_only,
                    transcript_segment_ids=record.transcript_segment_ids,
                    transcript_support=tuple(
                        VideoTranscriptSupport(
                            segment_id=segment.segment_id,
                            video_id=segment.video_id,
                            start_seconds=segment.start_seconds,
                            end_seconds=segment.end_seconds,
                            text=segment.text,
                            content_sha256=sha256(segment.text.encode()).hexdigest(),
                        )
                        for segment_id in record.transcript_segment_ids
                        if (segment := segments[segment_id]).text is not None
                    ),
                    reusable_source_context=VideoEvidenceContext(
                        record=record,
                        source_reference=references[record.source_id],
                    ),
                )
            )
        gaps = tuple(
            SourceEvidenceGap(
                gap_id=uuid5(bundle.bundle_id, f"transcript-gap:{index}:{note}"),
                capability=SourceIntelligenceCapability.VIDEO_REVIEW,
                summary=note,
            )
            for index, note in enumerate(bundle.transcript_gap_notes)
        )
        return ReusableSourceProjection(tuple(evidence), gaps)

    if isinstance(bundle, CommunityDiscussionEvidenceBundle):
        for item in bundle.evidence:
            evidence.append(
                _project_record(
                    item,
                    EvidenceType.COMMUNITY_CLAIM,
                    CommunityEvidenceContext(
                        record=item,
                        source_reference=references[item.source_id],
                        discussions=tuple(
                            row
                            for row in bundle.discussions
                            if row.source_id
                            in {item.source_id, *item.context_source_ids}
                        ),
                    ),
                )
            )
    elif isinstance(bundle, AmazonProductEvidenceBundle):
        for amazon_record in bundle.evidence:
            evidence.append(
                _project_record(
                    amazon_record,
                    _FACT_TYPES[amazon_record.fact_type],
                    AmazonEvidenceContext(
                        record=amazon_record,
                        source_reference=references[amazon_record.source_id],
                        listing_contexts=tuple(
                            row
                            for row in bundle.listing_contexts
                            if row.source_id == amazon_record.listing_context_source_id
                        ),
                        related_targets=tuple(
                            row.target
                            for row in bundle.evidence
                            if amazon_record.listing_context_source_id is not None
                            and row.listing_context_source_id
                            == amazon_record.listing_context_source_id
                        ),
                    ),
                )
            )
    else:
        for ikea_record in bundle.evidence:
            evidence.append(
                _project_record(
                    ikea_record,
                    _FACT_TYPES[ikea_record.fact_type],
                    IKEAEvidenceContext(
                        record=ikea_record,
                        source_reference=references[ikea_record.source_id],
                        store_contexts=tuple(
                            row
                            for row in bundle.store_contexts
                            if row.source_id == ikea_record.store_context_source_id
                        ),
                        related_targets=tuple(
                            row.target
                            for row in bundle.evidence
                            if ikea_record.store_context_source_id is not None
                            and row.store_context_source_id
                            == ikea_record.store_context_source_id
                        ),
                    ),
                )
            )
    return ReusableSourceProjection(tuple(evidence), bundle.evidence_gaps)


def _project_record(
    record: CommunityDiscussionEvidence | AmazonProductEvidence | IKEAStoreEvidence,
    kind: EvidenceType,
    context: ReusableSourceEvidenceContext,
) -> SourceEvidence:
    return SourceEvidence(
        evidence_id=record.evidence_id,
        source_id=record.source_id,
        target=record.target,
        evidence_type=kind,
        claim=record.claim,
        confidence=record.confidence,
        source_quality=record.source_quality,
        reusable_source_context=context,
    )


def project_reusable_source_bundles(
    bundles: Sequence[ReusableSourceBundle],
) -> ReusableSourceProjection:
    projections = tuple(project_reusable_source_bundle(bundle) for bundle in bundles)
    return ReusableSourceProjection(
        evidence=tuple(
            item for projection in projections for item in projection.evidence
        ),
        gaps=tuple(item for projection in projections for item in projection.gaps),
    )


def merge_source_evidence(
    *groups: Sequence[SourceEvidence],
) -> tuple[SourceEvidence, ...]:
    evidence: dict[SourceId, SourceEvidence] = {}
    for group in groups:
        for item in group:
            previous = evidence.get(item.evidence_id)
            if previous is not None and previous != item:
                old = previous.model_dump(exclude={"reusable_source_context"})
                new = item.model_dump(exclude={"reusable_source_context"})
                if old != new or (
                    previous.reusable_source_context is not None
                    and item.reusable_source_context is not None
                ):
                    raise ValueError(
                        "Evidence ID resolves to conflicting source records."
                    )
                if previous.reusable_source_context is not None:
                    continue
            evidence[item.evidence_id] = item
    return tuple(evidence.values())
