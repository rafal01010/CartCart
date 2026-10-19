from unittest.mock import create_autospec

import pytest

from app.core.settings import AgentWorkflowMode
from app.orchestration.shopping_runs import (
    ReusedRefinementArtifacts,
    ShoppingRunOrchestrator,
    ShoppingRunPersistenceHooks,
)
from app.schemas.analysis import RecommendationBundle
from app.schemas.errors import ErrorEnvelope
from app.schemas.ids import RunId, new_id
from app.schemas.intake import ShoppingBrief
from app.schemas.runs import RunEvent, RunStage, RunStatus, ShoppingRunRecord


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["run", "resume"])
@pytest.mark.parametrize("failure_point", ["persist_output", "completion_checkpoint"])
async def test_completion_failures_preserve_original_exception(
    monkeypatch: pytest.MonkeyPatch, operation: str, failure_point: str
) -> None:
    original_failure = OSError("Offline injected persistence failure.")
    run = ShoppingRunRecord(session_id=new_id())
    hooks = create_autospec(ShoppingRunPersistenceHooks, instance=True)
    hooks.load_run.return_value = run
    hooks.load_agent_records.return_value = ()
    events: list[RunEvent] = []

    async def emit_event(
        run_id: RunId, *, stage: RunStage, status: RunStatus,
        message: str, error: ErrorEnvelope | None = None,
    ) -> RunEvent:
        if events:
            raise ValueError("terminal shopping runs cannot accept ordinary events.")
        event = RunEvent(
            run_id=run_id, sequence=0, stage=stage, status=status,
            message=message, error=error,
        )
        events.append(event)
        return event

    async def checkpoint() -> None:
        if events and events[-1].status == RunStatus.SUCCEEDED:
            raise original_failure

    hooks.emit_event.side_effect = emit_event
    hooks.checkpoint.side_effect = checkpoint
    if failure_point == "persist_output":
        hooks.persist_live_output.side_effect = original_failure
    orchestrator = ShoppingRunOrchestrator(
        hooks, agent_workflow_mode=AgentWorkflowMode.LIVE
    )
    monkeypatch.setattr(orchestrator, "_STAGES", ())
    brief = ShoppingBrief(original_query="Offline completion control")
    with pytest.raises(OSError) as caught:
        if operation == "run":
            await orchestrator.run(run.run_id, brief=brief)
        else:
            await orchestrator.resume(
                run.run_id, brief,
                reused_artifacts=ReusedRefinementArtifacts(
                    products=(), listings=(), evidence=(), trust_assessments=(),
                    category_analyses=(), recommendation=RecommendationBundle(
                        no_strong_buy=True, no_strong_buy_reason="Offline control."
                    ),
                ),
            )
    assert caught.value is original_failure
    assert [(event.stage, event.status) for event in events] == [
        (RunStage.COMPLETE, RunStatus.SUCCEEDED)
        if failure_point == "completion_checkpoint"
        else (
            RunStage.INTAKE if operation == "run" else RunStage.COMPARISON_DECISION,
            RunStatus.FAILED,
        )
    ]
    hooks.persist_live_output.assert_awaited_once()
    hooks.emit_event.assert_awaited_once()
    assert hooks.checkpoint.await_count == (2 if operation == "run" else 1)
