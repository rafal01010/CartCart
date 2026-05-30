from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.schemas.errors import ErrorEnvelope
from app.schemas.runs import (
    RefinementRequest,
    RunEvent,
    RunStage,
    RunStatus,
    ShoppingRunRecord,
)


def _dump_json(value: RefinementRequest) -> dict[str, Any]:
    return value.model_dump(mode="json")


def _dump_error(error: ErrorEnvelope | None) -> dict[str, Any] | None:
    if error is None:
        return None
    return error.model_dump(mode="json")


def _load_error(error: dict[str, Any] | None) -> ErrorEnvelope | None:
    if error is None:
        return None
    return ErrorEnvelope.model_validate(error)


class ShoppingRunRecordModel(Base):
    __tablename__ = "shopping_runs"
    __table_args__ = (Index("ix_shopping_runs_session_id", "session_id"),)

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_sessions.session_id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[str] = mapped_column(String(35), nullable=False)
    started_at: Mapped[str | None] = mapped_column(String(35), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(35), nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    @classmethod
    def from_schema(cls, run: ShoppingRunRecord) -> "ShoppingRunRecordModel":
        return cls(
            run_id=str(run.run_id),
            session_id=str(run.session_id),
            status=run.status.value,
            current_stage=run.current_stage.value if run.current_stage else None,
            created_at=run.created_at.isoformat(),
            started_at=run.started_at.isoformat() if run.started_at else None,
            completed_at=run.completed_at.isoformat() if run.completed_at else None,
            error=_dump_error(run.error),
        )

    def to_schema(self) -> ShoppingRunRecord:
        return ShoppingRunRecord(
            run_id=UUID(self.run_id),
            session_id=UUID(self.session_id),
            status=RunStatus(self.status),
            current_stage=RunStage(self.current_stage) if self.current_stage else None,
            created_at=datetime.fromisoformat(self.created_at),
            started_at=(
                datetime.fromisoformat(self.started_at) if self.started_at else None
            ),
            completed_at=(
                datetime.fromisoformat(self.completed_at)
                if self.completed_at
                else None
            ),
            error=_load_error(self.error),
        )

    def apply_event(self, event: RunEvent) -> None:
        self.status = event.status.value
        self.current_stage = event.stage.value
        if event.status == RunStatus.RUNNING and self.started_at is None:
            self.started_at = event.occurred_at.isoformat()
        if event.status in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }:
            if self.started_at is None:
                self.started_at = event.occurred_at.isoformat()
            self.completed_at = event.occurred_at.isoformat()
        self.error = (
            _dump_error(event.error) if event.status == RunStatus.FAILED else None
        )


class RunEventRecord(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        Index("ix_run_events_run_id", "run_id"),
        Index("ix_run_events_run_id_sequence", "run_id", "sequence"),
        UniqueConstraint(
            "run_id",
            "sequence",
            name="uq_run_events_run_id_sequence",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    stage: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    occurred_at: Mapped[str] = mapped_column(String(35), nullable=False)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    @classmethod
    def from_schema(cls, event: RunEvent) -> "RunEventRecord":
        return cls(
            event_id=str(event.event_id),
            run_id=str(event.run_id),
            sequence=event.sequence,
            stage=event.stage.value,
            status=event.status.value,
            message=event.message,
            occurred_at=event.occurred_at.isoformat(),
            error=_dump_error(event.error),
        )

    def to_schema(self) -> RunEvent:
        return RunEvent(
            event_id=UUID(self.event_id),
            run_id=UUID(self.run_id),
            sequence=self.sequence,
            stage=RunStage(self.stage),
            status=RunStatus(self.status),
            message=self.message,
            occurred_at=datetime.fromisoformat(self.occurred_at),
            error=_load_error(self.error),
        )


class RefinementRequestRecord(Base):
    __tablename__ = "refinement_requests"
    __table_args__ = (
        Index("ix_refinement_requests_session_id", "session_id"),
        Index("ix_refinement_requests_run_id", "run_id"),
    )

    refinement_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_sessions.session_id"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    instruction: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[str] = mapped_column(String(35), nullable=False)
    refinement: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(cls, refinement: RefinementRequest) -> "RefinementRequestRecord":
        if refinement.run_id is None:
            raise ValueError("persisted refinement requests require run_id.")
        return cls(
            refinement_id=str(refinement.refinement_id),
            session_id=str(refinement.session_id),
            run_id=str(refinement.run_id),
            instruction=refinement.instruction,
            created_at=refinement.created_at.isoformat(),
            refinement=_dump_json(refinement),
        )

    def to_schema(self) -> RefinementRequest:
        return RefinementRequest.model_validate(self.refinement)
