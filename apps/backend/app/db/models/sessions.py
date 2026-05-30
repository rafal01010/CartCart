from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.schemas.intake import CreateSessionRequest, ShoppingBrief, ShoppingSession


def _dump_json(value: CreateSessionRequest | ShoppingBrief) -> dict[str, Any]:
    return value.model_dump(mode="json")


class ShoppingSessionRecord(Base):
    __tablename__ = "shopping_sessions"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    original_query: Mapped[str] = mapped_column(String(4000), nullable=False)
    original_input: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    current_brief: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[str] = mapped_column(String(35), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(35), nullable=False)

    @classmethod
    def from_schema(cls, session: ShoppingSession) -> "ShoppingSessionRecord":
        return cls(
            session_id=str(session.session_id),
            original_query=session.original_input.query,
            original_input=_dump_json(session.original_input),
            current_brief=_dump_json(session.current_brief),
            created_at=session.created_at.isoformat(),
            updated_at=session.updated_at.isoformat(),
        )

    def to_schema(self) -> ShoppingSession:
        return ShoppingSession(
            session_id=UUID(self.session_id),
            original_input=CreateSessionRequest.model_validate(self.original_input),
            current_brief=ShoppingBrief.model_validate(self.current_brief),
            created_at=datetime.fromisoformat(self.created_at),
            updated_at=datetime.fromisoformat(self.updated_at),
        )

    def update_current_brief(self, brief: ShoppingBrief, updated_at: datetime) -> None:
        self.current_brief = _dump_json(brief)
        self.updated_at = updated_at.isoformat()

