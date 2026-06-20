import asyncio
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from agents import Agent, ModelSettings, RunConfig, Runner
from pydantic import ValidationError

from app.agents.contracts import IntakeAgentInput
from app.agents.openai_config import build_openai_agent_run_configuration
from app.core.settings import Settings
from app.schemas.intake import (
    BudgetConstraint,
    BudgetMode,
    CreateSessionRequest,
    FieldSource,
    PreferenceConstraint,
    PreferenceMode,
    RegionPreference,
    ShoppingBrief,
)
from app.schemas.money import Money
from app.schemas.regions import Region


class IntakeModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        """Run the SDK intake agent and return its raw run result."""


@dataclass
class OpenAIAgentsSDKIntakeModelRunner:
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
class MockIntakeModelRunner:
    output: ShoppingBrief | dict[str, Any] | None = None
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
        del agent, run_config, max_turns
        self.calls += 1
        if self.error is not None:
            raise self.error
        output = self.output or _mock_brief_from_model_input(model_input)
        return _MockRunResult(final_output=output)


@dataclass
class LiveIntakeAgent:
    settings: Settings
    model_runner: IntakeModelRunner = field(
        default_factory=OpenAIAgentsSDKIntakeModelRunner,
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    async def run(self, input_data: IntakeAgentInput) -> ShoppingBrief:
        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name="IntakeAgent",
            run_id=str(input_data.run_id),
        )
        agent = _build_intake_agent(configuration.model)
        run_config = RunConfig(
            model=configuration.model,
            model_settings=ModelSettings(
                temperature=0,
                max_tokens=900,
                include_usage=True,
            ),
            tracing_disabled=not configuration.tracing_enabled,
            trace_include_sensitive_data=configuration.trace_include_sensitive_data,
            workflow_name=configuration.trace_workflow_name,
            trace_metadata=configuration.trace_metadata,
        )

        try:
            raw_result = await asyncio.wait_for(
                self.model_runner.run(
                    agent,
                    _model_input(input_data),
                    run_config=run_config,
                    max_turns=configuration.max_turns,
                ),
                timeout=configuration.timeout_seconds,
            )
            brief = _coerce_intake_result(
                getattr(raw_result, "final_output", raw_result),
                input_data.request,
            )
        except TimeoutError:
            brief = _fallback_brief(input_data.request)
            self._set_activity("timeout_fallback", input_data, brief)
            return brief
        except (ValidationError, ValueError, TypeError):
            brief = _fallback_brief(input_data.request)
            self._set_activity("schema_invalid_fallback", input_data, brief)
            return brief
        except Exception:
            brief = _fallback_brief(input_data.request)
            self._set_activity("error_fallback", input_data, brief)
            return brief

        self._set_activity("model_intake_completed", input_data, brief)
        return brief

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    def _set_activity(
        self,
        status: str,
        input_data: IntakeAgentInput,
        brief: ShoppingBrief,
    ) -> None:
        self._workbench_activity = (
            {
                "tool_name": "openai_agents_structured_output",
                "status": status,
                "input": {
                    "agent": "IntakeAgent",
                    "allowed_tools": [],
                    "has_explicit_region": input_data.request.region is not None,
                    "has_explicit_budget": input_data.request.budget is not None,
                },
                "output": brief.model_dump(mode="json"),
            },
        )


@dataclass
class _MockRunResult:
    final_output: Any


def _build_intake_agent(model: str) -> Agent[Any]:
    return Agent(
        name="CartCartIntakeAgent",
        model=model,
        model_settings=ModelSettings(
            temperature=0,
            max_tokens=900,
            include_usage=True,
        ),
        instructions=(
            "Convert the shopper's request into a ShoppingBrief. Preserve the "
            "original query exactly. Infer category, region, budget, hard "
            "constraints, and soft preferences only from the shopper's words or "
            "explicit controls. Use FieldSource.INFERRED for inferred values and "
            "keep FieldSource.USER_PROVIDED values from explicit controls. Treat "
            "'under', 'below', 'maximum', 'must', and exact requirements as hard "
            "constraints or hard-cap budgets. Treat use cases, priorities, and "
            "nice-to-have traits as soft preferences. If the product category is "
            "ambiguous, leave category and category_source null instead of "
            "inventing certainty. Do not recommend products, ask for product "
            "links, call tools, mention internal process, or expose agents, "
            "providers, prompts, traces, or policies. Return only the structured "
            "ShoppingBrief."
        ),
        tools=[],
        output_type=ShoppingBrief,
    )


def _model_input(input_data: IntakeAgentInput) -> str:
    return json.dumps(
        {
            "run_id": str(input_data.run_id),
            "request": input_data.request.model_dump(mode="json"),
        },
        sort_keys=True,
    )


def _coerce_intake_result(
    value: Any,
    request: CreateSessionRequest,
) -> ShoppingBrief:
    brief = value if isinstance(value, ShoppingBrief) else ShoppingBrief.model_validate(value)
    return _merge_explicit_request_fields(brief, request)


def _merge_explicit_request_fields(
    brief: ShoppingBrief,
    request: CreateSessionRequest,
) -> ShoppingBrief:
    data = brief.model_dump(mode="python")
    data["original_query"] = request.query
    if request.region is not None:
        data["region"] = request.region
    if request.budget is not None:
        data["budget"] = request.budget
    data["constraints"] = _merge_preferences(
        request.constraints,
        brief.constraints,
    )
    data["preferences"] = _merge_preferences(
        request.preferences,
        brief.preferences,
    )
    return ShoppingBrief.model_validate(data)


def _merge_preferences(
    explicit_items: tuple[PreferenceConstraint, ...],
    inferred_items: tuple[PreferenceConstraint, ...],
) -> tuple[PreferenceConstraint, ...]:
    merged = list(explicit_items)
    seen = {
        (item.text.strip().casefold(), item.mode.value)
        for item in explicit_items
    }
    for item in inferred_items:
        key = (item.text.strip().casefold(), item.mode.value)
        if key in seen:
            continue
        merged.append(item)
        seen.add(key)
    return tuple(merged)


def _fallback_brief(request: CreateSessionRequest) -> ShoppingBrief:
    return ShoppingBrief(
        original_query=request.query,
        region=request.region,
        budget=request.budget,
        constraints=request.constraints,
        preferences=request.preferences,
    )


def _mock_brief_from_model_input(model_input: str) -> ShoppingBrief:
    payload = json.loads(model_input)
    request = CreateSessionRequest.model_validate(payload["request"])
    query = request.query
    lower_query = query.lower()

    category = _mock_category(lower_query)
    region = request.region or _mock_region(lower_query)
    budget = request.budget or _mock_budget(query, region)
    constraints = (*request.constraints, *_mock_constraints(lower_query))
    preferences = (*request.preferences, *_mock_preferences(lower_query))

    return ShoppingBrief(
        original_query=query,
        category=category,
        category_source=FieldSource.INFERRED if category is not None else None,
        region=region,
        budget=budget,
        constraints=constraints,
        preferences=preferences,
    )


def _mock_category(lower_query: str) -> str | None:
    if any(term in lower_query for term in ("monitor", "1440p", "display")):
        return "monitor"
    if any(term in lower_query for term in ("headphone", "earphone", "earbud")):
        return "headphones"
    if "laptop" in lower_query:
        return "laptop"
    if any(term in lower_query for term in ("phone", "smartphone")):
        return "smartphone"
    if "office chair" in lower_query:
        return "office chair"
    return None


def _mock_region(lower_query: str) -> RegionPreference | None:
    if "philippines" in lower_query or "php" in lower_query:
        return RegionPreference(
            region=Region(country_code="PH", currency="PHP"),
            source=FieldSource.INFERRED,
            notes="Inferred from Philippines/PHP wording.",
        )
    if "united states" in lower_query or " usd" in f" {lower_query}":
        return RegionPreference(
            region=Region(country_code="US", currency="USD"),
            source=FieldSource.INFERRED,
        )
    return None


def _mock_budget(
    query: str,
    region: RegionPreference | None,
) -> BudgetConstraint | None:
    normalized = query.replace(",", "")
    php_match = re.search(r"(?:php|₱)\s*(\d+(?:\.\d{1,2})?)", normalized, re.I)
    usd_match = re.search(r"\$\s*(\d+(?:\.\d{1,2})?)", normalized)
    if php_match is not None:
        currency = "PHP"
        amount = php_match.group(1)
    elif usd_match is not None:
        currency = "USD"
        amount = usd_match.group(1)
    else:
        return None

    lower_query = query.lower()
    hard_cap = any(term in lower_query for term in ("under", "below", "max", "maximum"))
    if region is not None and region.region.currency is not None:
        currency = region.region.currency

    return BudgetConstraint(
        amount=Money(amount=Decimal(amount), currency=currency),
        mode=BudgetMode.HARD_CAP if hard_cap else BudgetMode.PREFERRED,
        source=FieldSource.INFERRED,
    )


def _mock_constraints(lower_query: str) -> tuple[PreferenceConstraint, ...]:
    constraints: list[PreferenceConstraint] = []
    if "27-inch" in lower_query or "27 inch" in lower_query:
        constraints.append(
            PreferenceConstraint(
                text="27-inch size",
                mode=PreferenceMode.HARD,
                source=FieldSource.INFERRED,
            )
        )
    if "1440p" in lower_query:
        constraints.append(
            PreferenceConstraint(
                text="1440p resolution",
                mode=PreferenceMode.HARD,
                source=FieldSource.INFERRED,
            )
        )
    return tuple(constraints)


def _mock_preferences(lower_query: str) -> tuple[PreferenceConstraint, ...]:
    preferences: list[PreferenceConstraint] = []
    if "coding" in lower_query:
        preferences.append(
            PreferenceConstraint(
                text="Good for coding",
                mode=PreferenceMode.SOFT,
                source=FieldSource.INFERRED,
            )
        )
    if "movies" in lower_query:
        preferences.append(
            PreferenceConstraint(
                text="Good for movies",
                mode=PreferenceMode.SOFT,
                source=FieldSource.INFERRED,
            )
        )
    return tuple(preferences)
