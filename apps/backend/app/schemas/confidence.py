from enum import StrEnum
from typing import Annotated

from pydantic import Field

from app.schemas.base import CartCartBaseModel


ConfidenceScore = Annotated[float, Field(ge=0.0, le=1.0)]


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Confidence(CartCartBaseModel):
    score: ConfidenceScore
    level: ConfidenceLevel
    rationale: str | None = None
