from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import StreamingResponse

from app.core.errors import ApplicationError
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.repositories.source_intelligence import SourceIntelligenceRepository
from app.db.repositories.video_sources import VideoReviewRepository
from app.db.session import get_db_session
from app.providers import (
    build_amazon_product_intelligence_provider,
    build_community_discussion_provider,
    build_extraction_provider,
    build_ikea_store_intelligence_provider,
    build_search_provider,
    build_transcript_provider,
    build_video_search_provider,
)
from app.schemas.ids import RunId, SessionId
from app.schemas.runs import RunEvent, ShoppingRunRecord
from app.services.runs import RunService


router = APIRouter(prefix="/api/sessions/{session_id}/runs", tags=["runs"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.post("", response_model=ShoppingRunRecord, status_code=status.HTTP_201_CREATED)
async def create_run(
    session_id: SessionId,
    db_session: DbSession,
    request: Request,
) -> ShoppingRunRecord:
    run = await _run_service(db_session, request).create_stub_run(session_id)
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


def _run_service(
    db_session: AsyncSession,
    request: Request | None = None,
) -> RunService:
    settings = request.app.state.settings if request is not None else None
    return RunService(
        session_repository=SessionRepository(db_session),
        run_repository=RunRepository(db_session),
        result_repository=ResultRepository(db_session),
        search_source_repository=SearchSourceRepository(db_session),
        product_repository=ProductRepository(db_session),
        source_intelligence_repository=SourceIntelligenceRepository(db_session),
        video_review_repository=VideoReviewRepository(db_session),
        search_provider=(
            build_search_provider(settings) if settings is not None else None
        ),
        extraction_provider=(
            build_extraction_provider(settings) if settings is not None else None
        ),
        video_search_provider=(
            build_video_search_provider(settings) if settings is not None else None
        ),
        transcript_provider=(
            build_transcript_provider(settings) if settings is not None else None
        ),
        community_discussion_provider=(
            build_community_discussion_provider(settings)
            if settings is not None
            else None
        ),
        amazon_product_intelligence_provider=(
            build_amazon_product_intelligence_provider(settings)
            if settings is not None
            else None
        ),
        ikea_store_intelligence_provider=(
            build_ikea_store_intelligence_provider(settings)
            if settings is not None
            else None
        ),
        default_region_code=(
            settings.default_region_code if settings is not None else "US"
        ),
        settings=settings,
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
