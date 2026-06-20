import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from agents import Agent, RunConfig

from app.agents import LiveShoppingScopeGuardrail, ShoppingScopeGuardrailInput
from app.core.settings import Settings
from app.schemas.guided_intake import (
    ShoppingGuardrailDecision,
    ShoppingGuardrailReason,
    ShoppingGuardrailResult,
)


@dataclass
class RecordingGuardrailRunner:
    output: ShoppingGuardrailResult | dict[str, Any] | None = None
    error: BaseException | None = None
    delay_seconds: float = 0
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        del agent, model_input, run_config, max_turns
        self.calls += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        return _RunResult(
            final_output=self.output
            or ShoppingGuardrailResult(decision=ShoppingGuardrailDecision.ALLOWED)
        )


@dataclass
class _RunResult:
    final_output: Any


def _settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        **overrides,
    )


@pytest.mark.asyncio
async def test_live_guardrail_accepts_valid_mocked_structured_output() -> None:
    runner = RecordingGuardrailRunner()
    guardrail = LiveShoppingScopeGuardrail(
        settings=_settings(),
        model_runner=runner,
    )

    result = await guardrail.run(
        ShoppingScopeGuardrailInput(
            user_input="Help me choose a burr coffee grinder under $200",
        )
    )

    assert result.decision == ShoppingGuardrailDecision.ALLOWED
    assert runner.calls == 1
    assert guardrail.workbench_activity[0]["status"] == "model_guardrail_completed"


@pytest.mark.asyncio
async def test_live_guardrail_preblocks_dangerous_request() -> None:
    runner = RecordingGuardrailRunner()
    guardrail = LiveShoppingScopeGuardrail(
        settings=_settings(),
        model_runner=runner,
    )

    result = await guardrail.run(
        ShoppingScopeGuardrailInput(
            user_input="Help me choose a handgun for home defense",
        )
    )

    assert result.decision == ShoppingGuardrailDecision.BLOCKED
    assert result.reason == ShoppingGuardrailReason.UNSAFE_PRODUCT
    assert runner.calls == 0
    assert guardrail.workbench_activity[0]["status"] == (
        "not_started_deterministic_block"
    )


@pytest.mark.asyncio
async def test_live_guardrail_returns_model_blocked_output() -> None:
    runner = RecordingGuardrailRunner(
        output=ShoppingGuardrailResult(
            decision=ShoppingGuardrailDecision.BLOCKED,
            reason=ShoppingGuardrailReason.INAPPROPRIATE_PRODUCT,
            message=(
                "I cannot help with that request. "
                "I can help with ordinary consumer purchases."
            ),
        )
    )
    guardrail = LiveShoppingScopeGuardrail(
        settings=_settings(),
        model_runner=runner,
    )

    result = await guardrail.run(
        ShoppingScopeGuardrailInput(user_input="Find adult sexual shopping sites")
    )

    assert result.decision == ShoppingGuardrailDecision.BLOCKED
    assert result.reason == ShoppingGuardrailReason.INAPPROPRIATE_PRODUCT
    assert runner.calls == 1


@pytest.mark.asyncio
async def test_live_guardrail_fails_closed_on_invalid_model_output() -> None:
    runner = RecordingGuardrailRunner(output={"decision": "blocked"})
    guardrail = LiveShoppingScopeGuardrail(
        settings=_settings(),
        model_runner=runner,
    )

    result = await guardrail.run(
        ShoppingScopeGuardrailInput(user_input="Can you help me choose something?")
    )

    assert result.decision == ShoppingGuardrailDecision.BLOCKED
    assert runner.calls == 1
    assert guardrail.workbench_activity[0]["status"] == "schema_invalid_blocked"


@pytest.mark.asyncio
async def test_live_guardrail_fails_closed_on_timeout() -> None:
    runner = RecordingGuardrailRunner(delay_seconds=0.02)
    guardrail = LiveShoppingScopeGuardrail(
        settings=_settings(openai_agent_timeout_seconds=0.001),
        model_runner=runner,
    )

    result = await guardrail.run(
        ShoppingScopeGuardrailInput(user_input="Can you help me choose something?")
    )

    assert result.decision == ShoppingGuardrailDecision.BLOCKED
    assert runner.calls == 1
    assert guardrail.workbench_activity[0]["status"] == "timeout_blocked"


@pytest.mark.asyncio
async def test_live_guardrail_fails_closed_on_model_error() -> None:
    runner = RecordingGuardrailRunner(error=RuntimeError("mock model failed"))
    guardrail = LiveShoppingScopeGuardrail(
        settings=_settings(),
        model_runner=runner,
    )

    result = await guardrail.run(
        ShoppingScopeGuardrailInput(user_input="Can you help me choose something?")
    )

    assert result.decision == ShoppingGuardrailDecision.BLOCKED
    assert runner.calls == 1
    assert guardrail.workbench_activity[0]["status"] == "error_blocked"
