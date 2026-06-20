import asyncio
from dataclasses import dataclass
from decimal import Decimal
import os
from typing import Any

import pytest

from agents import Agent, RunConfig

from app.agents import IntakeAgentInput, LiveIntakeAgent
from app.core.settings import Settings
from app.schemas.ids import new_id
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


@dataclass
class RecordingIntakeRunner:
    output: ShoppingBrief | dict[str, Any] | None = None
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
        return _RunResult(final_output=self.output or _monitor_brief())


@dataclass
class _RunResult:
    final_output: Any


def _settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        **overrides,
    )


def _monitor_query() -> str:
    return (
        "I need a 27-inch 1440p monitor for coding and movies under "
        "PHP 18,000 in the Philippines"
    )


def _monitor_brief(query: str | None = None) -> ShoppingBrief:
    return ShoppingBrief(
        original_query=query or _monitor_query(),
        category="monitor",
        category_source=FieldSource.INFERRED,
        region=RegionPreference(
            region=Region(country_code="PH", currency="PHP"),
            source=FieldSource.INFERRED,
        ),
        budget=BudgetConstraint(
            amount=Money(amount="18000", currency="PHP"),
            mode=BudgetMode.HARD_CAP,
            source=FieldSource.INFERRED,
        ),
        constraints=(
            PreferenceConstraint(
                text="27-inch size",
                mode=PreferenceMode.HARD,
                source=FieldSource.INFERRED,
            ),
            PreferenceConstraint(
                text="1440p resolution",
                mode=PreferenceMode.HARD,
                source=FieldSource.INFERRED,
            ),
        ),
        preferences=(
            PreferenceConstraint(
                text="Good for coding",
                mode=PreferenceMode.SOFT,
                source=FieldSource.INFERRED,
            ),
            PreferenceConstraint(
                text="Good for movies",
                mode=PreferenceMode.SOFT,
                source=FieldSource.INFERRED,
            ),
        ),
    )


def _input(query: str | None = None) -> IntakeAgentInput:
    return IntakeAgentInput(
        run_id=new_id(),
        request=CreateSessionRequest(query=query or _monitor_query()),
    )


@pytest.mark.asyncio
async def test_live_intake_accepts_valid_mocked_structured_output() -> None:
    runner = RecordingIntakeRunner()
    agent = LiveIntakeAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_input())

    assert result.category == "monitor"
    assert result.category_source == FieldSource.INFERRED
    assert result.region is not None
    assert result.region.region.country_code == "PH"
    assert result.budget is not None
    assert result.budget.amount.amount == Decimal("18000")
    assert result.budget.amount.currency == "PHP"
    assert result.budget.mode == BudgetMode.HARD_CAP
    assert {item.text for item in result.constraints} >= {
        "27-inch size",
        "1440p resolution",
    }
    assert {item.text for item in result.preferences} >= {
        "Good for coding",
        "Good for movies",
    }
    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "model_intake_completed"


@pytest.mark.asyncio
async def test_live_intake_preserves_ambiguous_category_uncertainty() -> None:
    runner = RecordingIntakeRunner(
        output=ShoppingBrief(
            original_query="I need something for my desk setup.",
        )
    )
    agent = LiveIntakeAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_input("I need something for my desk setup."))

    assert result.category is None
    assert result.category_source is None
    assert runner.calls == 1


@pytest.mark.asyncio
async def test_live_intake_preserves_explicit_request_controls() -> None:
    explicit_region = RegionPreference(
        region=Region(country_code="US", currency="USD"),
        source=FieldSource.USER_PROVIDED,
    )
    explicit_budget = BudgetConstraint(
        amount=Money(amount="300", currency="USD"),
        mode=BudgetMode.PREFERRED,
        source=FieldSource.USER_PROVIDED,
    )
    explicit_constraint = PreferenceConstraint(
        text="Must fit on a narrow desk.",
        mode=PreferenceMode.HARD,
        source=FieldSource.USER_PROVIDED,
    )
    runner = RecordingIntakeRunner(output=_monitor_brief())
    agent = LiveIntakeAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(
        IntakeAgentInput(
            run_id=new_id(),
            request=CreateSessionRequest(
                query="Need a monitor",
                region=explicit_region,
                budget=explicit_budget,
                constraints=(explicit_constraint,),
            ),
        )
    )

    assert result.original_query == "Need a monitor"
    assert result.region == explicit_region
    assert result.budget == explicit_budget
    assert result.constraints[0] == explicit_constraint
    assert any(item.text == "27-inch size" for item in result.constraints)


@pytest.mark.asyncio
async def test_live_intake_falls_back_on_invalid_model_output() -> None:
    runner = RecordingIntakeRunner(output={"category": "monitor"})
    agent = LiveIntakeAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_input("Need a monitor"))

    assert result == ShoppingBrief(original_query="Need a monitor")
    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "schema_invalid_fallback"


@pytest.mark.asyncio
async def test_live_intake_falls_back_on_timeout() -> None:
    runner = RecordingIntakeRunner(delay_seconds=0.02)
    agent = LiveIntakeAgent(
        settings=_settings(openai_agent_timeout_seconds=0.001),
        model_runner=runner,
    )

    result = await agent.run(_input("Need a monitor"))

    assert result == ShoppingBrief(original_query="Need a monitor")
    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "timeout_fallback"


@pytest.mark.asyncio
async def test_live_intake_falls_back_on_model_error() -> None:
    runner = RecordingIntakeRunner(error=RuntimeError("mock model failed"))
    agent = LiveIntakeAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_input("Need a monitor"))

    assert result == ShoppingBrief(original_query="Need a monitor")
    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "error_fallback"


@pytest.mark.live_provider
@pytest.mark.asyncio
async def test_live_intake_agent_live_opt_in() -> None:
    if os.getenv("CARTCART_RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("Set CARTCART_RUN_LIVE_PROVIDER_TESTS=1 to allow live calls.")

    settings = Settings(_env_file=None, live_agents_enabled=True)  # type: ignore[call-arg]
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY is not configured.")

    agent = LiveIntakeAgent(settings=settings)
    result = await agent.run(_input())

    assert result.original_query == _monitor_query()
    assert result.category is None or result.category
