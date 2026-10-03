"""Bounded, source-specific tools for the model-running YouTube specialist."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from agents import FunctionTool, function_tool

from app.agents.contracts import YouTubeReviewIntelligenceAgentInput
from app.agents.source_spans import source_span
from app.agents.youtube_review_intelligence_service import (
    _bundle_from_video_snapshots,
    _merge_video_bundles,
)
from app.providers import (
    ProviderRunStatus,
    TranscriptProvider,
    VideoSearchProvider,
    VideoSearchProviderOptions,
)
from app.schemas.search_sources import VideoReviewEvidenceBundle
from app.services.video_evidence_creation import YouTubeTranscriptIngestor


@dataclass
class YouTubeReviewTools:
    input_data: YouTubeReviewIntelligenceAgentInput
    video_provider: VideoSearchProvider
    transcript_provider: TranscriptProvider
    max_searches: int = 2
    max_transcripts: int = 3
    max_videos: int = 8
    max_segments_per_read: int = 6
    _bundles: list[VideoReviewEvidenceBundle] = field(default_factory=list, init=False)
    _searched: int = field(default=0, init=False)
    _transcripts_read: set[str] = field(default_factory=set, init=False)
    _transcripts: dict[str, VideoReviewEvidenceBundle] = field(
        default_factory=dict, init=False
    )
    _metadata_read: set[str] = field(default_factory=set, init=False)
    _span_reads: int = field(default=0, init=False)
    observed_text: dict[str, list[str]] = field(default_factory=dict, init=False)
    _activity: list[dict[str, Any]] = field(default_factory=list, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        seeded = _bundle_from_video_snapshots(self.input_data.source_snapshots)
        if seeded is not None:
            self._bundles.append(seeded)

    @property
    def bundle(self) -> VideoReviewEvidenceBundle | None:
        merged = _merge_video_bundles(tuple(self._bundles), ())
        if merged is None:
            return None
        replacements = {
            v.video_id: v for b in self._transcripts.values() for v in b.videos
        }
        segments = tuple(
            s
            for b in self._transcripts.values()
            for s in b.transcript_segments
        )
        notes = tuple(
            n for b in self._transcripts.values() for n in b.transcript_gap_notes
        )
        return VideoReviewEvidenceBundle.model_validate(
            merged.model_copy(
                update={
                    "videos": tuple(
                        replacements.get(v.video_id, v) for v in merged.videos
                    ),
                    "transcript_segments": segments,
                    "transcript_gap_notes": tuple(
                        dict.fromkeys((*merged.transcript_gap_notes, *notes))
                    ),
                }
            ).model_dump()
        )

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._activity)

    def sdk_tools(self) -> tuple[FunctionTool, ...]:
        @function_tool
        async def search_videos(query: str) -> str:
            """Search public YouTube review-video metadata for shopper-relevant products."""
            return json.dumps(await self.search(query))

        @function_tool
        async def read_video_metadata(video_id: str) -> str:
            """Read approved video metadata by a video ID returned by search or input."""
            return json.dumps(await self.metadata(video_id))

        @function_tool
        async def read_video_transcript(video_id: str, start_segment: int = 0,
                                        focus: str | None = None) -> str:
            """Read a bounded exact caption page, retaining timestamps and segment IDs.

            Args:
                video_id: Approved video ID.
                start_segment: Segment offset for later material, default zero.
                focus: Optional exact term to locate relevant caption text.
            """
            return json.dumps(await self.transcript(video_id, start_segment=start_segment, focus=focus))

        return (search_videos, read_video_metadata, read_video_transcript)

    async def search(self, query: str) -> dict[str, Any]:
        query = query.strip()
        if not query or len(query) > 300:
            return {
                "status": "invalid_query",
                "gap": "Use a 1–300 character review-video query.",
            }
        async with self._lock:
            if self._searched >= self.max_searches:
                return {
                    "status": "budget_exhausted",
                    "gap": "Video search limit reached.",
                }
            self._searched += 1
        try:
            result = await self.video_provider.search_videos(
                query,
                VideoSearchProviderOptions(
                    region_code=(
                        self.input_data.brief.region.region.country_code
                        if self.input_data.brief.region
                        else None
                    ),
                    max_results=min(self.max_videos, 10),
                ),
            )
            async with self._lock:
                if result.status == ProviderRunStatus.SUCCEEDED and result.bundle:
                    self._bundles.append(result.bundle)
                bundle = self.bundle
            response = {
                "status": result.status.value,
                "videos": self._video_summaries(bundle),
                "notes": list(result.notes),
            }
        except Exception:
            response = {
                "status": "provider_error",
                "videos": [],
                "gap": "Video search failed.",
            }
        self._activity.append(
            {
                "tool_name": "search_videos",
                "status": response["status"],
                "input": {"query": query},
                "output": {"video_count": len(response.get("videos", []))},
            }
        )
        return response

    async def metadata(self, video_id: str) -> dict[str, Any]:
        bundle = self.bundle
        video = (
            next((v for v in bundle.videos if v.video_id == video_id), None)
            if bundle
            else None
        )
        if video is None:
            return {
                "status": "unknown_video",
                "gap": "Video ID was not supplied or found by approved search.",
            }
        assert bundle is not None
        source = next(
            (r for r in bundle.source_references if str(r.url) == str(video.url)), None
        )
        if source is None:
            return {
                "status": "invalid_source",
                "gap": "Video has no matching source reference.",
            }
        response = {
            "status": "ok",
            "source_id": str(source.source_id),
            "video": video.model_dump(mode="json"),
        }
        self._metadata_read.add(video_id)
        self._activity.append(
            {
                "tool_name": "read_video_metadata",
                "status": "ok",
                "input": {"video_id": video_id},
                "output": {"source_id": str(source.source_id)},
            }
        )
        return response

    async def transcript(self, video_id: str, *, start_segment: int = 0,
                         focus: str | None = None) -> dict[str, Any]:
        async with self._lock:
            if start_segment < 0 or (focus is not None and (not focus.strip() or len(focus) > 200)):
                return {"status": "invalid_request", "gap": "Invalid transcript span."}
            if self._span_reads >= 12:
                return {"status": "budget_exhausted", "gap": "Transcript span read limit reached."}
            self._span_reads += 1
            bundle = self.bundle
            video = (
                next((v for v in bundle.videos if v.video_id == video_id), None)
                if bundle
                else None
            )
            if video is None:
                return {
                    "status": "unknown_video",
                    "gap": "Video ID was not supplied or found by approved search.",
                }
            if (
                video_id not in self._transcripts_read
                and len(self._transcripts_read) >= self.max_transcripts
            ):
                return {
                    "status": "budget_exhausted",
                    "gap": "Transcript read limit reached.",
                }
            assert bundle is not None
            if video_id not in self._transcripts_read:
                self._transcripts_read.add(video_id)
                source = next(
                    r for r in bundle.source_references if str(r.url) == str(video.url)
                )
                one_video = VideoReviewEvidenceBundle(
                    videos=(video,), source_references=(source,)
                )
                ingested = await YouTubeTranscriptIngestor().ingest(
                    one_video, self.transcript_provider
                )
                self._transcripts[video_id] = ingested
            else:
                ingested = self._transcripts[video_id]
            available = [s for s in ingested.transcript_segments if s.video_id == video_id]
            if focus is not None:
                start_segment = next((i for i, s in enumerate(available)
                                      if focus.casefold() in (s.text or "").casefold()), -1)
                if start_segment < 0:
                    return {"status": "gap", "gap": "Focus term was not found in permitted captions."}
            selected = available[start_segment:start_segment + self.max_segments_per_read]
            segments = []
            for i, segment in enumerate(selected):
                span = source_span(segment.text or "", limit=1000,
                                   focus=focus if i == 0 else None)
                projected = segment.model_dump(mode="json")
                projected.update(text=span.text, start_char=span.start, content_sha256=span.content_sha256)
                segments.append(projected)
                self.observed_text.setdefault(str(segment.segment_id), []).append(span.text)
            response = {
                "status": "ok" if segments else "unavailable",
                "video_id": video_id,
                "availability": ingested.videos[0].transcript_availability.value,
                "segments": segments,
                "start_segment": start_segment,
                "total_segments": len(available),
                "text_truncated": start_segment + len(segments) < len(available),
                "gap_notes": list(ingested.transcript_gap_notes),
            }
        self._activity.append(
            {
                "tool_name": "read_video_transcript",
                "status": response["status"],
                "input": {"video_id": video_id},
                "output": {"segment_count": len(segments)},
            }
        )
        return response

    def _video_summaries(
        self, bundle: VideoReviewEvidenceBundle | None
    ) -> list[dict[str, Any]]:
        if bundle is None:
            return []
        sources = {str(r.url): str(r.source_id) for r in bundle.source_references}
        return [
            {
                "video_id": v.video_id,
                "source_id": sources.get(str(v.url)),
                "title": v.title,
                "channel": v.channel_name,
                "description": (v.description or "")[:500],
            }
            for v in bundle.videos[: self.max_videos]
        ]
