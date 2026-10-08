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
from app.agents.research_history import tracked_tools
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.source_intelligence import SourceIntelligenceRepository
from app.db.repositories.video_sources import VideoReviewRepository
from app.schemas.base import CartCartBaseModel
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
        result = SnapshotReadResult(
            status="succeeded" if bounded else "gap",
            snapshot_id=parsed_id,
            title=snapshot.title,
            url=str(snapshot.url).split("?", 1)[0].split("#", 1)[0],
            provider_source_type=snapshot.source_type.value,
            extraction_status=snapshot.extraction_status,
            text=bounded,
            start_char=span.start if span else 0,
            total_characters=span.total_characters if span else 0,
            content_sha256=span.content_sha256 if span else None,
            text_truncated=text is not None and len(text) > len(bounded or ""),
            gap=None if bounded else "No extracted page text is available.",
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
                discussions = await source_repository.list_community_discussions(
                    self._run_id
                )
                amazon_contexts = await source_repository.list_amazon_listing_contexts(
                    self._run_id
                )
                ikea_contexts = await source_repository.list_ikea_store_contexts(
                    self._run_id
                )
                video_repository = VideoReviewRepository(session)
                videos = await video_repository.list_video_sources(self._run_id)
                segments = await video_repository.list_transcript_segments(self._run_id)
                for item in evidence:
                    descriptor: dict[str, Any] = {
                        "evidence_id": str(item.evidence_id),
                        "snapshot_id": str(item.source_id),
                        "status": "gap",
                    }
                    original = canonical.get(item.evidence_id)
                    if item.source_id not in self._allowed or original != item:
                        descriptor["gap"] = (
                            "Evidence does not match this run's canonical record."
                        )
                        support.append(descriptor)
                        continue
                    snapshot = await repository.get_source_snapshot_for_run(
                        self._run_id, item.source_id
                    )
                    if snapshot is None:
                        descriptor["gap"] = "Original source is missing from this run."
                        support.append(descriptor)
                        continue
                    text = (
                        snapshot.extracted_content.text
                        if snapshot.extracted_content
                        else None
                    )
                    if text and item.claim in text:
                        span = source_span(
                            text,
                            start=text.index(item.claim),
                            limit=self._max_text_chars,
                        )
                        descriptor.update(
                            status="exact_page_support",
                            start_char=span.start,
                            content_sha256=span.content_sha256,
                            total_characters=span.total_characters,
                        )
                    else:
                        typed = next(
                            (
                                record
                                for record in specialized
                                if record.evidence_id == item.evidence_id
                                and record.source_id == item.source_id
                                and record.claim == item.claim
                            ),
                            None,
                        )
                        original_support = (
                            _typed_original_support(
                                typed,
                                snapshot,
                                discussions,
                                amazon_contexts,
                                ikea_contexts,
                                videos,
                                segments,
                            )
                            if typed is not None
                            else None
                        )
                        if original_support is not None:
                            descriptor.update(
                                status="canonical_typed_support",
                                supporting_text=original_support[0],
                                original_records=original_support[1],
                            )
                        else:
                            descriptor["gap"] = (
                                "Exact original support is unavailable for this evidence."
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
    from app.schemas.search_sources import (
        AmazonEvidenceFactType,
        CommunityDiscussionEvidenceBundle,
        IKEAEvidenceFactType,
        VideoReviewEvidenceBundle,
    )
    from app.schemas.source_references import SourceReference
    from app.services.amazon_evidence_creation import (
        AmazonProductEvidenceCreator,
        AmazonProductEvidenceInput,
    )
    from app.services.community_evidence_creation import (
        CommunityEvidenceCreator,
        SourceBackedCommunityClaim,
    )
    from app.services.ikea_evidence_creation import (
        IKEAStoreEvidenceCreator,
        IKEAStoreEvidenceInput,
    )
    from app.services.video_evidence_creation import (
        VideoEvidenceCreator,
        TranscriptBackedVideoClaim,
    )

    reference = SourceReference(
        source_id=snapshot.source_id, url=snapshot.url, title=snapshot.title
    )
    try:
        if isinstance(record, VideoReviewEvidence):
            video = next(
                (
                    v
                    for v in videos
                    if v.video_id == record.video_id and str(v.url) == str(snapshot.url)
                ),
                None,
            )
            if video is None:
                return None
            original_segments = tuple(
                segment
                for segment in segments
                if segment.segment_id in record.transcript_segment_ids
            )
            original = VideoReviewEvidenceBundle(
                videos=(video,),
                source_references=(reference,),
                transcript_segments=original_segments,
            )
            claims = (
                ()
                if record.metadata_only
                else (
                    TranscriptBackedVideoClaim(
                        **record.model_dump(
                            include={
                                "source_id",
                                "target",
                                "video_id",
                                "claim",
                                "signal_kind",
                                "interpretation",
                                "confidence",
                                "source_quality",
                                "transcript_segment_ids",
                                "timestamp_references",
                            }
                        )
                    ),
                )
            )
            reconstructed = VideoEvidenceCreator().create(original, claims)
            if not any(item.claim == record.claim for item in reconstructed.evidence):
                return None
            return record.claim, [
                video.model_dump(mode="json", exclude={"description"}),
                *(
                    _original_text_metadata(s.model_dump(mode="json"), "text")
                    for s in original_segments
                ),
            ]
        if isinstance(record, CommunityDiscussionEvidence):
            cited = tuple(
                d for d in discussions if d.source_id in record.context_source_ids
            )
            refs = tuple(
                SourceReference(source_id=d.source_id, url=d.url, title=d.thread_title)
                for d in cited
            )
            bundle = CommunityDiscussionEvidenceBundle(
                source_references=refs, discussions=cited
            )
            claim = SourceBackedCommunityClaim(
                **record.model_dump(exclude={"evidence_id", "qualitative_signal"})
            )
            CommunityEvidenceCreator().create(bundle, (claim,))
            quotes = tuple(q.quote for q in record.supporting_quotes)
            original_text = " ".join(quotes) if quotes else record.claim
            return original_text, [
                _original_text_metadata(
                    d.model_dump(mode="json"), "extracted_public_summary"
                )
                for d in cited
            ]
        if isinstance(record, AmazonProductEvidence):
            context = next(
                (
                    c
                    for c in amazon_contexts
                    if c.source_id == record.source_id
                    and str(c.listing_url) == str(snapshot.url)
                ),
                None,
            )
            if context is None:
                return None
            provider_fact_types = {
                AmazonEvidenceFactType.PRODUCT_PAGE_FACT,
                AmazonEvidenceFactType.PRICE,
                AmazonEvidenceFactType.REVIEW_SUMMARY,
                AmazonEvidenceFactType.REVIEW_QUALITY_WARNING,
            }
            if record.fact_type in provider_fact_types:
                return record.claim, [
                    context.model_dump(mode="json"),
                    record.model_dump(mode="json"),
                ]
            generated = AmazonProductEvidenceCreator().create(
                (
                    AmazonProductEvidenceInput(
                        product_id=record.target.product_id or record.source_id,
                        listing_id=record.target.listing_id or record.source_id,
                        source_reference=reference,
                        listing_context=context,
                        source_quality=record.source_quality,
                    ),
                )
            )
            if any(
                item.fact_type == record.fact_type and item.claim == record.claim
                for item in generated.evidence
            ):
                return record.claim, [context.model_dump(mode="json")]
        if isinstance(record, IKEAStoreEvidence):
            store_context = next(
                (
                    c
                    for c in ikea_contexts
                    if c.source_id == record.source_id
                    and str(c.official_url) == str(snapshot.url)
                ),
                None,
            )
            if store_context is None:
                return None
            product_claim = None
            if record.fact_type == IKEAEvidenceFactType.OFFICIAL_PRODUCT_FACT:
                product_claim = "Official IKEA regional product result: " + (
                    store_context.product_name or "product"
                )
                if store_context.product_code:
                    product_claim += f". Product number: {store_context.product_code}"
                product_claim += "."
                if record.claim != product_claim:
                    return record.claim, [
                        store_context.model_dump(mode="json"),
                        record.model_dump(mode="json"),
                    ]
            generated_store = IKEAStoreEvidenceCreator().create(
                (
                    IKEAStoreEvidenceInput(
                        product_id=record.target.product_id or record.source_id,
                        source_reference=reference,
                        store_context=store_context,
                        source_quality=record.source_quality,
                        product_page_claim=product_claim,
                    ),
                )
            )
            if any(
                item.fact_type == record.fact_type and item.claim == record.claim
                for item in generated_store.evidence
            ):
                return record.claim, [store_context.model_dump(mode="json")]
    except (ValueError, TypeError):
        return None
    return None


def _original_text_metadata(record: dict[str, Any], field: str) -> dict[str, Any]:
    text = record.pop(field, None)
    if text:
        span = source_span(text)
        record.update(
            total_characters=span.total_characters, content_sha256=span.content_sha256
        )
    return record
