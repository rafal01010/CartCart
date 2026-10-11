import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from agents import Agent, RunConfig

from app.agents import LiveShoppingScopeGuardrail, ShoppingScopeGuardrailInput
from app.core.settings import Settings
from app.core.errors import ApplicationError
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
async def test_live_guardrail_does_not_phrase_block_ordinary_shopping() -> None:
    runner = RecordingGuardrailRunner()
    guardrail = LiveShoppingScopeGuardrail(settings=_settings(), model_runner=runner)
    result = await guardrail.run(
        ShoppingScopeGuardrailInput(
            user_input="Choose a glue gun for my homework craft project.",
        )
    )
    assert result.decision == ShoppingGuardrailDecision.ALLOWED
    assert runner.calls == 1


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
@pytest.mark.parametrize("failure", ["invalid", "timeout", "error"])
async def test_classifier_failure_is_retryable_not_off_topic(failure: str) -> None:
    runner = RecordingGuardrailRunner(
        output={"decision": "blocked"} if failure == "invalid" else None,
        delay_seconds=0.02 if failure == "timeout" else 0,
        error=RuntimeError("classifier failed") if failure == "error" else None,
    )
    guardrail = LiveShoppingScopeGuardrail(
        settings=_settings(openai_agent_timeout_seconds=0.001)
        if failure == "timeout"
        else _settings(),
        model_runner=runner,
    )
    with pytest.raises(ApplicationError) as caught:
        await guardrail.run(
            ShoppingScopeGuardrailInput(user_input="Help me choose a desk.")
        )
    assert caught.value.code == "shopping_guardrail_unavailable"
    assert caught.value.status_code == 503
    assert caught.value.details == {"retryable": True}
    assert runner.calls == 1
