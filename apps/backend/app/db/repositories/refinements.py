from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.runs import RefinementRequestRecord
from app.schemas.ids import RunId, SessionId
from app.schemas.runs import RefinementRequest


class RefinementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, refinement: RefinementRequest) -> RefinementRequest:
        record = RefinementRequestRecord.from_schema(refinement)
        self._session.add(record)
        await self._session.flush()
        return record.to_schema()

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
