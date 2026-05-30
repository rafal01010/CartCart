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

    async def get_source_snapshot(
        self,
        source_id: SourceId,
    ) -> SourceSnapshot | None:
        record = await self._session.get(SourceSnapshotRecord, str(source_id))
        if record is None:
            return None
        return record.to_schema()

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

    async def list_source_evidence(self, run_id: RunId) -> tuple[SourceEvidence, ...]:
        statement: Select[tuple[SourceEvidenceRecord]] = (
            select(SourceEvidenceRecord)
            .where(SourceEvidenceRecord.run_id == str(run_id))
            .order_by(SourceEvidenceRecord.source_id, SourceEvidenceRecord.evidence_id)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)
