from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.search_sources import (
    SearchPlanRecord,
    SearchResultRecord,
    SourceEvidenceRecord,
    SourceSnapshotRecord,
)
from app.schemas.ids import RunId, SourceId, new_id
from app.schemas.search_sources import (
    SearchPlan,
    SearchResult,
    SourceEvidence,
    SourceSnapshot,
)
from app.schemas.timestamps import utc_now


class SearchSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        """Unit-of-work session for run-scoped agent tools."""
        return self._session

    async def create_search_plan(
        self,
        run_id: RunId,
        plan: SearchPlan,
        *,
        plan_id: UUID | None = None,
    ) -> UUID:
        created_plan_id = plan_id or new_id()
        record = SearchPlanRecord.from_schema(
            plan_id=created_plan_id,
            run_id=run_id,
            plan=plan,
            created_at=utc_now(),
        )
        self._session.add(record)
        await self._session.flush()
        return created_plan_id

    async def get_search_plan(self, plan_id: UUID) -> SearchPlan | None:
        record = await self._session.get(SearchPlanRecord, str(plan_id))
        if record is None:
            return None
        return record.to_schema()

    async def add_search_result(
        self,
        run_id: RunId,
        result: SearchResult,
        *,
        plan_id: UUID | None = None,
    ) -> SearchResult:
        record = SearchResultRecord.from_schema(
            run_id=run_id,
            result=result,
            plan_id=plan_id,
        )
        self._session.add(record)
        await self._session.flush()
        return record.to_schema()

    async def list_search_results(self, run_id: RunId) -> tuple[SearchResult, ...]:
        statement: Select[tuple[SearchResultRecord]] = (
            select(SearchResultRecord)
            .where(SearchResultRecord.run_id == str(run_id))
            .order_by(SearchResultRecord.provider_name, SearchResultRecord.url)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def get_search_result_for_run(
        self, run_id: RunId, source_id: SourceId
    ) -> SearchResult | None:
        record = await self._session.get(SearchResultRecord, str(source_id))
        if record is None or record.run_id != str(run_id):
            return None
        return record.to_schema()

    async def add_source_snapshot(
        self,
        run_id: RunId,
        snapshot: SourceSnapshot,
        *,
        search_result_id: SourceId | None = None,
    ) -> SourceSnapshot:
        record = SourceSnapshotRecord.from_schema(
            run_id=run_id,
            snapshot=snapshot,
            search_result_id=search_result_id,
        )
        self._session.add(record)
        await self._session.flush()
        return record.to_schema()

    async def save_source_snapshot(
        self,
        run_id: RunId,
        snapshot: SourceSnapshot,
        *,
        search_result_id: SourceId | None = None,
    ) -> SourceSnapshot:
        """Refresh same-run metadata on a discovery-tool-fetched snapshot."""
        record = await self._session.get(SourceSnapshotRecord, str(snapshot.source_id))
        if record is None:
            return await self.add_source_snapshot(
                run_id, snapshot, search_result_id=search_result_id
            )
        if record.run_id != str(run_id) or (
            search_result_id is not None
            and record.search_result_id != str(search_result_id)
        ):
            raise ValueError("snapshot ID belongs to a different run or search result")
        record.snapshot = snapshot.model_dump(mode="json")
        await self._session.flush()
        return record.to_schema()

    async def get_source_snapshot(
        self,
        source_id: SourceId,
    ) -> SourceSnapshot | None:
        record = await self._session.get(SourceSnapshotRecord, str(source_id))
        if record is None:
            return None
        return record.to_schema()

    async def get_source_snapshot_for_run(
        self, run_id: RunId, source_id: SourceId
    ) -> SourceSnapshot | None:
        record = await self._session.get(SourceSnapshotRecord, str(source_id))
        if record is None or record.run_id != str(run_id):
            return None
        return record.to_schema()

    async def get_snapshot_for_search_result(
        self, run_id: RunId, search_result_id: SourceId
    ) -> SourceSnapshot | None:
        statement: Select[tuple[SourceSnapshotRecord]] = select(
            SourceSnapshotRecord
        ).where(
            SourceSnapshotRecord.run_id == str(run_id),
            SourceSnapshotRecord.search_result_id == str(search_result_id),
        )
        record = await self._session.scalar(statement)
        return None if record is None else record.to_schema()

    async def list_source_snapshots(self, run_id: RunId) -> tuple[SourceSnapshot, ...]:
        statement: Select[tuple[SourceSnapshotRecord]] = (
            select(SourceSnapshotRecord)
            .where(SourceSnapshotRecord.run_id == str(run_id))
            .order_by(SourceSnapshotRecord.captured_at, SourceSnapshotRecord.url)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def add_source_evidence(
        self,
        run_id: RunId,
        evidence: SourceEvidence,
    ) -> SourceEvidence:
        record = SourceEvidenceRecord.from_schema(run_id=run_id, evidence=evidence)
        self._session.add(record)
        await self._session.flush()
        return record.to_schema()

    async def save_source_evidence(
        self, run_id: RunId, evidence: SourceEvidence
    ) -> SourceEvidence:
        """Insert or refresh a same-run evidence target after canonical grouping."""
        record = await self._session.get(
            SourceEvidenceRecord, str(evidence.evidence_id)
        )
        if record is None:
            return await self.add_source_evidence(run_id, evidence)
        if record.run_id != str(run_id) or record.source_id != str(evidence.source_id):
            raise ValueError("evidence ID belongs to a different run or source")
        record.evidence = evidence.model_dump(mode="json")
        record.evidence_type = evidence.evidence_type.value
        await self._session.flush()
        return record.to_schema()

    async def list_source_evidence(self, run_id: RunId) -> tuple[SourceEvidence, ...]:
        statement: Select[tuple[SourceEvidenceRecord]] = (
            select(SourceEvidenceRecord)
            .where(SourceEvidenceRecord.run_id == str(run_id))
            .order_by(SourceEvidenceRecord.source_id, SourceEvidenceRecord.evidence_id)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)
