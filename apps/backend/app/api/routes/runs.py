from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.errors import ApplicationError
from app.db.repositories.runs import RunRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import get_db_session
from app.schemas.ids import RunId, SessionId
from app.schemas.runs import RunEvent, ShoppingRunRecord
from app.services.runs import RunService


router = APIRouter(prefix="/api/sessions/{session_id}/runs", tags=["runs"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.post("", response_model=ShoppingRunRecord, status_code=status.HTTP_201_CREATED)
async def create_run(
    session_id: SessionId,
    db_session: DbSession,
) -> ShoppingRunRecord:
    run = await _run_service(db_session).create_stub_run(session_id)
    if run is None:
        raise _session_not_found(session_id)

    await db_session.commit()
    return run


@router.get("/{run_id}/events")
async def stream_run_events(
    session_id: SessionId,
    run_id: RunId,
    db_session: DbSession,
) -> StreamingResponse:
    events = await _run_service(db_session).list_run_events(session_id, run_id)
    if events is None:
        raise _run_not_found(session_id, run_id)

    return StreamingResponse(
        _sse_event_stream(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/{run_id}", response_model=ShoppingRunRecord)
async def get_run(
    session_id: SessionId,
    run_id: RunId,
    db_session: DbSession,
) -> ShoppingRunRecord:
    run = await _run_service(db_session).get_run_status(session_id, run_id)
    if run is None:
        raise _run_not_found(session_id, run_id)
    return run


async def _sse_event_stream(events: tuple[RunEvent, ...]) -> AsyncIterator[str]:
    for event in events:
        yield (
            f"id: {event.sequence}\n"
            "event: run_event\n"
            f"data: {event.model_dump_json()}\n\n"
        )


def _run_service(db_session: AsyncSession) -> RunService:
    return RunService(
        session_repository=SessionRepository(db_session),
        run_repository=RunRepository(db_session),
    )


def _run_not_found(
    session_id: SessionId,
    run_id: RunId | None = None,
) -> ApplicationError:
    details = {"session_id": str(session_id)}
    if run_id is not None:
        details["run_id"] = str(run_id)

    return ApplicationError(
        "run_not_found",
        "Run not found.",
        status_code=status.HTTP_404_NOT_FOUND,
        details=details,
    )


def _session_not_found(session_id: SessionId) -> ApplicationError:
    return ApplicationError(
        "session_not_found",
        "Session not found.",
        status_code=status.HTTP_404_NOT_FOUND,
        details={"session_id": str(session_id)},
    )
