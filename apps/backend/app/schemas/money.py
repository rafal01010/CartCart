from decimal import Decimal
from typing import Annotated, Any

from pydantic import BeforeValidator, Field, StringConstraints

from app.schemas.base import CartCartBaseModel


def uppercase_string(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().upper()
    return value


CurrencyCode = Annotated[
    str,
    BeforeValidator(uppercase_string),
    StringConstraints(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    ),
]


class Money(CartCartBaseModel):
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    currency: CurrencyCode
