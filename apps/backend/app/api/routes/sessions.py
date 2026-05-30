from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.session_state import SessionStateResponse, to_session_state_response
from app.core.errors import ApplicationError
from app.db.repositories.products import ProductRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import get_db_session
from app.schemas.base import CartCartBaseModel
from app.schemas.ids import SessionId
from app.schemas.intake import (
    BudgetConstraint,
    CreateSessionRequest,
    FieldSource,
    PreferenceConstraint,
    RegionPreference,
    ShoppingBrief,
    ShoppingSession,
)


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class UpdateShoppingBriefRequest(CartCartBaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=120)
    category_source: FieldSource | None = None
    region: RegionPreference | None = None
    budget: BudgetConstraint | None = None
    constraints: tuple[PreferenceConstraint, ...] | None = None
    preferences: tuple[PreferenceConstraint, ...] | None = None

    @model_validator(mode="after")
    def _category_updates_need_explicit_source(self) -> "UpdateShoppingBriefRequest":
        fields_set = self.model_fields_set
        if "category" in fields_set and self.category is not None:
            if "category_source" not in fields_set or self.category_source is None:
                raise ValueError(
                    "category_source is required when category is updated."
                )
        if (
            "category_source" in fields_set
            and self.category_source is not None
            and "category" not in fields_set
        ):
            raise ValueError("category_source cannot be updated without category.")
        if self.category is None and self.category_source is not None:
            raise ValueError("category_source cannot be set without category.")
        return self


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.post(
    "",
    response_model=SessionStateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    request: CreateSessionRequest,
    db_session: DbSession,
) -> SessionStateResponse:
    repository = SessionRepository(db_session)
    brief = ShoppingBrief(
        original_query=request.query,
        region=request.region,
        budget=request.budget,
        constraints=request.constraints,
        preferences=request.preferences,
    )
    created = await repository.create(
        original_input=request,
        current_brief=brief,
    )
    await db_session.commit()
    return to_session_state_response(created)


@router.get("/{session_id}", response_model=SessionStateResponse)
async def get_session(
    session_id: SessionId,
    db_session: DbSession,
) -> SessionStateResponse:
    session = await SessionRepository(db_session).get(session_id)
    if session is None:
        raise _session_not_found(session_id)
    return await _session_state_response(db_session, session)


@router.patch("/{session_id}/brief", response_model=SessionStateResponse)
async def update_session_brief(
    session_id: SessionId,
    request: UpdateShoppingBriefRequest,
    db_session: DbSession,
) -> SessionStateResponse:
    repository = SessionRepository(db_session)
    session = await repository.get(session_id)
    if session is None:
        raise _session_not_found(session_id)

    brief_data = session.current_brief.model_dump()
    for field_name in request.model_fields_set:
        brief_data[field_name] = getattr(request, field_name)
    if "category" in request.model_fields_set and request.category is None:
        brief_data["category_source"] = None

    updated_brief = ShoppingBrief.model_validate(brief_data)
    updated = await repository.update_current_brief(session_id, updated_brief)
    if updated is None:
        raise _session_not_found(session_id)

    await db_session.commit()
    return await _session_state_response(db_session, updated)


async def _session_state_response(
    db_session: AsyncSession,
    session: ShoppingSession,
) -> SessionStateResponse:
    product_repository = ProductRepository(db_session)
    user_added_products = await product_repository.list_user_added_products(
        session.session_id,
    )
    return to_session_state_response(session, user_added_products)


def _session_not_found(session_id: SessionId) -> ApplicationError:
    return ApplicationError(
        "session_not_found",
        "Session not found.",
        status_code=status.HTTP_404_NOT_FOUND,
        details={"session_id": str(session_id)},
    )
