from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.base import CartCartBaseModel


ReasoningEffort = Literal[
    "none", "minimal", "low", "medium", "high", "xhigh", "max"
]


class AgentRunProfileName(StrEnum):
    DEFAULT = "default"
    FAST = "fast"
    STRONG = "strong"


class AgentRunProfileOptions(CartCartBaseModel):
    model: str | None = Field(default=None, min_length=1, max_length=200)
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)
    max_turns: int | None = Field(default=None, ge=1, le=50)
    reasoning_effort: ReasoningEffort | None = None

    @field_validator("model")
    @classmethod
    def _strip_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("An agent model override must not be blank.")
        return stripped
