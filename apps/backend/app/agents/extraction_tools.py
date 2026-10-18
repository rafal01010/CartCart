"""Read-only, run-scoped snapshot access for the semantic extraction agent."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from agents import FunctionTool, function_tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.catalog import ApprovedSDKTool, DEFAULT_AGENT_CATALOG
from app.agents.source_spans import source_span
from app.agents.research_history import bounded_cautions, tracked_tools
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.source_intelligence import SourceIntelligenceRepository
from app.db.repositories.video_sources import VideoReviewRepository
from app.schemas.base import CartCartBaseModel
from app.providers.outbound_urls import neutral_outbound_url
from app.schemas.ids import RunId, SourceId
from app.schemas.search_sources import (
    AmazonListingContext,
    AmazonProductEvidence,
    CommunityDiscussionContext,
    CommunityDiscussionEvidence,
    ExtractionStatus,
    IKEAStoreContext,
    IKEAStoreEvidence,
    SourceEvidence,
    SourceSnapshot,
    SourceType,
    TimestampReference,
    VideoReviewEvidence,
    VideoSource,
    VideoTranscriptSegment,
)


class SnapshotReadResult(CartCartBaseModel):
    status: str
    snapshot_id: SourceId | None = None
    title: str | None = None
    url: str | None = None
    provider_source_type: str | None = None
    extraction_status: ExtractionStatus | None = None
    text: str | None = None
    text_truncated: bool = False
    start_char: int = 0
    total_characters: int = 0
    content_sha256: str | None = None
    gap: str | None = None
    source_part_ids: tuple[SourceId, ...] = ()
    timestamp_references: tuple[TimestampReference, ...] = ()


class SnapshotInterpretationTools:
    def __init__(
        self,
        *,
        run_id: RunId,
        allowed_snapshot_ids: tuple[SourceId, ...],
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        shared_session: AsyncSession | None = None,
        max_reads: int = 24,
        max_text_chars: int = 4000,
        agent_name: str = "ExtractionAgent",
    ) -> None:
        if (
            ApprovedSDKTool.READ_SOURCE_SNAPSHOT
            not in DEFAULT_AGENT_CATALOG.require(agent_name).approved_sdk_tools
        ):
            raise ValueError(f"{agent_name} is not approved to read source snapshots")
        if session_factory is None and shared_session is None:
            raise ValueError("snapshot tools require database access")
        self._run_id = run_id
        self._allowed = frozenset(allowed_snapshot_ids)
        self._session_factory = session_factory
        self._shared_session = shared_session
        self._remaining = max_reads
        self._max_text_chars = max_text_chars
        self._lock = asyncio.Lock()
        self._activity: list[dict[str, Any]] = []
        self.observed_text: dict[SourceId, list[str]] = {}
        self.observed_pages: dict[SourceId, SnapshotReadResult] = {}

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._activity)

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        if self._shared_session is not None:
            yield self._shared_session
        else:
            assert self._session_factory is not None
            async with self._session_factory() as session:
                yield session

    def sdk_tools(self) -> tuple[FunctionTool, ...]:
        @function_tool
        async def read_source_snapshot(
            snapshot_id: str, start_char: int = 0, focus: str | None = None
        ) -> str:
            """Read bounded text from a persisted snapshot assigned to this run.

            Args:
                snapshot_id: Snapshot ID supplied in the extraction request.
                start_char: Offset for later exact text. Zero reads the first span.
                focus: Optional exact term to locate supporting text anywhere in this snapshot.
            """
            return (
                await self.read(snapshot_id, start_char=start_char, focus=focus)
            ).model_dump_json()

        return tracked_tools((read_source_snapshot,))

    async def read(
        self, snapshot_id: str, *, start_char: int = 0, focus: str | None = None
    ) -> SnapshotReadResult:
        try:
            parsed_id = SourceId(snapshot_id)
        except (TypeError, ValueError):
            return self._result("invalid_request", gap="Invalid snapshot ID.")
        if parsed_id not in self._allowed:
            return self._result(
                "unknown_snapshot", gap="Snapshot is not assigned to this extraction."
            )
        async with self._lock:
            if self._remaining <= 0:
                return self._result(
                    "budget_exhausted", gap="Snapshot read limit reached."
                )
            self._remaining -= 1
            async with self._session() as session:
                snapshot = await SearchSourceRepository(
                    session
                ).get_source_snapshot_for_run(self._run_id, parsed_id)
                if snapshot is None:
                    return self._result(
                        "unknown_snapshot", gap="Snapshot is not in this run."
                    )
                content = snapshot.extracted_content
                text = content.text if content is not None else None
                parts: list[tuple[SourceId, str, TimestampReference | None]] = []
                if not text and snapshot.video is not None:
                    videos = await VideoReviewRepository(session).list_video_sources(
                        self._run_id
                    )
                    if any(
                        v.video_id == snapshot.video.video_id
                        and str(v.url) == str(snapshot.url)
                        for v in videos
                    ):
                        segments = await VideoReviewRepository(
                            session
                        ).list_transcript_segments(self._run_id)
                        parts = [
                            (
                                segment.segment_id,
                                segment.text,
                                TimestampReference(
                                    start_seconds=segment.start_seconds,
                                    end_seconds=segment.end_seconds,
                                ),
                            )
                            for segment in segments
                            if segment.video_id == snapshot.video.video_id
                            and segment.text
                        ]
                elif (
                    not text and snapshot.source_type == SourceType.COMMUNITY_DISCUSSION
                ):
                    discussions = await SourceIntelligenceRepository(
                        session
                    ).list_community_discussions(self._run_id)
                    parts = [
                        (
                            discussion.source_id,
                            discussion.extracted_public_summary,
                            None,
                        )
                        for discussion in discussions
                        if discussion.source_id == snapshot.source_id
                        and str(discussion.url) == str(snapshot.url)
                        and discussion.extracted_public_summary
                    ]
                elif not text:
                    source_repository = SourceIntelligenceRepository(session)
                    typed_evidence: tuple[
                        AmazonProductEvidence | IKEAStoreEvidence, ...
                    ] = (
                        *await source_repository.list_amazon_evidence(self._run_id),
                        *await source_repository.list_ikea_evidence(self._run_id),
                    )
                    amazon_contexts = (
                        await source_repository.list_amazon_listing_contexts(
                            self._run_id
                        )
                    )
                    ikea_contexts = await source_repository.list_ikea_store_contexts(
                        self._run_id
                    )
                    for record in typed_evidence:
                        if record.source_id != parsed_id:
                            continue
                        support = _typed_original_support(
                            record, snapshot, (), amazon_contexts, ikea_contexts, (), ()
                        )
                        if support is not None:
                            parts.append(
                                (
                                    record.evidence_id,
                                    json.dumps(
                                        {
                                            "status": "canonical_typed_support",
                                            "evidence_id": str(record.evidence_id),
                                            "supporting_text": support[0],
                                            "original_records": support[1],
                                        },
                                        ensure_ascii=False,
                                    ),
                                    None,
                                )
                            )
                if parts:
                    text = "\n".join(part[1] for part in parts)
        try:
            span = (
                source_span(
                    text, start=start_char, focus=focus, limit=self._max_text_chars
                )
                if text
                else None
            )
        except ValueError as exc:
            return self._result("invalid_request", gap=str(exc))
        bounded = span.text if span else None
        if bounded and span is not None:
            previous = self.observed_pages.get(parsed_id)
            if previous is not None and previous.content_sha256 != span.content_sha256:
                self.observed_text.pop(parsed_id, None)
            self.observed_text.setdefault(parsed_id, []).append(bounded)
        observed_parts: list[SourceId] = []
        timestamps: list[TimestampReference] = []
        offset = 0
        for part_id, part_text, timestamp in parts:
            if (
                span is not None
                and offset < span.start + len(span.text)
                and offset + len(part_text) > span.start
            ):
                observed_parts.append(part_id)
                if timestamp is not None:
                    timestamps.append(timestamp)
            offset += len(part_text) + 1
        neutral_url = neutral_outbound_url(str(snapshot.url))
        result = SnapshotReadResult(
            status="succeeded" if bounded else "gap",
            snapshot_id=parsed_id,
            title=snapshot.title,
            url=neutral_url,
            provider_source_type=snapshot.source_type.value,
            extraction_status=snapshot.extraction_status,
            text=bounded,
            start_char=span.start if span else 0,
            total_characters=span.total_characters if span else 0,
            content_sha256=span.content_sha256 if span else None,
            text_truncated=text is not None and len(text) > len(bounded or ""),
            gap=(
                "Source destination contains unsupported or unsafe URL data."
                if neutral_url is None
                else None
                if bounded
                else "No extracted page text is available."
            ),
            source_part_ids=tuple(observed_parts),
            timestamp_references=tuple(timestamps),
        )
        if bounded:
            self.observed_pages[parsed_id] = result
        self._activity.append(
            {
                "tool_name": "read_source_snapshot",
                "status": result.status,
                "input": {"snapshot_id": str(parsed_id)},
                "output": {
                    "text_truncated": result.text_truncated,
                    "start_char": result.start_char,
                    "characters": len(result.text or ""),
                    "content_sha256": result.content_sha256,
                },
            }
        )
        return result

    def _result(self, status: str, *, gap: str) -> SnapshotReadResult:
        result = SnapshotReadResult(status=status, gap=gap)
        self._activity.append(
            {
                "tool_name": "read_source_snapshot",
                "status": status,
                "input": {},
                "output": {},
            }
        )
        return result

    async def canonical_support(
        self, evidence: tuple[SourceEvidence, ...]
    ) -> tuple[dict[str, Any], ...]:
        support: list[dict[str, Any]] = []
        async with self._lock:
            async with self._session() as session:
                repository = SearchSourceRepository(session)
                canonical = {
                    item.evidence_id: item
                    for item in await repository.list_source_evidence(self._run_id)
                }
                source_repository = SourceIntelligenceRepository(session)
                specialized: tuple[
                    CommunityDiscussionEvidence
                    | AmazonProductEvidence
                    | IKEAStoreEvidence
                    | VideoReviewEvidence,
                    ...,
                ] = (
                    *await source_repository.list_community_evidence(self._run_id),
                    *await source_repository.list_amazon_evidence(self._run_id),
                    *await source_repository.list_ikea_evidence(self._run_id),
                    *await VideoReviewRepository(session).list_video_evidence(
                        self._run_id
                    ),
                )
                for item in evidence:
                    original = canonical.get(item.evidence_id)
                    descriptor: dict[str, Any] = {
                        "evidence_id": str(item.evidence_id),
                        "snapshot_id": str(item.source_id),
                        "status": "gap",
                    }
                    if original is None or original.source_id not in self._allowed:
                        descriptor["gap"] = (
                            "Saved source association is unavailable in this run."
                        )
                        support.append(descriptor)
                        continue
                    snapshot = await repository.get_source_snapshot_for_run(
                        self._run_id, original.source_id
                    )
                    text = (
                        snapshot.extracted_content.text
                        if snapshot and snapshot.extracted_content
                        else ""
                    )
                    descriptor.update(
                        status="saved_source_context",
                        source_note=original.claim,
                        source_title=snapshot.title if snapshot else None,
                        source_url=str(snapshot.url) if snapshot else None,
                        source_spans=[
                            {
                                "snapshot_id": str(original.source_id),
                                "text": text[: self._max_text_chars],
                                "text_truncated": len(text) > self._max_text_chars,
                            }
                        ]
                        if text
                        else [],
                        original_records=[
                            record.model_dump(mode="json")
                            for record in specialized
                            if record.evidence_id == original.evidence_id
                        ],
                        **bounded_cautions(text, max_count=3, max_characters=200),
                    )
                    support.append(descriptor)
        return tuple(support)


def _typed_original_support(
    record: CommunityDiscussionEvidence
    | AmazonProductEvidence
    | IKEAStoreEvidence
    | VideoReviewEvidence,
    snapshot: SourceSnapshot,
    discussions: tuple[CommunityDiscussionContext, ...],
    amazon_contexts: tuple[AmazonListingContext, ...],
    ikea_contexts: tuple[IKEAStoreContext, ...],
    videos: tuple[VideoSource, ...],
    segments: tuple[VideoTranscriptSegment, ...],
) -> tuple[str, list[dict[str, Any]]] | None:
    records: list[dict[str, Any]] = []
    if isinstance(record, VideoReviewEvidence):
        records.extend(
            video.model_dump(mode="json")
            for video in videos
            if video.video_id == record.video_id
        )
        records.extend(
            segment.model_dump(mode="json")
            for segment in segments
            if segment.segment_id in record.transcript_segment_ids
        )
    elif isinstance(record, CommunityDiscussionEvidence):
        records.extend(
            context.model_dump(mode="json")
            for context in discussions
            if context.source_id in record.context_source_ids
        )
    elif isinstance(record, AmazonProductEvidence):
        records.extend(
            context.model_dump(mode="json")
            for context in amazon_contexts
            if context.source_id == record.source_id
        )
    elif isinstance(record, IKEAStoreEvidence):
        records.extend(
            context.model_dump(mode="json")
            for context in ikea_contexts
            if context.source_id == record.source_id
        )
    return (record.claim, records) if records else None
