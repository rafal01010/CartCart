from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.runs import RecomputePlanRecord, RefinementRequestRecord
from app.schemas.ids import CandidateId, RunId, SessionId
from app.schemas.runs import RecomputePlan, RecomputeStage, RefinementRequest


class RefinementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, refinement: RefinementRequest) -> RefinementRequest:
        record = RefinementRequestRecord.from_schema(refinement)
        self._session.add(record)
        await self._session.flush()
        return record.to_schema()

    async def save_plan(self, plan: RecomputePlan) -> RecomputePlan:
        record = RecomputePlanRecord.from_schema(plan)
        self._session.add(record)
        await self._session.flush()
        return record.to_schema()

    async def get_plan(self, refinement_id: CandidateId) -> RecomputePlan | None:
        statement = select(RecomputePlanRecord).where(
            RecomputePlanRecord.refinement_id == str(refinement_id)
        )
        record = await self._session.scalar(statement)
        return record.to_schema() if record is not None else None

    async def get_plan_for_run(self, run_id: RunId) -> RecomputePlan | None:
        statement = select(RecomputePlanRecord).where(
            RecomputePlanRecord.run_id == str(run_id)
        )
        record = await self._session.scalar(statement)
        return record.to_schema() if record is not None else None

    async def research_run_for(self, run_id: RunId) -> RunId:
        """Follow persisted reuse links to the run that owns candidate evidence."""
        seen: set[RunId] = set()
        current = run_id
        while current not in seen:
            seen.add(current)
            plan = await self.get_plan_for_run(current)
            if plan is None or RecomputeStage.SEARCH in plan.stages:
                return current
            current = plan.prior_run_id
        raise ValueError("Refinement plans contain a cycle.")

    async def get_for_run(
        self,
        run_id: RunId,
    ) -> RefinementRequest | None:
        statement: Select[tuple[RefinementRequestRecord]] = (
            select(RefinementRequestRecord)
            .where(RefinementRequestRecord.run_id == str(run_id))
            .limit(1)
        )
        record = await self._session.scalar(statement)
        if record is None:
            return None
        return record.to_schema()

    async def list_for_session(
        self,
        session_id: SessionId,
    ) -> tuple[RefinementRequest, ...]:
        statement: Select[tuple[RefinementRequestRecord]] = (
            select(RefinementRequestRecord)
            .where(RefinementRequestRecord.session_id == str(session_id))
            .order_by(RefinementRequestRecord.created_at)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)
