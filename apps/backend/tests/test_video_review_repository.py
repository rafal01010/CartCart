from pathlib import Path

import pytest

from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.repositories.video_sources import VideoReviewRepository
from app.db.session import create_database_engine, create_session_factory
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import new_id
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.search_sources import (
    ChannelSignal,
    EvidenceTarget,
    EvidenceTargetType,
    ExtractionStatus,
    ProviderMetadata,
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
)


def make_provider() -> ProviderMetadata:
    return ProviderMetadata(
        provider_name="fixture-video-search",
        provider_result_id="video-result-1",
        raw={"rank": 1},
    )


def make_quality(level: SourceQualityLevel = SourceQualityLevel.ADEQUATE) -> SourceQuality:
    return SourceQuality(
        level=level,
        score=0.72,
        rationale="Fixture video source.",
    )


async def create_run(session_factory) -> tuple:
    async with session_factory() as db_session:
        shopping_session = await SessionRepository(db_session).create(
            original_input=CreateSessionRequest(query="Need a travel monitor"),
            current_brief=ShoppingBrief(original_query="Need a travel monitor"),
        )
        run = await RunRepository(db_session).create(shopping_session.session_id)
        await db_session.commit()
    return shopping_session, run


@pytest.mark.asyncio
async def test_video_review_repository_links_timestamped_evidence_to_run_source_product_and_claim(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "videos.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        _shopping_session, run = await create_run(session_factory)
        product_id = new_id()
        video = VideoSource(
            video_id="video-123",
            url="https://www.youtube.com/watch?v=video-123",
            title="Long-term travel monitor review",
            channel_id="channel-123",
            channel_name="Review Channel",
            transcript_availability=TranscriptAvailability.AVAILABLE,
            channel_signals=(ChannelSignal.REVIEW_FOCUSED,),
            sponsorship_disclosed=False,
            affiliate_links_disclosed=True,
            affiliate_bias_risk=Confidence(score=0.25, level=ConfidenceLevel.LOW),
        )
        snapshot = SourceSnapshot(
            url=video.url,
            source_type=SourceType.VIDEO,
            provider=make_provider(),
            title=video.title,
            extraction_status=ExtractionStatus.SUCCEEDED,
            quality=make_quality(),
            video=video,
        )
        segment = VideoTranscriptSegment(
            video_id=video.video_id,
            start_seconds=92.5,
            end_seconds=104.0,
            text="After six months the USB-C port was still reliable.",
        )
        evidence = VideoReviewEvidence(
            source_id=snapshot.source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product_id,
            ),
            video_id=video.video_id,
            claim="The reviewer reports the USB-C port remained reliable.",
            confidence=Confidence(score=0.78, level=ConfidenceLevel.HIGH),
            source_quality=make_quality(),
            timestamp_references=(
                TimestampReference(start_seconds=92.5, end_seconds=104.0),
            ),
            transcript_segment_ids=(segment.segment_id,),
            affiliate_links_disclosed=True,
        )
        bundle = VideoReviewEvidenceBundle(
            videos=(video,),
            source_references=(
                SourceReference(
                    source_id=snapshot.source_id,
                    url=snapshot.url,
                    title=snapshot.title,
                ),
            ),
            transcript_segments=(segment,),
            evidence=(evidence,),
        )

        async with session_factory() as db_session:
            await SearchSourceRepository(db_session).add_source_snapshot(
                run.run_id,
                snapshot,
            )
            stored_bundle = await VideoReviewRepository(
                db_session
            ).add_video_review_bundle(
                run.run_id,
                bundle,
                recommendation_claim_ids={
                    evidence.evidence_id: "final_pick.rationale.1"
                },
            )
            await db_session.commit()

        async with session_factory() as db_session:
            repository = VideoReviewRepository(db_session)
            loaded_bundle = await repository.get_video_review_bundle(
                stored_bundle.bundle_id,
            )
            videos = await repository.list_video_sources(run.run_id)
            segments = await repository.list_transcript_segments(run.run_id)
            evidence_items = await repository.list_video_evidence(run.run_id)
            links = await repository.list_video_evidence_links(run.run_id)

        assert loaded_bundle is not None
        assert loaded_bundle.bundle_id == bundle.bundle_id
        assert videos[0].video_id == video.video_id
        assert videos[0].channel_name == "Review Channel"
        assert segments[0].segment_id == segment.segment_id
        assert segments[0].text is not None
        assert evidence_items[0].evidence_id == evidence.evidence_id
        assert links[0].run_id == run.run_id
        assert links[0].source_id == snapshot.source_id
        assert links[0].product_id == product_id
        assert links[0].recommendation_claim_id == "final_pick.rationale.1"

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_video_review_repository_preserves_metadata_only_evidence_without_transcript(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "videos.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        _shopping_session, run = await create_run(session_factory)
        video = VideoSource(
            video_id="video-456",
            url="https://www.youtube.com/watch?v=video-456",
            title="Sponsored overview",
            channel_name="Brand Channel",
            transcript_availability=TranscriptAvailability.UNAVAILABLE,
            channel_signals=(
                ChannelSignal.SPONSORSHIP_DISCLOSED,
                ChannelSignal.AFFILIATE_LINKS_DISCLOSED,
            ),
            sponsorship_disclosed=True,
            affiliate_links_disclosed=True,
            affiliate_bias_risk=Confidence(score=0.7, level=ConfidenceLevel.HIGH),
            bias_notes="No transcript-backed product claim was extracted.",
        )
        snapshot = SourceSnapshot(
            url=video.url,
            source_type=SourceType.VIDEO,
            provider=make_provider(),
            title=video.title,
            extraction_status=ExtractionStatus.PARTIAL,
            quality=make_quality(SourceQualityLevel.WEAK),
            video=video,
        )
        evidence = VideoReviewEvidence(
            source_id=snapshot.source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.SOURCE_METADATA,
                source_id=snapshot.source_id,
            ),
            video_id=video.video_id,
            claim="The source is a sponsored video with no available transcript.",
            confidence=Confidence(score=0.4, level=ConfidenceLevel.LOW),
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
                    source_id=snapshot.source_id,
                    url=snapshot.url,
                    title=snapshot.title,
                ),
            ),
            evidence=(evidence,),
            transcript_gap_notes=("Transcript unavailable.",),
        )

        async with session_factory() as db_session:
            await SearchSourceRepository(db_session).add_source_snapshot(
                run.run_id,
                snapshot,
            )
            await VideoReviewRepository(db_session).add_video_review_bundle(
                run.run_id,
                bundle,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            repository = VideoReviewRepository(db_session)
            videos = await repository.list_video_sources(run.run_id)
            segments = await repository.list_transcript_segments(run.run_id)
            evidence_items = await repository.list_video_evidence(run.run_id)
            links = await repository.list_video_evidence_links(run.run_id)

        assert videos[0].transcript_availability == TranscriptAvailability.UNAVAILABLE
        assert videos[0].sponsorship_disclosed is True
        assert segments == ()
        assert evidence_items[0].metadata_only is True
        assert links[0].source_target_id == snapshot.source_id
        assert links[0].product_id is None
        assert links[0].recommendation_claim_id is None

    finally:
        await engine.dispose()
