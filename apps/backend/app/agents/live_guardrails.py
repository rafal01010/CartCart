import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from agents import (
    Agent,
    GuardrailFunctionOutput,
    ModelSettings,
    RunConfig,
    RunContextWrapper,
    Runner,
    input_guardrail,
)
from pydantic import ValidationError

from app.agents.contracts import ShoppingScopeGuardrailInput
from app.agents.openai_config import build_openai_agent_run_configuration
from app.core.settings import Settings
from app.schemas.guided_intake import (
    ShoppingGuardrailDecision,
    ShoppingGuardrailResult,
)
from app.services.shopping_guardrails import (
    evaluate_shopping_guardrail,
    safe_guardrail_failure_result,
)


class ShoppingGuardrailModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        """Run the SDK classifier agent and return its raw run result."""


@dataclass
class OpenAIAgentsSDKModelRunner:
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        return await Runner.run(
            agent,
            model_input,
            run_config=run_config,
            max_turns=max_turns,
        )


@dataclass
class MockShoppingGuardrailModelRunner:
    output: ShoppingGuardrailResult | dict[str, Any] | None = None
    error: BaseException | None = None
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
        if self.error is not None:
            raise self.error
        output = self.output or ShoppingGuardrailResult(
            decision=ShoppingGuardrailDecision.ALLOWED,
        )
        return _MockRunResult(final_output=output)


@dataclass
class LiveShoppingScopeGuardrail:
    settings: Settings
    model_runner: ShoppingGuardrailModelRunner = field(
        default_factory=OpenAIAgentsSDKModelRunner,
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    async def run(
        self,
        input_data: ShoppingScopeGuardrailInput,
    ) -> ShoppingGuardrailResult:
        deterministic_result = evaluate_shopping_guardrail(
            input_data.user_input,
            prior_answers=input_data.prior_answers,
        )
        if deterministic_result.decision == ShoppingGuardrailDecision.BLOCKED:
            self._set_activity(
                "not_started_deterministic_block",
                output=deterministic_result,
            )
            return deterministic_result

        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name="ShoppingScopeGuardrail",
        )
        runtime = _ShoppingGuardrailRuntime(self, input_data)
        context = RunContextWrapper(context=runtime)
        guardrail_agent = _build_guardrail_classifier_agent(configuration.model)

        try:
            guardrail_result = await asyncio.wait_for(
                _shopping_scope_input_guardrail.run(
                    guardrail_agent,
                    _model_input(input_data),
                    context,
                ),
                timeout=configuration.timeout_seconds,
            )
            result = _coerce_guardrail_result(
                guardrail_result.output.output_info,
            )
        except TimeoutError:
            result = safe_guardrail_failure_result()
            self._set_activity("timeout_blocked", output=result)
            return result
        except (ValidationError, ValueError, TypeError):
            result = safe_guardrail_failure_result()
            self._set_activity("schema_invalid_blocked", output=result)
            return result
        except Exception:
            result = safe_guardrail_failure_result()
            self._set_activity("error_blocked", output=result)
            return result

        self._set_activity(
            "model_guardrail_completed",
            output=result,
        )
        return result

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    async def _classify_with_model(
        self,
        input_data: ShoppingScopeGuardrailInput,
    ) -> ShoppingGuardrailResult:
        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name="ShoppingScopeGuardrail",
        )
        agent = _build_guardrail_classifier_agent(configuration.model)
        run_config = RunConfig(
            model=configuration.model,
            model_settings=ModelSettings(
                temperature=0,
                max_tokens=300,
                include_usage=True,
            ),
            tracing_disabled=not configuration.tracing_enabled,
            trace_include_sensitive_data=configuration.trace_include_sensitive_data,
            workflow_name=configuration.trace_workflow_name,
            trace_metadata=configuration.trace_metadata,
        )
        raw_result = await self.model_runner.run(
            agent,
            _model_input(input_data),
            run_config=run_config,
            max_turns=configuration.max_turns,
        )
        return _coerce_guardrail_result(
            getattr(raw_result, "final_output", raw_result),
        )

    def _set_activity(
        self,
        status: str,
        *,
        output: ShoppingGuardrailResult,
    ) -> None:
        self._workbench_activity = (
            {
                "tool_name": "openai_agents_input_guardrail",
                "status": status,
                "input": {"classifier": "ShoppingScopeGuardrail"},
                "output": output.model_dump(mode="json"),
            },
        )


@dataclass
class _MockRunResult:
    final_output: Any


@dataclass
class _ShoppingGuardrailRuntime:
    guardrail: LiveShoppingScopeGuardrail
    input_data: ShoppingScopeGuardrailInput

    async def classify(self) -> ShoppingGuardrailResult:
        return await self.guardrail._classify_with_model(self.input_data)


@input_guardrail(name="cartcart_shopping_scope_guardrail", run_in_parallel=False)
async def _shopping_scope_input_guardrail(
    context: RunContextWrapper[_ShoppingGuardrailRuntime],
    agent: Agent[Any],
    input_value: str | list[Any],
) -> GuardrailFunctionOutput:
    del agent, input_value
    result = await context.context.classify()
    return GuardrailFunctionOutput(
        output_info=result,
        tripwire_triggered=result.decision == ShoppingGuardrailDecision.BLOCKED,
    )


def _build_guardrail_classifier_agent(model: str) -> Agent[Any]:
    return Agent(
        name="CartCartShoppingScopeGuardrailClassifier",
        model=model,
        model_settings=ModelSettings(
            temperature=0,
            max_tokens=300,
            include_usage=True,
        ),
        instructions=(
            "Classify whether the shopper's request may proceed in CartCart. "
            "Allow ordinary consumer shopping, product comparison, budget, "
            "availability, and buyer-risk questions. Block requests that are "
            "off-topic, illegal purchases, dangerous products, weapons, "
            "explosives, or adult sexual shopping. Return only the structured "
            "ShoppingGuardrailResult. Blocked messages must be short and plain "
            "for a regular shopper. Do not mention agents, tools, providers, "
            "prompts, traces, policies, or internal process."
        ),
        tools=[],
        output_type=ShoppingGuardrailResult,
    )


def _model_input(input_data: ShoppingScopeGuardrailInput) -> str:
    return json.dumps(
        {
            "user_input": input_data.user_input,
            "prior_answers": [
                answer.model_dump(mode="json") for answer in input_data.prior_answers
            ],
        },
        sort_keys=True,
    )


def _coerce_guardrail_result(value: Any) -> ShoppingGuardrailResult:
    if isinstance(value, ShoppingGuardrailResult):
        return value
    return ShoppingGuardrailResult.model_validate(value)
