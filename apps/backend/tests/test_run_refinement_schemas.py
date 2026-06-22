from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import (
    AgentRunRecord,
    BudgetConstraint,
    BudgetMode,
    ErrorBody,
    ErrorEnvelope,
    FieldSource,
    Money,
    PreferenceConstraint,
    PreferenceMode,
    RefinementRequest,
    Region,
    RegionPreference,
    RunEvent,
    RunEventLog,
    RunStage,
    RunStatus,
    ShoppingRunRecord,
    new_id,
)


def make_error() -> ErrorEnvelope:
    return ErrorEnvelope(
        error=ErrorBody(
            code="provider_failed",
            message="Provider failed.",
            request_id="request-123",
            details={"provider": "fixture"},
        )
    )


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.PENDING,
        RunStatus.RUNNING,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    ],
)
def test_run_event_accepts_all_run_statuses(status: RunStatus) -> None:
    event = RunEvent(
        run_id=new_id(),
        sequence=0,
        stage=RunStage.DISCOVERY,
        status=status,
        message=f"Run is {status.value}.",
        occurred_at="2026-05-30T00:00:00Z",
        error=make_error() if status == RunStatus.FAILED else None,
    )

    assert event.status == status
    assert event.occurred_at == datetime(2026, 5, 30, 0, 0, tzinfo=UTC)


def test_run_event_links_error_envelope_only_for_failed_status() -> None:
    with pytest.raises(ValidationError):
        RunEvent(
            run_id=new_id(),
            sequence=0,
            stage=RunStage.EXTRACTION,
            status=RunStatus.FAILED,
            message="Extraction failed.",
        )

    with pytest.raises(ValidationError):
        RunEvent(
            run_id=new_id(),
            sequence=0,
            stage=RunStage.EXTRACTION,
            status=RunStatus.RUNNING,
            message="Extraction running.",
            error=make_error(),
        )


def test_run_event_log_enforces_run_id_sequence_and_timestamp_ordering() -> None:
    run_id = new_id()
    first = RunEvent(
        run_id=run_id,
        sequence=0,
        stage=RunStage.INTAKE,
        status=RunStatus.SUCCEEDED,
        message="Intake complete.",
        occurred_at="2026-05-30T00:00:00Z",
    )
    second = RunEvent(
        run_id=run_id,
        sequence=1,
        stage=RunStage.QUERY_PLANNING,
        status=RunStatus.RUNNING,
        message="Planning queries.",
        occurred_at="2026-05-30T00:00:01Z",
    )
    log = RunEventLog(run_id=run_id, events=(first, second))

    assert log.events[0].sequence == 0
    assert log.events[1].sequence == 1

    with pytest.raises(ValidationError):
        RunEventLog(run_id=run_id, events=(second, first))

    with pytest.raises(ValidationError):
        RunEventLog(
            run_id=run_id,
            events=(
                first,
                RunEvent(
                    run_id=new_id(),
                    sequence=1,
                    stage=RunStage.DISCOVERY,
                    status=RunStatus.RUNNING,
                    message="Wrong run.",
                    occurred_at="2026-05-30T00:00:01Z",
                ),
            ),
        )


def test_shopping_run_record_validates_status_timestamps_and_errors() -> None:
    session_id = new_id()
    pending = ShoppingRunRecord(
        session_id=session_id,
        status=RunStatus.PENDING,
        created_at="2026-05-30T00:00:00Z",
    )
    running = ShoppingRunRecord(
        session_id=session_id,
        status=RunStatus.RUNNING,
        current_stage=RunStage.DISCOVERY,
        created_at="2026-05-30T00:00:00Z",
        started_at="2026-05-30T00:00:01Z",
    )
    succeeded = ShoppingRunRecord(
        session_id=session_id,
        status=RunStatus.SUCCEEDED,
        current_stage=RunStage.COMPLETE,
        created_at="2026-05-30T00:00:00Z",
        started_at="2026-05-30T00:00:01Z",
        completed_at="2026-05-30T00:00:02Z",
    )
    failed = ShoppingRunRecord(
        session_id=session_id,
        status=RunStatus.FAILED,
        current_stage=RunStage.EXTRACTION,
        created_at="2026-05-30T00:00:00Z",
        started_at="2026-05-30T00:00:01Z",
        completed_at="2026-05-30T00:00:02Z",
        error=make_error(),
    )
    cancelled = ShoppingRunRecord(
        session_id=session_id,
        status=RunStatus.CANCELLED,
        current_stage=RunStage.DISCOVERY,
        created_at="2026-05-30T00:00:00Z",
        started_at="2026-05-30T00:00:01Z",
        completed_at="2026-05-30T00:00:02Z",
    )

    assert pending.started_at is None
    assert running.current_stage == RunStage.DISCOVERY
    assert succeeded.completed_at is not None
    assert failed.error is not None
    assert cancelled.status == RunStatus.CANCELLED

    with pytest.raises(ValidationError):
        ShoppingRunRecord(
            session_id=session_id,
            status=RunStatus.RUNNING,
            created_at="2026-05-30T00:00:00Z",
        )

    with pytest.raises(ValidationError):
        ShoppingRunRecord(
            session_id=session_id,
            status=RunStatus.FAILED,
            created_at="2026-05-30T00:00:00Z",
            started_at="2026-05-30T00:00:01Z",
            completed_at="2026-05-30T00:00:02Z",
        )


def test_agent_run_record_links_trace_and_error_envelope() -> None:
    run_id = new_id()
    record = AgentRunRecord(
        run_id=run_id,
        stage=RunStage.CATEGORY_ANALYSIS,
        agent_name="GenericProductAnalystAgent",
        status=RunStatus.SUCCEEDED,
        started_at="2026-05-30T00:00:01Z",
        ended_at="2026-05-30T00:00:02Z",
        trace_id="trace-123",
        source_ids=(new_id(),),
        runtime_mode="live",
        model_name="gpt-test",
        duration_ms=1000.0,
        input_tokens=12,
        output_tokens=24,
        total_tokens=36,
        estimated_cost_usd="0.0001",
        tool_activity=(
            {"tool_name": "openai_agents_structured_output", "status": "completed"},
        ),
        fallback_outcome=None,
    )

    assert record.trace_id == "trace-123"
    assert record.model_name == "gpt-test"
    assert record.tool_activity[0]["status"] == "completed"
    assert record.error is None

    with pytest.raises(ValidationError):
        AgentRunRecord(
            run_id=run_id,
            stage=RunStage.EXTRACTION,
            agent_name="ExtractionAgent",
            status=RunStatus.FAILED,
            started_at="2026-05-30T00:00:01Z",
            ended_at="2026-05-30T00:00:02Z",
        )

    with pytest.raises(ValidationError):
        AgentRunRecord(
            run_id=run_id,
            stage=RunStage.EXTRACTION,
            agent_name="ExtractionAgent",
            status=RunStatus.SUCCEEDED,
            started_at="2026-05-30T00:00:02Z",
            ended_at="2026-05-30T00:00:01Z",
        )


def test_refinement_request_accepts_targeted_brief_changes() -> None:
    refinement = RefinementRequest(
        session_id=new_id(),
        run_id=new_id(),
        instruction="Tighten the budget and prioritize quieter fans.",
        region=RegionPreference(
            region=Region(country_code="US", currency="USD"),
            source=FieldSource.USER_PROVIDED,
        ),
        budget=BudgetConstraint(
            amount=Money(amount="900.00", currency="USD"),
            mode=BudgetMode.HARD_CAP,
            source=FieldSource.USER_PROVIDED,
        ),
        preferences=(
            PreferenceConstraint(
                text="Prefer quiet fans.",
                mode=PreferenceMode.SOFT,
                source=FieldSource.USER_PROVIDED,
            ),
        ),
        created_at="2026-05-30T00:00:00Z",
    )

    assert refinement.region is not None
    assert refinement.budget is not None
    assert refinement.preferences[0].text == "Prefer quiet fans."

    with pytest.raises(ValidationError):
        RefinementRequest(session_id=new_id(), instruction="")
