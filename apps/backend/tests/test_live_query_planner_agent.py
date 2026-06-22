import asyncio
from dataclasses import dataclass
import os
from typing import Any

import pytest

from agents import Agent, RunConfig

from app.agents import (
    LiveQueryPlannerAgent,
    MockQueryPlannerModelRunner,
    QueryPlannerAgentInput,
)
from app.core.settings import Settings
from app.schemas.ids import new_id
from app.schemas.intake import (
    BudgetConstraint,
    BudgetMode,
    FieldSource,
    PreferenceConstraint,
    PreferenceMode,
    RegionPreference,
    ShoppingBrief,
)
from app.schemas.money import Money
from app.schemas.regions import Region
from app.schemas.search_sources import (
    SearchIntent,
    SearchPlan,
    SearchQuery,
    SourceType,
)


@dataclass
class RecordingQueryPlannerRunner:
    output: SearchPlan | dict[str, Any] | None = None
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
        return _RunResult(final_output=self.output or _valid_model_plan())


@dataclass
class _RunResult:
    final_output: Any


def _settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        **overrides,
    )


def _coffee_grinder_input() -> QueryPlannerAgentInput:
    return QueryPlannerAgentInput(
        run_id=new_id(),
        brief=ShoppingBrief(
            original_query="Help me choose a burr coffee grinder under $150 in the US.",
            category="coffee grinder",
            category_source=FieldSource.INFERRED,
            region=RegionPreference(
                region=Region(country_code="US", currency="USD"),
                source=FieldSource.USER_PROVIDED,
            ),
            budget=BudgetConstraint(
                amount=Money(amount="150", currency="USD"),
                mode=BudgetMode.HARD_CAP,
                source=FieldSource.USER_PROVIDED,
            ),
            preferences=(
                PreferenceConstraint(
                    text="Good for espresso and pour-over.",
                    mode=PreferenceMode.SOFT,
                    source=FieldSource.USER_PROVIDED,
                ),
            ),
        ),
    )


def _unknown_category_input() -> QueryPlannerAgentInput:
    return QueryPlannerAgentInput(
        run_id=new_id(),
        brief=ShoppingBrief(
            original_query="I need something to organize a small entryway under $75.",
            region=RegionPreference(
                region=Region(country_code="US", currency="USD"),
                source=FieldSource.USER_PROVIDED,
            ),
            budget=BudgetConstraint(
                amount=Money(amount="75", currency="USD"),
                mode=BudgetMode.HARD_CAP,
                source=FieldSource.USER_PROVIDED,
            ),
        ),
    )


def _valid_model_plan() -> SearchPlan:
    return SearchPlan(
        queries=(
            SearchQuery(
                query="coffee grinder retailers under 150",
                intent=SearchIntent.DISCOVERY,
            ),
            SearchQuery(
                query="coffee grinder reviews comparison",
                intent=SearchIntent.REVIEW,
            ),
        ),
        rationale="Check stores and reviews before extraction.",
    )


@pytest.mark.asyncio
async def test_live_query_planner_accepts_valid_mocked_structured_output() -> None:
    runner = RecordingQueryPlannerRunner()
    agent = LiveQueryPlannerAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_coffee_grinder_input())

    assert runner.calls == 1
    assert {query.intent for query in result.queries} >= {
        SearchIntent.DISCOVERY,
        SearchIntent.REVIEW,
    }
    assert all(query.region_code == "US" for query in result.queries)
    assert all(query.required_source_types for query in result.queries)
    assert any(
        SourceType.RETAILER_LISTING in query.required_source_types
        for query in result.queries
    )
    assert any(
        SourceType.PROFESSIONAL_REVIEW in query.required_source_types
        for query in result.queries
    )
    assert "coffee grinder" in " ".join(query.query for query in result.queries)
    assert agent.workbench_activity[0]["status"] == "model_query_plan_completed"
    assert agent.workbench_activity[0]["input"]["allowed_tools"] == []


@pytest.mark.asyncio
async def test_live_query_planner_falls_back_on_invalid_or_blocking_output() -> None:
    runner = RecordingQueryPlannerRunner(
        output={
            "queries": (
                {
                    "query": "unsupported category no specialist search plan",
                    "intent": "discovery",
                },
            ),
            "rationale": "No specialist exists for this category.",
        }
    )
    agent = LiveQueryPlannerAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_coffee_grinder_input())

    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "schema_invalid_fallback"
    assert _has_shopping_query(result)
    assert _has_review_query(result)
    assert all(query.region_code == "US" for query in result.queries)
    assert not _contains_artificial_blocking(result)


@pytest.mark.asyncio
async def test_live_query_planner_falls_back_on_timeout() -> None:
    runner = RecordingQueryPlannerRunner(delay_seconds=0.02)
    agent = LiveQueryPlannerAgent(
        settings=_settings(openai_agent_timeout_seconds=0.001),
        model_runner=runner,
    )

    result = await agent.run(_coffee_grinder_input())

    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "timeout_fallback"
    assert _has_shopping_query(result)
    assert _has_review_query(result)


@pytest.mark.asyncio
async def test_live_query_planner_falls_back_on_model_error() -> None:
    runner = RecordingQueryPlannerRunner(error=RuntimeError("mock model failed"))
    agent = LiveQueryPlannerAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_coffee_grinder_input())

    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "error_fallback"
    assert _has_shopping_query(result)
    assert _has_review_query(result)


@pytest.mark.asyncio
async def test_live_query_planner_supports_unknown_category_with_generic_strategy() -> None:
    runner = MockQueryPlannerModelRunner()
    agent = LiveQueryPlannerAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_unknown_category_input())

    assert runner.calls == 1
    assert _has_shopping_query(result)
    assert _has_review_query(result)
    assert all(query.region_code == "US" for query in result.queries)
    assert all(query.required_source_types for query in result.queries)
    assert "organize a small entryway" in " ".join(
        query.query for query in result.queries
    )
    assert not _contains_artificial_blocking(result)
    assert agent.workbench_activity[0]["status"] == "model_query_plan_completed"


@pytest.mark.live_provider
@pytest.mark.asyncio
async def test_live_query_planner_agent_live_opt_in() -> None:
    if os.getenv("CARTCART_RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("Set CARTCART_RUN_LIVE_PROVIDER_TESTS=1 to allow live calls.")

    settings = Settings(_env_file=None, live_agents_enabled=True)  # type: ignore[call-arg]
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY is not configured.")

    agent = LiveQueryPlannerAgent(settings=settings)
    result = await agent.run(_coffee_grinder_input())

    assert result.queries
    assert _has_shopping_query(result)
    assert _has_review_query(result)


def _has_shopping_query(plan: SearchPlan) -> bool:
    return any(
        query.intent
        in {
            SearchIntent.DISCOVERY,
            SearchIntent.PRICE_CHECK,
            SearchIntent.OFFICIAL_SOURCE,
            SearchIntent.TRUST_CHECK,
        }
        for query in plan.queries
    )


def _has_review_query(plan: SearchPlan) -> bool:
    return any(
        query.intent in {SearchIntent.REVIEW, SearchIntent.VIDEO_REVIEW}
        for query in plan.queries
    )


def _contains_artificial_blocking(plan: SearchPlan) -> bool:
    text = " ".join(
        (
            *(query.query for query in plan.queries),
            plan.rationale or "",
        )
    ).casefold()
    return any(
        phrase in text
        for phrase in (
            "unsupported category",
            "no specialist",
            "specialist-only",
            "not supported",
            "cannot plan",
            "can't plan",
        )
    )
