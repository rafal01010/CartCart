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
from app.schemas.ids import CandidateId, SessionId
from app.schemas.products import (
    CanonicalProduct,
    ManualFallbackReason,
    ManualProductDetails,
    UserAddedProduct,
)
from app.services.product_deduplication import canonical_listing_url


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
    fallback_candidate_id: CandidateId | None = None
    manual_fallback_reason: ManualFallbackReason | None = None
    manual_details: ManualProductDetails | None = None

    @model_validator(mode="after")
    def _requires_url_text_or_product_name(self) -> "CreateUserAddedProductRequest":
        if not (self.input_text or self.url or self.name or self.fallback_candidate_id):
            raise ValueError("user-added products require input_text, url, or name.")
        if self.manual_fallback_reason is None:
            if (
                self.manual_details
                or self.fallback_candidate_id
                or any((self.brand, self.model, self.category))
            ):
                raise ValueError("manual product details require a fallback reason.")
        else:
            if self.url is not None:
                raise ValueError(
                    "manual fallback cannot create a verified listing URL."
                )
            if not (self.name or self.fallback_candidate_id):
                raise ValueError(
                    "manual fallback requires a product name or candidate."
                )
            if (
                self.manual_fallback_reason != ManualFallbackReason.USER_CORRECTION
                and self.fallback_candidate_id is None
            ):
                raise ValueError("research fallback requires an existing candidate.")
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

    product_repository = ProductRepository(db_session)
    if request.url is not None and request.manual_fallback_reason is None:
        requested_url = canonical_listing_url(str(request.url))
        existing = await product_repository.list_user_added_products(session_id)
        if any(
            item.url is not None
            and canonical_listing_url(str(item.url)) == requested_url
            for item in existing
        ):
            return to_session_state_response(session, existing)
    prior = (
        await product_repository.get_user_added_product(
            session_id, request.fallback_candidate_id
        )
        if request.fallback_candidate_id is not None
        else None
    )
    if request.fallback_candidate_id is not None and prior is None:
        raise ApplicationError(
            "candidate_not_found", "Product not found.", status_code=404
        )
    if (
        prior is not None
        and request.manual_fallback_reason == ManualFallbackReason.USER_CORRECTION
        and request.name is None
    ):
        raise ApplicationError(
            "manual_product_name_required",
            "Add the corrected product name.",
            status_code=422,
        )
    if (
        prior is not None
        and request.manual_fallback_reason != ManualFallbackReason.USER_CORRECTION
        and (not prior.research_attempted or prior.listing is not None)
    ):
        raise ApplicationError(
            "manual_fallback_unavailable",
            "Manual details are available after product research is inconclusive.",
            status_code=409,
        )
    product = _manual_product_from_request(request) or (
        prior.product if prior else None
    )
    if request.manual_fallback_reason is not None and product is None:
        raise ApplicationError(
            "manual_product_name_required",
            "Add the product name before saving manual details.",
            status_code=422,
        )
    url = request.url
    if request.manual_fallback_reason == ManualFallbackReason.USER_CORRECTION:
        url = None
    elif prior is not None and request.manual_fallback_reason is not None:
        url = prior.url
    user_added = UserAddedProduct(
        **({"candidate_id": prior.candidate_id} if prior else {}),
        input_text=request.input_text or (prior.input_text if prior else None),
        url=url,
        product=product,
        notes=request.notes or (prior.notes if prior else None),
        research_attempted=prior.research_attempted if prior else False,
        manual_fallback_reason=request.manual_fallback_reason,
        manual_details=(request.manual_details or ManualProductDetails())
        if request.manual_fallback_reason is not None
        else None,
    )
    if prior is not None:
        await product_repository.replace_user_added_product(session_id, user_added)
    else:
        await product_repository.add_user_added_product(session_id, user_added)
    await db_session.commit()

    user_added_products = await product_repository.list_user_added_products(session_id)
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
