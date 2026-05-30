from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.schemas.search_sources import (
    EvidenceTargetType,
    VideoReviewEvidence,
    VideoReviewEvidenceBundle,
    VideoSource,
    VideoTranscriptSegment,
)


def _dump_json(
    value: (
        VideoSource
        | VideoTranscriptSegment
        | VideoReviewEvidenceBundle
        | VideoReviewEvidence
    ),
) -> dict[str, Any]:
    return value.model_dump(mode="json")


class VideoSourceRecord(Base):
    __tablename__ = "video_sources"
    __table_args__ = (
        Index("ix_video_sources_run_id", "run_id"),
        Index("ix_video_sources_source_id", "source_id"),
        Index("ix_video_sources_video_id", "video_id"),
        Index("ix_video_sources_channel_id", "channel_id"),
    )

    video_record_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("source_snapshots.source_id"),
        nullable=False,
    )
    video_id: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    channel_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    channel_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    transcript_availability: Mapped[str] = mapped_column(String(40), nullable=False)
    channel_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    video: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        video_record_id: UUID,
        run_id: UUID,
        source_id: UUID,
        video: VideoSource,
    ) -> "VideoSourceRecord":
        return cls(
            video_record_id=str(video_record_id),
            run_id=str(run_id),
            source_id=str(source_id),
            video_id=video.video_id,
            url=str(video.url),
            channel_id=video.channel_id,
            channel_name=video.channel_name,
            transcript_availability=video.transcript_availability.value,
            channel_metadata={
                "channel_signals": [signal.value for signal in video.channel_signals],
                "sponsorship_disclosed": video.sponsorship_disclosed,
                "affiliate_links_disclosed": video.affiliate_links_disclosed,
                "affiliate_bias_risk": (
                    video.affiliate_bias_risk.model_dump(mode="json")
                    if video.affiliate_bias_risk
                    else None
                ),
                "bias_notes": video.bias_notes,
            },
            video=_dump_json(video),
        )

    def to_schema(self) -> VideoSource:
        return VideoSource.model_validate(self.video)


class VideoTranscriptSegmentRecord(Base):
    __tablename__ = "video_transcript_segments"
    __table_args__ = (
        Index("ix_video_transcript_segments_run_id", "run_id"),
        Index("ix_video_transcript_segments_video_id", "video_id"),
    )

    segment_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    video_id: Mapped[str] = mapped_column(String(128), nullable=False)
    start_seconds: Mapped[float] = mapped_column(nullable=False)
    end_seconds: Mapped[float | None] = mapped_column(nullable=True)
    availability: Mapped[str] = mapped_column(String(40), nullable=False)
    text: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    gap_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    segment: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        run_id: UUID,
        segment: VideoTranscriptSegment,
    ) -> "VideoTranscriptSegmentRecord":
        return cls(
            segment_id=str(segment.segment_id),
            run_id=str(run_id),
            video_id=segment.video_id,
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            availability=segment.availability.value,
            text=segment.text,
            gap_reason=segment.gap_reason,
            segment=_dump_json(segment),
        )

    def to_schema(self) -> VideoTranscriptSegment:
        return VideoTranscriptSegment.model_validate(self.segment)


class VideoReviewEvidenceBundleRecord(Base):
    __tablename__ = "video_review_evidence_bundles"
    __table_args__ = (Index("ix_video_review_evidence_bundles_run_id", "run_id"),)

    bundle_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    bundle: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        run_id: UUID,
        bundle: VideoReviewEvidenceBundle,
    ) -> "VideoReviewEvidenceBundleRecord":
        return cls(
            bundle_id=str(bundle.bundle_id),
            run_id=str(run_id),
            bundle=_dump_json(bundle),
        )

    def to_schema(self) -> VideoReviewEvidenceBundle:
        return VideoReviewEvidenceBundle.model_validate(self.bundle)


class VideoReviewEvidenceRecord(Base):
    __tablename__ = "video_review_evidence"
    __table_args__ = (
        Index("ix_video_review_evidence_bundle_id", "bundle_id"),
        Index("ix_video_review_evidence_run_id", "run_id"),
        Index("ix_video_review_evidence_source_id", "source_id"),
        Index("ix_video_review_evidence_video_id", "video_id"),
        Index("ix_video_review_evidence_product_id", "product_id"),
        Index("ix_video_review_evidence_listing_id", "listing_id"),
        Index("ix_video_review_evidence_candidate_id", "candidate_id"),
        Index(
            "ix_video_review_evidence_recommendation_claim_id",
            "recommendation_claim_id",
        ),
    )

    evidence_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("video_review_evidence_bundles.bundle_id"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("source_snapshots.source_id"),
        nullable=False,
    )
    video_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str] = mapped_column(String(60), nullable=False)
    product_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    listing_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    candidate_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    seller_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    recommendation_claim_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    metadata_only: Mapped[bool] = mapped_column(nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        run_id: UUID,
        bundle_id: UUID,
        evidence: VideoReviewEvidence,
        recommendation_claim_id: str | None = None,
    ) -> "VideoReviewEvidenceRecord":
        target = evidence.target
        return cls(
            evidence_id=str(evidence.evidence_id),
            bundle_id=str(bundle_id),
            run_id=str(run_id),
            source_id=str(evidence.source_id),
            video_id=evidence.video_id,
            target_type=target.target_type.value,
            product_id=str(target.product_id) if target.product_id else None,
            listing_id=str(target.listing_id) if target.listing_id else None,
            candidate_id=str(target.candidate_id) if target.candidate_id else None,
            seller_name=target.seller_name,
            source_target_id=(
                str(target.source_id)
                if target.target_type == EvidenceTargetType.SOURCE_METADATA
                and target.source_id
                else None
            ),
            recommendation_claim_id=recommendation_claim_id,
            metadata_only=evidence.metadata_only,
            evidence=_dump_json(evidence),
        )

    def to_schema(self) -> VideoReviewEvidence:
        return VideoReviewEvidence.model_validate(self.evidence)
