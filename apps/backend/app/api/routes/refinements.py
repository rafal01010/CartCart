from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.analysis import RecommendationMode

from app.core.errors import ApplicationError
from app.db.repositories.products import ProductRepository
from app.db.repositories.refinements import RefinementRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import get_db_session
from app.schemas.base import CartCartBaseModel
from app.schemas.ids import CandidateId, SessionId
from app.schemas.intake import (
    BudgetConstraint,
    PreferenceConstraint,
    RegionPreference,
)
from app.schemas.runs import RecomputePlan, RefinementRequest, ShoppingRunRecord
from app.services.refinements import RefinementService
from app.api.routes.runs import _run_service


router = APIRouter(
    prefix="/api/sessions/{session_id}/refinements",
    tags=["refinements"],
)

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


class CreateRefinementRequest(CartCartBaseModel):
    instruction: str = Field(min_length=1, max_length=1000)
    category: str | None = Field(default=None, min_length=1, max_length=120)
    result_mode: RecommendationMode | None = None
    region: RegionPreference | None = None
    budget: BudgetConstraint | None = None
    constraints: tuple[PreferenceConstraint, ...] = ()
    preferences: tuple[PreferenceConstraint, ...] = ()


class RefinementRunResponse(CartCartBaseModel):
    refinement: RefinementRequest
    run: ShoppingRunRecord
    plan: RecomputePlan


@router.post(
    "",
    response_model=RefinementRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_refinement(
    session_id: SessionId,
    request: CreateRefinementRequest,
    db_session: DbSession,
) -> RefinementRunResponse:
    refinement = RefinementRequest(
        session_id=session_id,
        instruction=request.instruction,
        category=request.category,
        result_mode=request.result_mode,
        region=request.region,
        budget=request.budget,
        constraints=request.constraints,
        preferences=request.preferences,
    )
    result = await _refinement_service(db_session).create_refinement_plan(
        session_id,
        refinement,
    )
    if result is None:
        raise _session_not_found(session_id)

    stored_refinement, run, plan = result
    await db_session.commit()
    return RefinementRunResponse(refinement=stored_refinement, run=run, plan=plan)


@router.get("/{refinement_id}/plan", response_model=RecomputePlan)
async def get_refinement_plan(
    session_id: SessionId,
    refinement_id: CandidateId,
    db_session: DbSession,
) -> RecomputePlan:
    plan = await RefinementRepository(db_session).get_plan(refinement_id)
    if plan is None or plan.session_id != session_id:
        raise ApplicationError(
            "refinement_not_found", "Refinement not found.", status_code=404
        )
    return plan


@router.post("/{refinement_id}/execute", response_model=ShoppingRunRecord)
async def execute_refinement(
    session_id: SessionId,
    refinement_id: CandidateId,
    db_session: DbSession,
    request: Request,
) -> ShoppingRunRecord:
    repository = RefinementRepository(db_session)
    plan = await repository.get_plan(refinement_id)
    if plan is None or plan.session_id != session_id:
        raise ApplicationError(
            "refinement_not_found", "Refinement not found.", status_code=404
        )
    refinement = await repository.get_for_run(plan.run_id)
    if refinement is None or refinement.refinement_id != refinement_id:
        raise ApplicationError(
            "refinement_not_found", "Refinement not found.", status_code=404
        )
    run = await _run_service(db_session, request).execute_refinement(
        session_id, plan, refinement.instruction
    )
    await db_session.commit()
    return run


def _refinement_service(
    db_session: AsyncSession,
) -> RefinementService:
    return RefinementService(
        session_repository=SessionRepository(db_session),
        run_repository=RunRepository(db_session),
        refinement_repository=RefinementRepository(db_session),
        result_repository=ResultRepository(db_session),
        search_source_repository=SearchSourceRepository(db_session),
        product_repository=ProductRepository(db_session),
    )


def _session_not_found(session_id: SessionId) -> ApplicationError:
    return ApplicationError(
        "session_not_found",
        "Session not found.",
        status_code=status.HTTP_404_NOT_FOUND,
        details={"session_id": str(session_id)},
    )
