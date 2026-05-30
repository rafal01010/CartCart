from app.schemas.base import CartCartBaseModel
from app.schemas.ids import SessionId
from app.schemas.intake import CreateSessionRequest, ShoppingBrief, ShoppingSession
from app.schemas.products import UserAddedProduct
from app.schemas.timestamps import Timestamp


class SessionStateResponse(CartCartBaseModel):
    schema_version: int
    session_id: SessionId
    original_input: CreateSessionRequest
    current_brief: ShoppingBrief
    created_at: Timestamp
    updated_at: Timestamp
    user_added_products: tuple[UserAddedProduct, ...] = ()


def to_session_state_response(
    session: ShoppingSession,
    user_added_products: tuple[UserAddedProduct, ...] = (),
) -> SessionStateResponse:
    return SessionStateResponse(
        schema_version=session.schema_version,
        session_id=session.session_id,
        original_input=session.original_input,
        current_brief=session.current_brief,
        created_at=session.created_at,
        updated_at=session.updated_at,
        user_added_products=user_added_products,
    )
