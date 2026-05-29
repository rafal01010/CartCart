from typing import Annotated

from pydantic import BeforeValidator, Field, StringConstraints

from app.schemas.base import CartCartBaseModel
from app.schemas.money import CurrencyCode, uppercase_string


RegionCode = Annotated[
    str,
    BeforeValidator(uppercase_string),
    StringConstraints(
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z]{2}$",
    ),
]


class Region(CartCartBaseModel):
    country_code: RegionCode
    currency: CurrencyCode | None = None
    locale: str | None = Field(default=None, min_length=2, max_length=35)
