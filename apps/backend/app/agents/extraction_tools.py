"""Read-only, run-scoped snapshot access for the semantic extraction agent."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from agents import FunctionTool, function_tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.catalog import ApprovedSDKTool, DEFAULT_AGENT_CATALOG
from app.agents.source_spans import source_span
from app.db.repositories.search_sources import SearchSourceRepository
from app.schemas.base import CartCartBaseModel
from app.schemas.ids import RunId, SourceId
from app.schemas.search_sources import ExtractionStatus


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
        async def read_source_snapshot(snapshot_id: str, start_char: int = 0,
                                       focus: str | None = None) -> str:
            """Read bounded text from a persisted snapshot assigned to this run.

            Args:
                snapshot_id: Snapshot ID supplied in the extraction request.
                start_char: Offset for later exact text. Zero reads the first span.
                focus: Optional exact term to locate supporting text anywhere in this snapshot.
            """
            return (await self.read(snapshot_id, start_char=start_char, focus=focus)).model_dump_json()

        return (read_source_snapshot,)

    async def read(self, snapshot_id: str, *, start_char: int = 0,
                   focus: str | None = None) -> SnapshotReadResult:
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
            return self._result("unknown_snapshot", gap="Snapshot is not in this run.")
        content = snapshot.extracted_content
        text = content.text if content is not None else None
        try:
            span = source_span(text, start=start_char, focus=focus,
                               limit=self._max_text_chars) if text else None
        except ValueError as exc:
            return self._result("invalid_request", gap=str(exc))
        bounded = span.text if span else None
        if bounded:
            self.observed_text.setdefault(parsed_id, []).append(bounded)
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
        )
        self._activity.append(
            {
                "tool_name": "read_source_snapshot",
                "status": result.status,
                "input": {"snapshot_id": str(parsed_id)},
                "output": {"text_truncated": result.text_truncated},
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
