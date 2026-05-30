from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import AnyHttpUrl, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.session_state import SessionStateResponse, to_session_state_response
from app.core.errors import ApplicationError
from app.db.repositories.products import ProductRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import get_db_session
from app.schemas.base import CartCartBaseModel
from app.schemas.ids import SessionId
from app.schemas.products import CanonicalProduct, UserAddedProduct


router = APIRouter(prefix="/api/sessions/{session_id}/products", tags=["products"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


class CreateUserAddedProductRequest(CartCartBaseModel):
    input_text: str | None = Field(default=None, min_length=1, max_length=1000)
    url: AnyHttpUrl | None = None
    name: str | None = Field(default=None, min_length=1, max_length=300)
    brand: str | None = Field(default=None, min_length=1, max_length=200)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def _requires_url_text_or_product_name(self) -> "CreateUserAddedProductRequest":
        if not (self.input_text or self.url or self.name):
            raise ValueError("user-added products require input_text, url, or name.")
        return self


@router.post(
    "",
    response_model=SessionStateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_user_added_product(
    session_id: SessionId,
    request: CreateUserAddedProductRequest,
    db_session: DbSession,
) -> SessionStateResponse:
    session_repository = SessionRepository(db_session)
    session = await session_repository.get(session_id)
    if session is None:
        raise _session_not_found(session_id)

    product = _manual_product_from_request(request)
    user_added = UserAddedProduct(
        input_text=request.input_text,
        url=request.url,
        product=product,
        notes=request.notes,
    )
    product_repository = ProductRepository(db_session)
    await product_repository.add_user_added_product(session_id, user_added)
    await db_session.commit()

    user_added_products = await product_repository.list_user_added_products(
        session_id
    )
    return to_session_state_response(session, user_added_products)


def _manual_product_from_request(
    request: CreateUserAddedProductRequest,
) -> CanonicalProduct | None:
    if request.name is None:
        return None
    return CanonicalProduct(
        name=request.name,
        brand=request.brand,
        model=request.model,
        category=request.category,
    )


def _session_not_found(session_id: SessionId) -> ApplicationError:
    return ApplicationError(
        "session_not_found",
        "Session not found.",
        status_code=status.HTTP_404_NOT_FOUND,
        details={"session_id": str(session_id)},
    )
