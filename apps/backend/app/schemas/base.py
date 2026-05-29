from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


SchemaVersion = Annotated[int, Field(ge=1)]


class CartCartBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class VersionedSchema(CartCartBaseModel):
    schema_version: SchemaVersion = 1
