from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.db.session import get_db_session
from app.schemas.guided_intake import (
    CreateGuidedSessionRequest,
    GuidedAnswerSubmission,
    GuidedIntakeState,
    GuidedReanswerRequest,
    GuidedSessionResponse,
    RegionSetupSubmission,
)
from app.schemas.ids import SessionId
from app.services.guided_intake import GuidedIntakeService


router = APIRouter(prefix="/api/sessions", tags=["guided intake"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.post(
    "/guided",
    response_model=GuidedSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_guided_session(
    request: CreateGuidedSessionRequest,
    db_session: DbSession,
) -> GuidedSessionResponse:
    response = await GuidedIntakeService(db_session).create_guided_session(request)
    await db_session.commit()
    return response


@router.get("/{session_id}/guide", response_model=GuidedIntakeState)
async def get_guide_state(
    session_id: SessionId,
    db_session: DbSession,
) -> GuidedIntakeState:
    state = await GuidedIntakeService(db_session).load_state(session_id)
    if state is None:
        raise _session_not_found(session_id)
    return state


@router.post("/{session_id}/answers", response_model=GuidedIntakeState)
async def submit_guided_answer(
    session_id: SessionId,
    request: GuidedAnswerSubmission,
    db_session: DbSession,
) -> GuidedIntakeState:
    state = await GuidedIntakeService(db_session).submit_answer(session_id, request)
    if state is None:
        raise _session_not_found(session_id)
    await db_session.commit()
    return state


@router.post("/{session_id}/guide/skip", response_model=GuidedIntakeState)
async def skip_guided_question(
    session_id: SessionId,
    db_session: DbSession,
) -> GuidedIntakeState:
    state = await GuidedIntakeService(db_session).skip_question(session_id)
    if state is None:
        raise _session_not_found(session_id)
    await db_session.commit()
    return state


@router.post("/{session_id}/guide/skip-all", response_model=GuidedIntakeState)
async def skip_all_guided_questions(
    session_id: SessionId,
    db_session: DbSession,
) -> GuidedIntakeState:
    state = await GuidedIntakeService(db_session).skip_all_and_start_analysis(
        session_id,
    )
    if state is None:
        raise _session_not_found(session_id)
    await db_session.commit()
    return state


@router.post("/{session_id}/guide/reanswer", response_model=GuidedIntakeState)
async def reanswer_guided_question(
    session_id: SessionId,
    request: GuidedReanswerRequest,
    db_session: DbSession,
) -> GuidedIntakeState:
    state = await GuidedIntakeService(db_session).reanswer_question(
        session_id,
        request,
    )
    if state is None:
        raise _session_not_found(session_id)
    return state


@router.post("/{session_id}/guide/region", response_model=GuidedIntakeState)
async def submit_guided_region_setup(
    session_id: SessionId,
    request: RegionSetupSubmission,
    db_session: DbSession,
) -> GuidedIntakeState:
    state = await GuidedIntakeService(db_session).submit_region_setup(
        session_id,
        request,
    )
    if state is None:
        raise _session_not_found(session_id)
    await db_session.commit()
    return state


def _session_not_found(session_id: SessionId) -> ApplicationError:
    return ApplicationError(
        "session_not_found",
        "Session not found.",
        status_code=status.HTTP_404_NOT_FOUND,
        details={"session_id": str(session_id)},
    )
