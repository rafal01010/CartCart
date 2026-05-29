from typing import TypeAlias
from uuid import UUID, uuid4


SessionId: TypeAlias = UUID
RunId: TypeAlias = UUID
SourceId: TypeAlias = UUID
ProductId: TypeAlias = UUID
ListingId: TypeAlias = UUID
CandidateId: TypeAlias = UUID


def new_id() -> UUID:
    return uuid4()
