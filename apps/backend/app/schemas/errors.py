from typing import Any

from pydantic import Field

from app.schemas.base import CartCartBaseModel


class ErrorBody(CartCartBaseModel):
    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=1000)
    request_id: str = Field(min_length=1, max_length=200)
    details: Any | None = None


class ErrorEnvelope(CartCartBaseModel):
    error: ErrorBody
