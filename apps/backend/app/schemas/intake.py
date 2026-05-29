from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.ids import SessionId, new_id
from app.schemas.money import Money
from app.schemas.regions import Region
from app.schemas.timestamps import Timestamp, utc_now


class FieldSource(StrEnum):
    USER_PROVIDED = "user_provided"
    INFERRED = "inferred"
    DEFAULTED = "defaulted"


class BudgetMode(StrEnum):
    HARD_CAP = "hard_cap"
    PREFERRED = "preferred"


class PreferenceMode(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class BudgetConstraint(CartCartBaseModel):
    amount: Money
    mode: BudgetMode
    source: FieldSource = FieldSource.USER_PROVIDED
    notes: str | None = Field(default=None, min_length=1, max_length=500)

    @property
    def is_hard_cap(self) -> bool:
        return self.mode == BudgetMode.HARD_CAP


class RegionPreference(CartCartBaseModel):
    region: Region
    source: FieldSource
    notes: str | None = Field(default=None, min_length=1, max_length=500)


class PreferenceConstraint(CartCartBaseModel):
    text: str = Field(min_length=1, max_length=500)
    mode: PreferenceMode
    source: FieldSource = FieldSource.USER_PROVIDED

    @property
    def is_hard(self) -> bool:
        return self.mode == PreferenceMode.HARD


class ShoppingBrief(VersionedSchema):
    original_query: str = Field(min_length=1, max_length=4000)
    category: str | None = Field(default=None, min_length=1, max_length=120)
    category_source: FieldSource | None = None
    region: RegionPreference | None = None
    budget: BudgetConstraint | None = None
    constraints: tuple[PreferenceConstraint, ...] = Field(default_factory=tuple)
    preferences: tuple[PreferenceConstraint, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _require_category_source_when_category_is_set(self) -> "ShoppingBrief":
        if self.category is not None and self.category_source is None:
            raise ValueError("category_source is required when category is set.")
        if self.category is None and self.category_source is not None:
            raise ValueError("category_source cannot be set without category.")
        return self


class CreateSessionRequest(CartCartBaseModel):
    query: str = Field(min_length=1, max_length=4000)
    region: RegionPreference | None = None
    budget: BudgetConstraint | None = None
    constraints: tuple[PreferenceConstraint, ...] = Field(default_factory=tuple)
    preferences: tuple[PreferenceConstraint, ...] = Field(default_factory=tuple)


class ShoppingSession(VersionedSchema):
    session_id: SessionId = Field(default_factory=new_id)
    original_input: CreateSessionRequest
    current_brief: ShoppingBrief
    created_at: Timestamp = Field(default_factory=utc_now)
    updated_at: Timestamp = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _updated_at_must_not_precede_created_at(self) -> "ShoppingSession":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at.")
        return self
