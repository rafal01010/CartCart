from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.agents.contracts import YouTubeReviewIntelligenceAgentInput
from app.core.settings import Settings
from app.providers import (
    ProviderRunStatus,
    TranscriptProvider,
    VideoSearchProvider,
    VideoSearchProviderOptions,
    build_transcript_provider,
    build_video_search_provider,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import SourceId
from app.schemas.products import CanonicalProduct
from app.schemas.regions import RegionCode
from app.schemas.search_sources import (
    ChannelSignal,
    EvidenceTarget,
    EvidenceTargetType,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
    TranscriptAvailability,
    VideoReviewEvidence,
    VideoReviewEvidenceBundle,
    VideoSource,
    VideoTranscriptSegment,
)
from app.schemas.source_references import SourceReference
from app.services.video_evidence_creation import (
    TranscriptBackedVideoClaim,
    VideoEvidenceCreator,
    YouTubeTranscriptIngestor,
)


YOUTUBE_REVIEW_INTELLIGENCE_AGENT_NAME = "YouTubeReviewIntelligenceAgent"
_MAX_REVIEW_VIDEOS = 3
_MAX_CLAIMS_PER_VIDEO = 6
_CLAIM_MAX_LENGTH = 700
_SPONSORSHIP_PATTERN = re.compile(
    r"\b(sponsored|paid promotion|provided by|thanks to|#ad)\b",
    re.IGNORECASE,
)
_AFFILIATE_PATTERN = re.compile(
    r"\b(affiliate links?|commission|links? below|as an amazon associate)\b",
    re.IGNORECASE,
)
_PRO_MARKERS = frozenset(
    {
        "pro",
        "excellent",
        "great",
        "good",
        "strong",
        "bright",
        "sharp",
        "accurate",
        "stable",
        "comfortable",
        "smooth",
        "reliable",
        "works well",
    }
)
_CON_MARKERS = frozenset(
    {
        "con",
        "drawback",
        "weak",
        "poor",
        "bad",
        "dim",
        "blurry",
        "washed out",
        "expensive",
        "overpriced",
        "slow",
    }
)
_CONCERN_MARKERS = frozenset(
    {
        "concern",
        "issue",
        "problem",
        "risk",
        "wobble",
        "flicker",
        "fail",
        "heat",
        "sponsored",
        "affiliate",
        "warranty",
        "return",
    }
)


@dataclass
class LiveYouTubeReviewIntelligenceAgent:
    settings: Settings | None = None
    video_search_provider: VideoSearchProvider | None = None
    transcript_provider: TranscriptProvider | None = None
    transcript_ingestor: YouTubeTranscriptIngestor = field(
        default_factory=YouTubeTranscriptIngestor,
    )
    evidence_creator: VideoEvidenceCreator = field(default_factory=VideoEvidenceCreator)
    max_review_videos: int = _MAX_REVIEW_VIDEOS
    max_claims_per_video: int = _MAX_CLAIMS_PER_VIDEO
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    async def run(
        self,
        input_data: YouTubeReviewIntelligenceAgentInput,
    ) -> VideoReviewEvidenceBundle:
        transcript_provider = self._transcript_provider()
        activity: list[dict[str, Any]] = []

        bundle = await self._collect_video_metadata(input_data, activity)
        bundle = _select_relevant_videos(
            bundle,
            input_data,
            limit=self.max_review_videos,
        )
        bundle = _annotate_video_bias(bundle)

        ingested = await self.transcript_ingestor.ingest(
            bundle,
            transcript_provider,
        )
        ingested = _annotate_video_bias(ingested)
        activity.append(
            {
                "tool_name": "TranscriptProvider.fetch_transcript",
                "status": "transcripts_ingested",
                "input": {
                    "agent": YOUTUBE_REVIEW_INTELLIGENCE_AGENT_NAME,
                    "allowed_tools": ["TranscriptProvider"],
                    "video_ids": [video.video_id for video in ingested.videos],
                    "provider_name": transcript_provider.capabilities.provider_name,
                },
                "output": {
                    "segment_count": len(ingested.transcript_segments),
                    "gap_count": len(ingested.transcript_gap_notes),
                    "availability_by_video": {
                        video.video_id: video.transcript_availability.value
                        for video in ingested.videos
                    },
                },
            }
        )

        claims = _transcript_claims(
            ingested,
            input_data,
            max_claims_per_video=self.max_claims_per_video,
        )
        output = self.evidence_creator.create(ingested, claims)
        output = _annotate_video_bias(output)
        output = _annotate_evidence_bias_and_gaps(output)
        activity.append(
            {
                "tool_name": "VideoEvidenceCreator.create",
                "status": "video_review_evidence_created",
                "input": {
                    "agent": YOUTUBE_REVIEW_INTELLIGENCE_AGENT_NAME,
                    "allowed_tools": [],
                    "claim_count": len(claims),
                },
                "output": {
                    "evidence_count": len(output.evidence),
                    "metadata_only_count": sum(
                        1 for evidence in output.evidence if evidence.metadata_only
                    ),
                },
            }
        )
        self._workbench_activity = tuple(activity)
        return output

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    def _video_provider(self) -> VideoSearchProvider:
        if self.video_search_provider is not None:
            return self.video_search_provider
        if self.settings is None:
            raise ValueError("settings are required to build the video search provider.")
        return build_video_search_provider(self.settings)

    def _transcript_provider(self) -> TranscriptProvider:
        if self.transcript_provider is not None:
            return self.transcript_provider
        if self.settings is None:
            raise ValueError("settings are required to build the transcript provider.")
        return build_transcript_provider(self.settings)

    async def _collect_video_metadata(
        self,
        input_data: YouTubeReviewIntelligenceAgentInput,
        activity: list[dict[str, Any]],
    ) -> VideoReviewEvidenceBundle:
        snapshot_bundle = _bundle_from_video_snapshots(input_data.source_snapshots)
        if snapshot_bundle is not None:
            activity.append(
                {
                    "tool_name": "supplied_video_metadata",
                    "status": "source_snapshots_selected",
                    "input": {
                        "agent": YOUTUBE_REVIEW_INTELLIGENCE_AGENT_NAME,
                        "allowed_tools": [],
                        "snapshot_count": len(input_data.source_snapshots),
                    },
                    "output": {
                        "video_count": len(snapshot_bundle.videos),
                    },
                }
            )
            return snapshot_bundle

        provider = self._video_provider()
        bundles: list[VideoReviewEvidenceBundle] = []
        notes: list[str] = []
        queries = input_data.video_queries or (_fallback_video_query(input_data),)
        for query in queries:
            result = await provider.search_videos(
                query,
                VideoSearchProviderOptions(
                    region_code=_region_code(input_data),
                    max_results=self.max_review_videos,
                ),
            )
            notes.extend(result.notes)
            activity.append(
                {
                    "tool_name": "VideoSearchProvider.search_videos",
                    "status": result.status.value,
                    "input": {
                        "agent": YOUTUBE_REVIEW_INTELLIGENCE_AGENT_NAME,
                        "allowed_tools": ["VideoSearchProvider"],
                        "query": query,
                        "provider_name": provider.capabilities.provider_name,
                    },
                    "output": {
                        "video_count": len(result.bundle.videos)
                        if result.bundle is not None
                        else 0,
                        "notes": result.notes,
                    },
                }
            )
            if (
                result.status == ProviderRunStatus.SUCCEEDED
                and result.bundle is not None
            ):
                bundles.append(result.bundle)

        merged = _merge_video_bundles(tuple(bundles), tuple(notes))
        if merged is None:
            raise ValueError("YouTube review intelligence requires video metadata.")
        return merged


def _bundle_from_video_snapshots(
    snapshots: tuple[SourceSnapshot, ...],
) -> VideoReviewEvidenceBundle | None:
    videos: list[VideoSource] = []
    references: list[SourceReference] = []
    seen_video_ids: set[str] = set()
    seen_source_ids: set[SourceId] = set()

    for snapshot in snapshots:
        if snapshot.source_type != SourceType.VIDEO or snapshot.video is None:
            continue
        if snapshot.video.video_id in seen_video_ids:
            continue
        seen_video_ids.add(snapshot.video.video_id)
        videos.append(snapshot.video)
        if snapshot.source_id not in seen_source_ids:
            seen_source_ids.add(snapshot.source_id)
            references.append(
                SourceReference(
                    source_id=snapshot.source_id,
                    url=snapshot.video.url,
                    title=snapshot.title or snapshot.video.title,
                )
            )

    if not videos or not references:
        return None
    return VideoReviewEvidenceBundle(
        videos=tuple(videos),
        source_references=tuple(references),
    )


def _merge_video_bundles(
    bundles: tuple[VideoReviewEvidenceBundle, ...],
    notes: tuple[str, ...],
) -> VideoReviewEvidenceBundle | None:
    if not bundles:
        return None

    videos: list[VideoSource] = []
    references: list[SourceReference] = []
    segments: list[VideoTranscriptSegment] = []
    evidence: list[VideoReviewEvidence] = []
    seen_video_ids: set[str] = set()
    seen_source_ids: set[SourceId] = set()
    seen_segment_ids: set[SourceId] = set()
    seen_evidence_ids: set[SourceId] = set()

    for bundle in bundles:
        selected_video_ids: set[str] = set()
        for video in bundle.videos:
            if video.video_id in seen_video_ids:
                continue
            seen_video_ids.add(video.video_id)
            selected_video_ids.add(video.video_id)
            videos.append(video)

        selected_urls = {str(video.url) for video in videos}
        for reference in bundle.source_references:
            if reference.source_id in seen_source_ids:
                continue
            if str(reference.url) not in selected_urls:
                continue
            seen_source_ids.add(reference.source_id)
            references.append(reference)

        for segment in bundle.transcript_segments:
            if (
                segment.segment_id in seen_segment_ids
                or segment.video_id not in selected_video_ids
            ):
                continue
            seen_segment_ids.add(segment.segment_id)
            segments.append(segment)

        for item in bundle.evidence:
            if (
                item.evidence_id in seen_evidence_ids
                or item.video_id not in selected_video_ids
            ):
                continue
            seen_evidence_ids.add(item.evidence_id)
            evidence.append(item)

    if not videos or not references:
        return None
    return VideoReviewEvidenceBundle(
        videos=tuple(videos),
        source_references=tuple(references),
        transcript_segments=tuple(segments),
        evidence=tuple(evidence),
        transcript_gap_notes=tuple(dict.fromkeys((*notes,))),
    )


def _select_relevant_videos(
    bundle: VideoReviewEvidenceBundle,
    input_data: YouTubeReviewIntelligenceAgentInput,
    *,
    limit: int,
) -> VideoReviewEvidenceBundle:
    if len(bundle.videos) <= limit:
        return bundle

    scored = [
        (_video_relevance_score(video, input_data), index, video)
        for index, video in enumerate(bundle.videos)
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected_videos = tuple(video for _, _, video in scored[:limit])
    selected_video_ids = {video.video_id for video in selected_videos}
    selected_urls = {str(video.url) for video in selected_videos}
    selected_references = tuple(
        reference
        for reference in bundle.source_references
        if str(reference.url) in selected_urls
    )
    selected_source_ids = {reference.source_id for reference in selected_references}
    selected_segment_ids = {
        segment.segment_id
        for segment in bundle.transcript_segments
        if segment.video_id in selected_video_ids
    }
    selected_evidence = tuple(
        item
        for item in bundle.evidence
        if item.video_id in selected_video_ids
        and item.source_id in selected_source_ids
        and all(
            segment_id in selected_segment_ids
            for segment_id in item.transcript_segment_ids
        )
    )
    return bundle.model_copy(
        update={
            "videos": selected_videos,
            "source_references": selected_references,
            "transcript_segments": tuple(
                segment
                for segment in bundle.transcript_segments
                if segment.segment_id in selected_segment_ids
            ),
            "evidence": selected_evidence,
        }
    )


def _video_relevance_score(
    video: VideoSource,
    input_data: YouTubeReviewIntelligenceAgentInput,
) -> int:
    tokens = _query_tokens(input_data)
    if not tokens:
        return 0
    haystack = _video_metadata_text(video)
    return sum(1 for token in tokens if token in haystack)


def _query_tokens(input_data: YouTubeReviewIntelligenceAgentInput) -> set[str]:
    values = [
        input_data.brief.original_query,
        input_data.brief.category,
        *(product.name for product in input_data.products),
        *(product.brand or "" for product in input_data.products),
        *(product.model or "" for product in input_data.products),
        *input_data.video_queries,
    ]
    return {
        token
        for value in values
        if value
        for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", value.casefold())
    }


def _annotate_video_bias(
    bundle: VideoReviewEvidenceBundle,
) -> VideoReviewEvidenceBundle:
    text_by_video_id: dict[str, list[str]] = {}
    for video in bundle.videos:
        text_by_video_id[video.video_id] = [_video_metadata_text(video)]
    for segment in bundle.transcript_segments:
        if segment.text:
            text_by_video_id.setdefault(segment.video_id, []).append(segment.text)

    videos = tuple(
        _video_with_bias(video, " ".join(text_by_video_id.get(video.video_id, ())))
        for video in bundle.videos
    )
    return bundle.model_copy(update={"videos": videos})


def _video_with_bias(video: VideoSource, text: str) -> VideoSource:
    sponsorship_disclosed = bool(_SPONSORSHIP_PATTERN.search(text))
    affiliate_links_disclosed = bool(_AFFILIATE_PATTERN.search(text))
    signals = list(video.channel_signals)
    if ChannelSignal.REVIEW_FOCUSED not in signals:
        signals.append(ChannelSignal.REVIEW_FOCUSED)
    if sponsorship_disclosed and ChannelSignal.SPONSORSHIP_DISCLOSED not in signals:
        signals.append(ChannelSignal.SPONSORSHIP_DISCLOSED)
    if (
        affiliate_links_disclosed
        and ChannelSignal.AFFILIATE_LINKS_DISCLOSED not in signals
    ):
        signals.append(ChannelSignal.AFFILIATE_LINKS_DISCLOSED)

    if sponsorship_disclosed and affiliate_links_disclosed:
        risk = _confidence(0.72, "Visible sponsorship and affiliate disclosures.")
        notes = "Visible sponsorship and affiliate-link disclosures; treat review claims with bias caution."
    elif sponsorship_disclosed or affiliate_links_disclosed:
        risk = _confidence(0.58, "Visible sponsorship or affiliate disclosure.")
        notes = "Visible sponsorship or affiliate disclosure; treat review claims with bias caution."
    else:
        risk = _confidence(0.2, "No visible sponsorship or affiliate disclosure found.")
        notes = None

    return video.model_copy(
        update={
            "channel_signals": tuple(dict.fromkeys(signals)),
            "sponsorship_disclosed": sponsorship_disclosed,
            "affiliate_links_disclosed": affiliate_links_disclosed,
            "affiliate_bias_risk": risk,
            "bias_notes": notes,
        }
    )


def _transcript_claims(
    bundle: VideoReviewEvidenceBundle,
    input_data: YouTubeReviewIntelligenceAgentInput,
    *,
    max_claims_per_video: int,
) -> tuple[TranscriptBackedVideoClaim, ...]:
    source_ids_by_video = _source_ids_by_video(bundle)
    videos_by_id = {video.video_id: video for video in bundle.videos}
    segments_by_video: dict[str, list[VideoTranscriptSegment]] = {}
    for segment in bundle.transcript_segments:
        if segment.text is None:
            continue
        segments_by_video.setdefault(segment.video_id, []).append(segment)

    claims: list[TranscriptBackedVideoClaim] = []
    target = _product_target(input_data.products)
    for video in bundle.videos:
        selected_segments = _selected_review_segments(
            tuple(segments_by_video.get(video.video_id, ())),
            limit=max_claims_per_video,
        )
        for segment in selected_segments:
            assert segment.text is not None
            claim = _claim_text(segment.text)
            claims.append(
                TranscriptBackedVideoClaim(
                    source_id=source_ids_by_video[video.video_id],
                    target=target
                    or EvidenceTarget(
                        target_type=EvidenceTargetType.SOURCE_METADATA,
                        source_id=source_ids_by_video[video.video_id],
                    ),
                    video_id=video.video_id,
                    claim=claim,
                    confidence=_claim_confidence(segment.text),
                    source_quality=_source_quality_for_video(videos_by_id[video.video_id]),
                    transcript_segment_ids=(segment.segment_id,),
                )
            )
    return tuple(claims)


def _selected_review_segments(
    segments: tuple[VideoTranscriptSegment, ...],
    *,
    limit: int,
) -> tuple[VideoTranscriptSegment, ...]:
    scored: list[tuple[int, int, VideoTranscriptSegment]] = []
    for index, segment in enumerate(segments):
        text = (segment.text or "").casefold()
        score = _segment_review_score(text)
        if score > 0:
            scored.append((score, index, segment))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(segment for _, _, segment in scored[:limit])


def _segment_review_score(text: str) -> int:
    score = 0
    if any(marker in text for marker in _PRO_MARKERS):
        score += 3
    if any(marker in text for marker in _CON_MARKERS):
        score += 3
    if any(marker in text for marker in _CONCERN_MARKERS):
        score += 4
    return score


def _claim_text(text: str) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= _CLAIM_MAX_LENGTH:
        return normalized
    return normalized[:_CLAIM_MAX_LENGTH].rsplit(" ", 1)[0].rstrip(".;,")


def _claim_confidence(text: str) -> Confidence:
    score = 0.74 if _segment_review_score(text.casefold()) >= 4 else 0.66
    return _confidence(score, "Transcript-backed video review claim.")


def _source_quality_for_video(video: VideoSource) -> SourceQuality:
    if (
        video.affiliate_bias_risk is not None
        and video.affiliate_bias_risk.score >= 0.7
    ):
        return SourceQuality(
            level=SourceQualityLevel.MIXED,
            score=0.58,
            rationale="Useful transcript evidence with visible sponsorship or affiliate bias risk.",
        )
    return SourceQuality(
        level=SourceQualityLevel.ADEQUATE,
        score=0.68,
        rationale="Review video transcript evidence selected through the provider boundary.",
    )


def _annotate_evidence_bias_and_gaps(
    bundle: VideoReviewEvidenceBundle,
) -> VideoReviewEvidenceBundle:
    videos_by_id = {video.video_id: video for video in bundle.videos}
    gap_by_video_id = _gap_note_by_video_id(bundle)
    evidence = tuple(
        item.model_copy(
            update={
                "sponsorship_disclosed": videos_by_id[
                    item.video_id
                ].sponsorship_disclosed,
                "affiliate_links_disclosed": videos_by_id[
                    item.video_id
                ].affiliate_links_disclosed,
                "affiliate_bias_risk": videos_by_id[item.video_id].affiliate_bias_risk,
                **(
                    {
                        "transcript_gap": gap_by_video_id.get(item.video_id)
                        or "No transcript-backed product claim was available for this video."
                    }
                    if item.metadata_only
                    else {}
                ),
            }
        )
        for item in bundle.evidence
    )
    return bundle.model_copy(update={"evidence": evidence})


def _gap_note_by_video_id(bundle: VideoReviewEvidenceBundle) -> dict[str, str]:
    by_video_id: dict[str, str] = {}
    combined_gap = " ".join(bundle.transcript_gap_notes).strip()
    for video in bundle.videos:
        if video.transcript_availability in {
            TranscriptAvailability.AVAILABLE,
            TranscriptAvailability.PARTIAL,
        }:
            continue
        by_video_id[video.video_id] = combined_gap or (
            "Transcript unavailable or not checked; no transcript-backed product claim was created."
        )
    return by_video_id


def _source_ids_by_video(bundle: VideoReviewEvidenceBundle) -> dict[str, SourceId]:
    source_ids_by_url = {
        str(reference.url): reference.source_id
        for reference in bundle.source_references
    }
    return {
        video.video_id: source_ids_by_url[str(video.url)]
        for video in bundle.videos
    }


def _product_target(
    products: tuple[CanonicalProduct, ...],
) -> EvidenceTarget | None:
    if not products:
        return None
    return EvidenceTarget(
        target_type=EvidenceTargetType.PRODUCT,
        product_id=products[0].product_id,
    )


def _fallback_video_query(input_data: YouTubeReviewIntelligenceAgentInput) -> str:
    terms = [product.name for product in input_data.products[:2]]
    if input_data.brief.category:
        terms.append(input_data.brief.category)
    terms.append(input_data.brief.original_query)
    return f"{' '.join(dict.fromkeys(term for term in terms if term))} review video"[
        :500
    ].strip()


def _region_code(
    input_data: YouTubeReviewIntelligenceAgentInput,
) -> RegionCode | None:
    if input_data.brief.region is None:
        return None
    return input_data.brief.region.region.code


def _video_metadata_text(video: VideoSource) -> str:
    return " ".join(
        value
        for value in (
            video.title,
            video.description,
            video.channel_name,
            video.channel_id,
        )
        if value
    ).casefold()


def _confidence(score: float, rationale: str) -> Confidence:
    level = (
        ConfidenceLevel.HIGH
        if score >= 0.75
        else ConfidenceLevel.MEDIUM
        if score >= 0.45
        else ConfidenceLevel.LOW
    )
    return Confidence(score=score, level=level, rationale=rationale)
