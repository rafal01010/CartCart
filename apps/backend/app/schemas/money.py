from decimal import Decimal
from typing import Annotated, Any

from pydantic import BeforeValidator, Field, StringConstraints, WithJsonSchema

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
    amount: Annotated[
        Decimal,
        WithJsonSchema(
            {
                "anyOf": [
                    {"type": "number", "minimum": 0},
                    {
                        "type": "string",
                        "pattern": r"^[0-9]{1,10}(?:\.[0-9]{1,2})?$",
                    },
                ]
            },
            mode="validation",
        ),
    ] = Field(ge=0, max_digits=12, decimal_places=2)
    currency: CurrencyCode
