from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import TypeAdapter

from app.db.models.sessions import ShoppingSessionRecord
from app.schemas.ids import SessionId, new_id
from app.schemas.intake import CreateSessionRequest, ShoppingBrief, ShoppingSession
from app.schemas.timestamps import utc_now
from app.schemas.guided_intake import GuidedAnswer


_guided_answers_adapter = TypeAdapter(dict[str, GuidedAnswer])


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        original_input: CreateSessionRequest,
        current_brief: ShoppingBrief,
        *,
        session_id: SessionId | None = None,
    ) -> ShoppingSession:
        now = utc_now()
        shopping_session = ShoppingSession(
            session_id=session_id or new_id(),
            original_input=original_input,
            current_brief=current_brief,
            created_at=now,
            updated_at=now,
        )
        record = ShoppingSessionRecord.from_schema(shopping_session)
        self._session.add(record)
        await self._session.flush()
        return record.to_schema()

    async def get(self, session_id: SessionId) -> ShoppingSession | None:
        record = await self._session.get(ShoppingSessionRecord, str(session_id))
        if record is None:
            return None
        return record.to_schema()

    async def update_current_brief(
        self,
        session_id: SessionId,
        current_brief: ShoppingBrief,
    ) -> ShoppingSession | None:
        record = await self._session.get(ShoppingSessionRecord, str(session_id))
        if record is None:
            return None

        record.update_current_brief(current_brief, utc_now())
        await self._session.flush()
        return record.to_schema()

    async def get_guided_region_status(self, session_id: SessionId) -> str | None:
        record = await self._session.get(ShoppingSessionRecord, str(session_id))
        return record.guided_region_status if record is not None else None

    async def get_guided_answers(self, session_id: SessionId) -> dict[str, GuidedAnswer] | None:
        record = await self._session.get(ShoppingSessionRecord, str(session_id))
        if record is None or record.guided_answers is None:
            return None
        return _guided_answers_adapter.validate_python(record.guided_answers)

    async def update_guided_answers(
        self, session_id: SessionId, answers: dict[str, GuidedAnswer]
    ) -> None:
        record = await self._session.get(ShoppingSessionRecord, str(session_id))
        if record is not None:
            record.guided_answers = _guided_answers_adapter.dump_python(answers, mode="json")
            await self._session.flush()

    async def update_guided_region_status(
        self, session_id: SessionId, status: str | None
    ) -> None:
        record = await self._session.get(ShoppingSessionRecord, str(session_id))
        if record is not None:
            record.guided_region_status = status
            await self._session.flush()
