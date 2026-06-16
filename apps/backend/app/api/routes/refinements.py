from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.errors import ApplicationError
from app.db.repositories.products import ProductRepository
from app.db.repositories.refinements import RefinementRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import get_db_session
from app.providers import build_extraction_provider, build_search_provider
from app.schemas.base import CartCartBaseModel
from app.schemas.ids import SessionId
from app.schemas.intake import (
    BudgetConstraint,
    PreferenceConstraint,
    RegionPreference,
)
from app.schemas.runs import RefinementRequest, ShoppingRunRecord
from app.services.refinements import RefinementService


router = APIRouter(
    prefix="/api/sessions/{session_id}/refinements",
    tags=["refinements"],
)

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


class CreateRefinementRequest(CartCartBaseModel):
    instruction: str = Field(min_length=1, max_length=1000)
    region: RegionPreference | None = None
    budget: BudgetConstraint | None = None
    constraints: tuple[PreferenceConstraint, ...] = ()
    preferences: tuple[PreferenceConstraint, ...] = ()


class RefinementRunResponse(CartCartBaseModel):
    refinement: RefinementRequest
    run: ShoppingRunRecord


@router.post(
    "",
    response_model=RefinementRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_refinement(
    session_id: SessionId,
    request: CreateRefinementRequest,
    db_session: DbSession,
    http_request: Request,
) -> RefinementRunResponse:
    refinement = RefinementRequest(
        session_id=session_id,
        instruction=request.instruction,
        region=request.region,
        budget=request.budget,
        constraints=request.constraints,
        preferences=request.preferences,
    )
    result = await _refinement_service(
        db_session,
        http_request,
    ).create_stub_refinement_run(
        session_id,
        refinement,
    )
    if result is None:
        raise _session_not_found(session_id)

    stored_refinement, run = result
    await db_session.commit()
    return RefinementRunResponse(refinement=stored_refinement, run=run)


def _refinement_service(
    db_session: AsyncSession,
    request: Request | None = None,
) -> RefinementService:
    settings = request.app.state.settings if request is not None else None
    return RefinementService(
        session_repository=SessionRepository(db_session),
        run_repository=RunRepository(db_session),
        refinement_repository=RefinementRepository(db_session),
        result_repository=ResultRepository(db_session),
        search_source_repository=SearchSourceRepository(db_session),
        product_repository=ProductRepository(db_session),
        search_provider=(
            build_search_provider(settings) if settings is not None else None
        ),
        extraction_provider=(
            build_extraction_provider(settings) if settings is not None else None
        ),
        default_region_code=(
            settings.default_region_code if settings is not None else "US"
        ),
    )


def _session_not_found(session_id: SessionId) -> ApplicationError:
    return ApplicationError(
        "session_not_found",
        "Session not found.",
        status_code=status.HTTP_404_NOT_FOUND,
        details={"session_id": str(session_id)},
    )
