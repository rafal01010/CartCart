from __future__ import annotations

from app.providers.contracts import (
    ProviderCapabilityFlags,
    ProviderRunStatus,
    TranscriptAccessStrategy,
    TranscriptProvider,
    TranscriptProviderOptions,
    TranscriptProviderResult,
)
from app.schemas.base import CartCartBaseModel
from app.schemas.confidence import Confidence
from app.schemas.ids import SourceId
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    SourceQuality,
    SourceQualityLevel,
    TimestampReference,
    TranscriptAvailability,
    VideoReviewEvidence,
    VideoReviewEvidenceBundle,
    VideoSource,
    VideoTranscriptSegment,
)


class VideoEvidenceCreationError(ValueError):
    """Raised when video evidence is not grounded in bundled source data."""


class TranscriptBackedVideoClaim(CartCartBaseModel):
    source_id: SourceId
    target: EvidenceTarget
    video_id: str
    claim: str
    confidence: Confidence
    source_quality: SourceQuality
    transcript_segment_ids: tuple[SourceId, ...]
    timestamp_references: tuple[TimestampReference, ...] = ()


class YouTubeTranscriptIngestor:
    """Ingest transcripts through an explicitly permitted provider boundary."""

    async def ingest(
        self,
        bundle: VideoReviewEvidenceBundle,
        provider: TranscriptProvider,
        options: TranscriptProviderOptions | None = None,
    ) -> VideoReviewEvidenceBundle:
        capabilities = provider.capabilities
        if not capabilities.enabled:
            return _with_gap_for_all(
                bundle,
                "Transcript provider is disabled; transcript availability was not checked.",
            )
        if not _permits_transcript_ingestion(capabilities):
            return _with_gap_for_all(
                bundle,
                "Transcript provider does not declare an approved transcript access strategy.",
            )

        existing_video_ids = {
            segment.video_id for segment in bundle.transcript_segments
        }
        videos: list[VideoSource] = []
        segments = list(bundle.transcript_segments)
        gap_notes = list(bundle.transcript_gap_notes)

        for video in bundle.videos:
            if video.video_id in existing_video_ids:
                videos.append(video)
                continue
            try:
                result = await provider.fetch_transcript(video, options)
                _validate_provider_result(video, result)
            except Exception:
                videos.append(
                    video.model_copy(
                        update={
                            "transcript_availability": TranscriptAvailability.NOT_CHECKED
                        }
                    )
                )
                gap_notes.append(
                    f"Transcript provider failed for video {video.video_id}; "
                    "no transcript-backed claims were created."
                )
                continue

            videos.append(
                video.model_copy(
                    update={"transcript_availability": result.availability}
                )
            )
            if result.status == ProviderRunStatus.SUCCEEDED:
                segments.extend(result.segments)
            gap_notes.extend(result.gap_notes)

        return bundle.model_copy(
            update={
                "videos": tuple(videos),
                "transcript_segments": tuple(segments),
                "transcript_gap_notes": tuple(dict.fromkeys(gap_notes)),
            }
        )


class VideoEvidenceCreator:
    """Create transcript-backed claims and conservative metadata fallbacks."""

    def create(
        self,
        bundle: VideoReviewEvidenceBundle,
        claims: tuple[TranscriptBackedVideoClaim, ...] = (),
    ) -> VideoReviewEvidenceBundle:
        videos = {video.video_id: video for video in bundle.videos}
        source_ids_by_video = _source_ids_by_video(bundle)
        segments = {
            segment.segment_id: segment for segment in bundle.transcript_segments
        }
        evidence = list(bundle.evidence)

        for claim in claims:
            video = videos.get(claim.video_id)
            if video is None:
                raise VideoEvidenceCreationError(
                    "video claims must reference a bundled video."
                )
            if claim.source_id != source_ids_by_video.get(claim.video_id):
                raise VideoEvidenceCreationError(
                    "video claims must reference the source for the bundled video."
                )
            cited_segments = _cited_segments(claim, segments)
            if not _claim_is_transcript_backed(claim.claim, cited_segments):
                raise VideoEvidenceCreationError(
                    "video claims must appear in the cited transcript text."
                )
            timestamps = claim.timestamp_references or tuple(
                TimestampReference(
                    start_seconds=segment.start_seconds,
                    end_seconds=segment.end_seconds,
                )
                for segment in cited_segments
            )
            if not _timestamps_match_segments(timestamps, cited_segments):
                raise VideoEvidenceCreationError(
                    "video claim timestamps must fall within cited transcript segments."
                )
            evidence.append(
                VideoReviewEvidence(
                    source_id=claim.source_id,
                    target=claim.target,
                    video_id=claim.video_id,
                    claim=claim.claim,
                    confidence=claim.confidence,
                    source_quality=claim.source_quality,
                    timestamp_references=timestamps,
                    transcript_segment_ids=claim.transcript_segment_ids,
                )
            )

        videos_with_evidence = {item.video_id for item in evidence}
        for video in bundle.videos:
            if video.video_id in videos_with_evidence:
                continue
            source_id = source_ids_by_video[video.video_id]
            evidence.append(
                VideoReviewEvidence(
                    source_id=source_id,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.SOURCE_METADATA,
                        source_id=source_id,
                    ),
                    video_id=video.video_id,
                    claim=(
                        "Video metadata is available; no transcript-backed product "
                        "claim was created."
                    ),
                    confidence={"score": 0.4, "level": "low"},
                    source_quality=SourceQuality(level=SourceQualityLevel.UNKNOWN),
                    metadata_only=True,
                )
            )

        return bundle.model_copy(update={"evidence": tuple(evidence)})


def _permits_transcript_ingestion(
    capabilities: ProviderCapabilityFlags,
) -> bool:
    return bool(
        capabilities.supports_transcripts
        and capabilities.permits_transcript_text
        and capabilities.transcript_access_strategy
        in {
            TranscriptAccessStrategy.AUTHORIZED_OFFICIAL_CAPTIONS,
            TranscriptAccessStrategy.USER_PROVIDED,
            TranscriptAccessStrategy.APPROVED_THIRD_PARTY,
        }
    )


def _validate_provider_result(
    requested_video: VideoSource,
    result: TranscriptProviderResult,
) -> None:
    if result.video.video_id != requested_video.video_id or str(
        result.video.url
    ) != str(requested_video.url):
        raise VideoEvidenceCreationError(
            "transcript provider returned a different video."
        )
    if result.segments and not _permits_transcript_ingestion(result.capabilities):
        raise VideoEvidenceCreationError(
            "transcript provider returned text without an approved access strategy."
        )


def _with_gap_for_all(
    bundle: VideoReviewEvidenceBundle,
    note: str,
) -> VideoReviewEvidenceBundle:
    videos = tuple(
        video.model_copy(
            update={"transcript_availability": TranscriptAvailability.NOT_CHECKED}
        )
        for video in bundle.videos
    )
    return bundle.model_copy(
        update={
            "videos": videos,
            "transcript_gap_notes": tuple(
                dict.fromkeys((*bundle.transcript_gap_notes, note))
            ),
        }
    )


def _source_ids_by_video(
    bundle: VideoReviewEvidenceBundle,
) -> dict[str, SourceId]:
    source_ids_by_url = {
        str(reference.url): reference.source_id
        for reference in bundle.source_references
    }
    source_ids_by_video: dict[str, SourceId] = {}
    for video in bundle.videos:
        source_id = source_ids_by_url.get(str(video.url))
        if source_id is None:
            raise VideoEvidenceCreationError(
                "each bundled video requires an exact source reference URL."
            )
        source_ids_by_video[video.video_id] = source_id
    return source_ids_by_video


def _cited_segments(
    claim: TranscriptBackedVideoClaim,
    segments: dict[SourceId, VideoTranscriptSegment],
) -> tuple[VideoTranscriptSegment, ...]:
    if not claim.transcript_segment_ids:
        raise VideoEvidenceCreationError(
            "transcript-backed video claims require transcript segment IDs."
        )
    cited: list[VideoTranscriptSegment] = []
    for segment_id in claim.transcript_segment_ids:
        segment = segments.get(segment_id)
        if segment is None or segment.video_id != claim.video_id:
            raise VideoEvidenceCreationError(
                "video claims must cite bundled segments from the same video."
            )
        if segment.text is None:
            raise VideoEvidenceCreationError(
                "video claims cannot cite transcript gaps as supporting text."
            )
        cited.append(segment)
    return tuple(cited)


def _claim_is_transcript_backed(
    claim: str,
    segments: tuple[VideoTranscriptSegment, ...],
) -> bool:
    normalized_claim = " ".join(claim.casefold().split())
    normalized_text = " ".join(
        " ".join((segment.text or "").casefold().split()) for segment in segments
    )
    return normalized_claim in normalized_text


def _timestamps_match_segments(
    timestamps: tuple[TimestampReference, ...],
    segments: tuple[VideoTranscriptSegment, ...],
) -> bool:
    for timestamp in timestamps:
        if not any(
            timestamp.start_seconds >= segment.start_seconds
            and (
                segment.end_seconds is None
                or timestamp.end_seconds is None
                or (timestamp.end_seconds <= segment.end_seconds)
            )
            for segment in segments
        ):
            return False
    return True
