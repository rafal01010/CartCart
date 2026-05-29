from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include timezone information.")
    return value.astimezone(UTC)


Timestamp = Annotated[datetime, AfterValidator(_ensure_aware_utc)]


def utc_now() -> datetime:
    return datetime.now(UTC)
