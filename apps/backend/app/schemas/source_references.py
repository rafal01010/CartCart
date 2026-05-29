from pydantic import AnyHttpUrl, Field

from app.schemas.base import CartCartBaseModel
from app.schemas.ids import SourceId
from app.schemas.timestamps import Timestamp


class SourceReference(CartCartBaseModel):
    source_id: SourceId
    url: AnyHttpUrl
    title: str | None = Field(default=None, min_length=1, max_length=300)
    accessed_at: Timestamp | None = None
