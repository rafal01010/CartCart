from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.base import VersionedSchema
from app.schemas.errors import ErrorEnvelope
from app.schemas.ids import CandidateId, RunId, SessionId, SourceId, new_id
from app.schemas.intake import BudgetConstraint, PreferenceConstraint, RegionPreference
from app.schemas.timestamps import Timestamp, utc_now


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStage(StrEnum):
    INTAKE = "intake"
    QUERY_PLANNING = "query_planning"
    DISCOVERY = "discovery"
    EXTRACTION = "extraction"
    DEDUPLICATION = "deduplication"
    LISTING_TRUST = "listing_trust"
    CATEGORY_ANALYSIS = "category_analysis"
    COMPARISON_DECISION = "comparison_decision"
    VERIFICATION = "verification"
    COMPLETE = "complete"


class RunEvent(VersionedSchema):
    event_id: CandidateId = Field(default_factory=new_id)
    run_id: RunId
    sequence: int = Field(ge=0)
    stage: RunStage
    status: RunStatus
    message: str = Field(min_length=1, max_length=1000)
    occurred_at: Timestamp = Field(default_factory=utc_now)
    error: ErrorEnvelope | None = None

    @model_validator(mode="after")
    def _failed_events_link_error_envelope(self) -> "RunEvent":
        if self.status == RunStatus.FAILED and self.error is None:
            raise ValueError("failed run events require an error envelope.")
        if self.status != RunStatus.FAILED and self.error is not None:
            raise ValueError("only failed run events may include an error envelope.")
        return self


class RunEventLog(VersionedSchema):
    run_id: RunId
    events: tuple[RunEvent, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _events_must_be_ordered_for_run(self) -> "RunEventLog":
        previous_sequence = -1
        previous_time: Timestamp | None = None
        for event in self.events:
            if event.run_id != self.run_id:
                raise ValueError("run event logs can only include events for one run.")
            if event.sequence <= previous_sequence:
                raise ValueError("run events must be strictly ordered by sequence.")
            if previous_time is not None and event.occurred_at < previous_time:
                raise ValueError("run events cannot move backward in time.")
            previous_sequence = event.sequence
            previous_time = event.occurred_at
        return self


class AgentRunRecord(VersionedSchema):
    record_id: CandidateId = Field(default_factory=new_id)
    run_id: RunId
    stage: RunStage
    agent_name: str = Field(min_length=1, max_length=200)
    status: RunStatus
    started_at: Timestamp
    ended_at: Timestamp | None = None
    trace_id: str | None = Field(default=None, min_length=1, max_length=300)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    error: ErrorEnvelope | None = None

    @model_validator(mode="after")
    def _validate_agent_run_timing_and_error(self) -> "AgentRunRecord":
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("agent run ended_at cannot be earlier than started_at.")
        if self.status == RunStatus.FAILED and self.error is None:
            raise ValueError("failed agent runs require an error envelope.")
        if self.status != RunStatus.FAILED and self.error is not None:
            raise ValueError("only failed agent runs may include an error envelope.")
        return self


class RefinementRequest(VersionedSchema):
    refinement_id: CandidateId = Field(default_factory=new_id)
    session_id: SessionId
    run_id: RunId | None = None
    instruction: str = Field(min_length=1, max_length=1000)
    region: RegionPreference | None = None
    budget: BudgetConstraint | None = None
    constraints: tuple[PreferenceConstraint, ...] = Field(default_factory=tuple)
    preferences: tuple[PreferenceConstraint, ...] = Field(default_factory=tuple)
    created_at: Timestamp = Field(default_factory=utc_now)


class ShoppingRunRecord(VersionedSchema):
    run_id: RunId = Field(default_factory=new_id)
    session_id: SessionId
    status: RunStatus = RunStatus.PENDING
    current_stage: RunStage | None = None
    created_at: Timestamp = Field(default_factory=utc_now)
    started_at: Timestamp | None = None
    completed_at: Timestamp | None = None
    error: ErrorEnvelope | None = None

    @model_validator(mode="after")
    def _validate_run_status_timestamps_and_error(self) -> "ShoppingRunRecord":
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at cannot be earlier than created_at.")
        if self.completed_at is not None:
            comparison_start = self.started_at or self.created_at
            if self.completed_at < comparison_start:
                raise ValueError("completed_at cannot be earlier than run start.")

        if self.status == RunStatus.PENDING and self.started_at is not None:
            raise ValueError("pending runs cannot have started_at.")
        if self.status == RunStatus.RUNNING and self.started_at is None:
            raise ValueError("running runs require started_at.")
        if self.status in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        } and self.completed_at is None:
            raise ValueError("terminal runs require completed_at.")
        if self.status == RunStatus.FAILED and self.error is None:
            raise ValueError("failed runs require an error envelope.")
        if self.status != RunStatus.FAILED and self.error is not None:
            raise ValueError("only failed runs may include an error envelope.")
        return self
