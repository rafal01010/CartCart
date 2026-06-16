from dataclasses import dataclass

import pytest

from app.providers import (
    FakeTranscriptProvider,
    ProviderCapabilityFlags,
    TranscriptAccessStrategy,
    TranscriptProviderOptions,
    TranscriptProviderResult,
)
from app.schemas import (
    CanonicalProduct,
    EvidenceTarget,
    EvidenceTargetType,
    SourceQuality,
    SourceQualityLevel,
    SourceId,
    TranscriptAvailability,
    VideoReviewEvidenceBundle,
    VideoSource,
    new_id,
)
from app.schemas.source_references import SourceReference
from app.services.video_evidence_creation import (
    TranscriptBackedVideoClaim,
    VideoEvidenceCreationError,
    VideoEvidenceCreator,
    YouTubeTranscriptIngestor,
)


@pytest.mark.asyncio
async def test_permitted_transcript_ingestion_preserves_language_and_timestamps() -> (
    None
):
    bundle, source_id = _metadata_bundle()
    ingested = await YouTubeTranscriptIngestor().ingest(
        bundle,
        FakeTranscriptProvider(language="en-US"),
        TranscriptProviderOptions(language="en-US"),
    )

    segment = ingested.transcript_segments[0]
    assert ingested.videos[0].transcript_availability == (
        TranscriptAvailability.AVAILABLE
    )
    assert segment.language == "en-US"
    assert segment.start_seconds == 12.0
    assert segment.end_seconds == 24.0

    product = CanonicalProduct(name="Fixture Monitor", source_ids=(source_id,))
    created = VideoEvidenceCreator().create(
        ingested,
        (
            TranscriptBackedVideoClaim(
                source_id=source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.PRODUCT,
                    product_id=product.product_id,
                ),
                video_id=ingested.videos[0].video_id,
                claim="product-specific review evidence",
                confidence={"score": 0.8, "level": "high"},
                source_quality=SourceQuality(
                    level=SourceQualityLevel.ADEQUATE,
                    score=0.7,
                ),
                transcript_segment_ids=(segment.segment_id,),
            ),
        ),
    )

    evidence = created.evidence[0]
    assert evidence.metadata_only is False
    assert evidence.transcript_segment_ids == (segment.segment_id,)
    assert evidence.timestamp_references[0].start_seconds == 12.0
    assert evidence.timestamp_references[0].end_seconds == 24.0


@pytest.mark.asyncio
async def test_unavailable_transcript_falls_back_to_metadata_only_evidence() -> None:
    bundle, source_id = _metadata_bundle()
    ingested = await YouTubeTranscriptIngestor().ingest(
        bundle,
        FakeTranscriptProvider(availability=TranscriptAvailability.UNAVAILABLE),
    )
    created = VideoEvidenceCreator().create(ingested)

    assert ingested.videos[0].transcript_availability == (
        TranscriptAvailability.UNAVAILABLE
    )
    assert ingested.transcript_segments == ()
    assert ingested.transcript_gap_notes
    assert len(created.evidence) == 1
    assert created.evidence[0].source_id == source_id
    assert created.evidence[0].metadata_only is True
    assert "no transcript-backed product claim" in created.evidence[0].claim


@pytest.mark.asyncio
async def test_provider_failure_is_sanitized_and_keeps_metadata_fallback() -> None:
    bundle, _ = _metadata_bundle()
    ingested = await YouTubeTranscriptIngestor().ingest(
        bundle,
        _FailingTranscriptProvider(),
    )
    created = VideoEvidenceCreator().create(ingested)

    assert ingested.videos[0].transcript_availability == (
        TranscriptAvailability.NOT_CHECKED
    )
    assert ingested.transcript_segments == ()
    assert "secret-provider-token" not in " ".join(ingested.transcript_gap_notes)
    assert "provider failed" in ingested.transcript_gap_notes[0].lower()
    assert created.evidence[0].metadata_only is True


@pytest.mark.asyncio
async def test_unapproved_transcript_strategy_is_not_called() -> None:
    bundle, _ = _metadata_bundle()
    provider = _UnapprovedTranscriptProvider()
    ingested = await YouTubeTranscriptIngestor().ingest(bundle, provider)

    assert provider.called is False
    assert ingested.transcript_segments == ()
    assert "approved transcript access strategy" in ingested.transcript_gap_notes[0]


@pytest.mark.asyncio
async def test_video_evidence_creator_rejects_fabricated_claims() -> None:
    bundle, source_id = _metadata_bundle()
    ingested = await YouTubeTranscriptIngestor().ingest(
        bundle,
        FakeTranscriptProvider(),
    )
    segment = ingested.transcript_segments[0]
    product = CanonicalProduct(name="Fixture Monitor", source_ids=(source_id,))

    with pytest.raises(
        VideoEvidenceCreationError,
        match="must appear in the cited transcript text",
    ):
        VideoEvidenceCreator().create(
            ingested,
            (
                TranscriptBackedVideoClaim(
                    source_id=source_id,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.PRODUCT,
                        product_id=product.product_id,
                    ),
                    video_id=ingested.videos[0].video_id,
                    claim="This monitor has a five-year warranty.",
                    confidence={"score": 0.9, "level": "high"},
                    source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE),
                    transcript_segment_ids=(segment.segment_id,),
                ),
            ),
        )


def _metadata_bundle() -> tuple[VideoReviewEvidenceBundle, SourceId]:
    source_id = new_id()
    video = VideoSource(
        video_id="fixture-video-64a",
        url="https://www.youtube.com/watch?v=fixture-video-64a",
        title="Fixture monitor review",
        channel_name="Fixture Reviews",
    )
    return (
        VideoReviewEvidenceBundle(
            videos=(video,),
            source_references=(
                SourceReference(
                    source_id=source_id,
                    url=video.url,
                    title=video.title,
                ),
            ),
        ),
        source_id,
    )


@dataclass
class _FailingTranscriptProvider:
    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name="failing-transcript",
            supports_transcripts=True,
            permits_transcript_text=True,
            transcript_access_strategy=(
                TranscriptAccessStrategy.AUTHORIZED_OFFICIAL_CAPTIONS
            ),
        )

    async def fetch_transcript(
        self,
        video: VideoSource,
        options: TranscriptProviderOptions | None = None,
    ) -> TranscriptProviderResult:
        raise RuntimeError("secret-provider-token")


@dataclass
class _UnapprovedTranscriptProvider:
    called: bool = False

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name="unapproved-transcript",
            supports_transcripts=True,
            permits_transcript_text=True,
        )

    async def fetch_transcript(
        self,
        video: VideoSource,
        options: TranscriptProviderOptions | None = None,
    ) -> TranscriptProviderResult:
        self.called = True
        raise AssertionError("unapproved provider must not be called")
