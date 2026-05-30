from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.runs import RunEventRecord, ShoppingRunRecordModel
from app.schemas.errors import ErrorEnvelope
from app.schemas.ids import RunId, SessionId, new_id
from app.schemas.runs import RunEvent, RunStage, RunStatus, ShoppingRunRecord
from app.schemas.timestamps import utc_now


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        session_id: SessionId,
        *,
        run_id: RunId | None = None,
    ) -> ShoppingRunRecord:
        run = ShoppingRunRecord(
            run_id=run_id or new_id(),
            session_id=session_id,
            status=RunStatus.PENDING,
            created_at=utc_now(),
        )
        record = ShoppingRunRecordModel.from_schema(run)
        self._session.add(record)
        await self._session.flush()
        return record.to_schema()

    async def get(self, run_id: RunId) -> ShoppingRunRecord | None:
        record = await self._session.get(ShoppingRunRecordModel, str(run_id))
        if record is None:
            return None
        return record.to_schema()

    async def append_event(
        self,
        run_id: RunId,
        *,
        stage: RunStage,
        status: RunStatus,
        message: str,
        error: ErrorEnvelope | None = None,
    ) -> RunEvent | None:
        run_record = await self._session.get(ShoppingRunRecordModel, str(run_id))
        if run_record is None:
            return None

        event = RunEvent(
            run_id=run_id,
            sequence=await self._next_sequence(run_id),
            stage=stage,
            status=status,
            message=message,
            occurred_at=utc_now(),
            error=error,
        )
        event_record = RunEventRecord.from_schema(event)
        self._session.add(event_record)
        run_record.apply_event(event)
        await self._session.flush()
        return event_record.to_schema()

    async def list_events(self, run_id: RunId) -> tuple[RunEvent, ...]:
        statement: Select[tuple[RunEventRecord]] = (
            select(RunEventRecord)
            .where(RunEventRecord.run_id == str(run_id))
            .order_by(RunEventRecord.sequence)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def _next_sequence(self, run_id: RunId) -> int:
        statement = select(func.max(RunEventRecord.sequence)).where(
            RunEventRecord.run_id == str(run_id)
        )
        latest_sequence = await self._session.scalar(statement)
        if latest_sequence is None:
            return 0
        return latest_sequence + 1
