from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.video_sources import (
    VideoReviewEvidenceBundleRecord,
    VideoReviewEvidenceRecord,
    VideoSourceRecord,
    VideoTranscriptSegmentRecord,
)
from app.schemas.ids import (
    CandidateId,
    ListingId,
    ProductId,
    RunId,
    SourceId,
    new_id,
)
from app.schemas.search_sources import (
    VideoReviewEvidence,
    VideoReviewEvidenceBundle,
    VideoSource,
    VideoTranscriptSegment,
)


@dataclass(frozen=True)
class VideoEvidenceLink:
    evidence_id: SourceId
    run_id: RunId
    source_id: SourceId
    video_id: str
    product_id: ProductId | None
    listing_id: ListingId | None
    candidate_id: CandidateId | None
    source_target_id: SourceId | None
    recommendation_claim_id: str | None


class VideoReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_video_source(
        self,
        run_id: RunId,
        source_id: SourceId,
        video: VideoSource,
        *,
        video_record_id: UUID | None = None,
    ) -> VideoSource:
        record = VideoSourceRecord.from_schema(
            video_record_id=video_record_id or new_id(),
            run_id=run_id,
            source_id=source_id,
            video=video,
        )
        self._session.add(record)
        await self._session.flush()
        return record.to_schema()

    async def add_transcript_segment(
        self,
        run_id: RunId,
        segment: VideoTranscriptSegment,
    ) -> VideoTranscriptSegment:
        record = VideoTranscriptSegmentRecord.from_schema(
            run_id=run_id,
            segment=segment,
        )
        self._session.add(record)
        await self._session.flush()
        return record.to_schema()

    async def add_video_review_bundle(
        self,
        run_id: RunId,
        bundle: VideoReviewEvidenceBundle,
        *,
        recommendation_claim_ids: Mapping[SourceId, str] | None = None,
    ) -> VideoReviewEvidenceBundle:
        source_id_by_url = {
            str(reference.url): reference.source_id
            for reference in bundle.source_references
        }
        fallback_source_id = bundle.source_references[0].source_id

        for video in bundle.videos:
            await self.add_video_source(
                run_id,
                source_id_by_url.get(str(video.url), fallback_source_id),
                video,
            )

        for segment in bundle.transcript_segments:
            await self.add_transcript_segment(run_id, segment)

        bundle_record = VideoReviewEvidenceBundleRecord.from_schema(
            run_id=run_id,
            bundle=bundle,
        )
        self._session.add(bundle_record)
        await self._session.flush()

        for evidence in bundle.evidence:
            evidence_record = VideoReviewEvidenceRecord.from_schema(
                run_id=run_id,
                bundle_id=bundle.bundle_id,
                evidence=evidence,
                recommendation_claim_id=(
                    recommendation_claim_ids or {}
                ).get(evidence.evidence_id),
            )
            self._session.add(evidence_record)

        await self._session.flush()
        return bundle_record.to_schema()

    async def get_video_review_bundle(
        self,
        bundle_id: SourceId,
    ) -> VideoReviewEvidenceBundle | None:
        record = await self._session.get(
            VideoReviewEvidenceBundleRecord,
            str(bundle_id),
        )
        if record is None:
            return None
        return record.to_schema()

    async def list_video_sources(self, run_id: RunId) -> tuple[VideoSource, ...]:
        statement: Select[tuple[VideoSourceRecord]] = (
            select(VideoSourceRecord)
            .where(VideoSourceRecord.run_id == str(run_id))
            .order_by(VideoSourceRecord.video_id, VideoSourceRecord.url)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def list_transcript_segments(
        self,
        run_id: RunId,
    ) -> tuple[VideoTranscriptSegment, ...]:
        statement: Select[tuple[VideoTranscriptSegmentRecord]] = (
            select(VideoTranscriptSegmentRecord)
            .where(VideoTranscriptSegmentRecord.run_id == str(run_id))
            .order_by(
                VideoTranscriptSegmentRecord.video_id,
                VideoTranscriptSegmentRecord.start_seconds,
            )
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def list_video_evidence(
        self,
        run_id: RunId,
    ) -> tuple[VideoReviewEvidence, ...]:
        statement: Select[tuple[VideoReviewEvidenceRecord]] = (
            select(VideoReviewEvidenceRecord)
            .where(VideoReviewEvidenceRecord.run_id == str(run_id))
            .order_by(
                VideoReviewEvidenceRecord.video_id,
                VideoReviewEvidenceRecord.evidence_id,
            )
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def list_video_evidence_links(
        self,
        run_id: RunId,
    ) -> tuple[VideoEvidenceLink, ...]:
        statement: Select[tuple[VideoReviewEvidenceRecord]] = (
            select(VideoReviewEvidenceRecord)
            .where(VideoReviewEvidenceRecord.run_id == str(run_id))
            .order_by(VideoReviewEvidenceRecord.evidence_id)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(_to_link(record) for record in records)


def _to_link(record: VideoReviewEvidenceRecord) -> VideoEvidenceLink:
    return VideoEvidenceLink(
        evidence_id=UUID(record.evidence_id),
        run_id=UUID(record.run_id),
        source_id=UUID(record.source_id),
        video_id=record.video_id,
        product_id=UUID(record.product_id) if record.product_id else None,
        listing_id=UUID(record.listing_id) if record.listing_id else None,
        candidate_id=UUID(record.candidate_id) if record.candidate_id else None,
        source_target_id=(
            UUID(record.source_target_id) if record.source_target_id else None
        ),
        recommendation_claim_id=record.recommendation_claim_id,
    )
