import asyncio
from dataclasses import dataclass
import os
from typing import Any

import pytest

from agents import Agent, RunConfig

from app.agents import (
    DiscoveryAgentInput,
    DiscoveryAgentOutcome,
    DiscoveryAgentOutput,
    LiveDiscoveryAgent,
    MockDiscoveryModelRunner,
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
    ProviderMetadata,
    SearchIntent,
    SearchPlan,
    SearchQuery,
    SearchResult,
    SourceQuality,
    SourceQualityLevel,
    SourceType,
)


@dataclass
class RecordingDiscoveryRunner:
    output: DiscoveryAgentOutput | dict[str, Any] | None = None
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
        return _RunResult(final_output=self.output or _valid_model_selection())


@dataclass
class _RunResult:
    final_output: Any


def _settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        **overrides,
    )


def _brief() -> ShoppingBrief:
    return ShoppingBrief(
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
    )


def _plan() -> SearchPlan:
    return SearchPlan(
        queries=(
            SearchQuery(
                query="coffee grinder retailers under 150 US",
                intent=SearchIntent.DISCOVERY,
                region_code="US",
                required_source_types=(SourceType.RETAILER_LISTING,),
            ),
            SearchQuery(
                query="coffee grinder reviews comparison US",
                intent=SearchIntent.REVIEW,
                region_code="US",
                required_source_types=(SourceType.PROFESSIONAL_REVIEW,),
            ),
        ),
        rationale="Check retailer listings and review evidence.",
    )


def _search_result(
    query: SearchQuery,
    *,
    url: str,
    title: str,
    source_type: SourceType,
    quality_level: SourceQualityLevel = SourceQualityLevel.ADEQUATE,
    source_class: str = "established_retailer_first_party",
    excluded: bool = False,
) -> SearchResult:
    return SearchResult(
        query=query,
        url=url,
        title=title,
        snippet="Synthetic discovery result.",
        source_type=source_type,
        provider=ProviderMetadata(
            provider_name="fixture-search",
            raw={
                "source_class": source_class,
                "excluded": excluded,
                "region_relevance": "match",
            },
        ),
        quality=SourceQuality(
            level=quality_level,
            score=0.72 if quality_level != SourceQualityLevel.WEAK else 0.1,
            rationale="Fixture quality.",
        ),
    )


def _input() -> DiscoveryAgentInput:
    plan = _plan()
    return DiscoveryAgentInput(
        run_id=new_id(),
        brief=_brief(),
        search_plan=plan,
        seed_results=(
            _search_result(
                plan.queries[0],
                url="https://www.bestbuy.com/site/coffee-grinder-fixture",
                title="Retailer coffee grinder listing",
                source_type=SourceType.RETAILER_LISTING,
                source_class="established_retailer_first_party",
            ),
            _search_result(
                plan.queries[1],
                url="https://www.nytimes.com/wirecutter/reviews/best-coffee-grinder/",
                title="Coffee grinder review roundup",
                source_type=SourceType.PROFESSIONAL_REVIEW,
                quality_level=SourceQualityLevel.STRONG,
                source_class="review_editorial",
            ),
            _search_result(
                plan.queries[0],
                url="https://buyee.jp/item/coffee-grinder-fixture",
                title="Weak proxy import listing",
                source_type=SourceType.RETAILER_LISTING,
                quality_level=SourceQualityLevel.WEAK,
                source_class="reseller_import_proxy",
                excluded=True,
            ),
        ),
    )


def _no_good_input() -> DiscoveryAgentInput:
    plan = _plan()
    return DiscoveryAgentInput(
        run_id=new_id(),
        brief=_brief(),
        search_plan=plan,
        seed_results=(
            _search_result(
                plan.queries[0],
                url="https://example-search.invalid/coffee-grinder",
                title="Generic search proxy page",
                source_type=SourceType.SEARCH_RESULT,
                quality_level=SourceQualityLevel.UNKNOWN,
                source_class="unknown",
            ),
            _search_result(
                plan.queries[0],
                url="https://buyee.jp/item/no-good-coffee-grinder",
                title="Weak proxy listing",
                source_type=SourceType.RETAILER_LISTING,
                quality_level=SourceQualityLevel.WEAK,
                source_class="reseller_import_proxy",
                excluded=True,
            ),
        ),
    )


def _valid_model_selection() -> DiscoveryAgentOutput:
    input_data = _input()
    return DiscoveryAgentOutput(
        selected_source_ids=(
            input_data.seed_results[0].source_id,
            input_data.seed_results[1].source_id,
        ),
        outcome=DiscoveryAgentOutcome.SELECTED,
        notes=("Select the retailer listing and review source.",),
    )


@pytest.mark.asyncio
async def test_live_discovery_accepts_valid_mocked_structured_output() -> None:
    input_data = _input()
    runner = RecordingDiscoveryRunner(
        output=DiscoveryAgentOutput(
            selected_source_ids=(
                input_data.seed_results[0].source_id,
                input_data.seed_results[1].source_id,
            ),
            outcome=DiscoveryAgentOutcome.SELECTED,
        )
    )
    agent = LiveDiscoveryAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result.search_results == input_data.seed_results
    assert result.outcome == DiscoveryAgentOutcome.SELECTED
    assert result.selected_source_ids == (
        input_data.seed_results[0].source_id,
        input_data.seed_results[1].source_id,
    )
    assert input_data.seed_results[2].source_id not in result.selected_source_ids
    assert agent.workbench_activity[0]["status"] == "model_discovery_completed"
    assert agent.workbench_activity[0]["input"]["allowed_tools"] == []


@pytest.mark.asyncio
async def test_live_discovery_falls_back_on_fabricated_or_malformed_output() -> None:
    input_data = _input()
    runner = RecordingDiscoveryRunner(
        output={
            "selected_source_ids": (str(input_data.seed_results[0].source_id),),
            "outcome": "selected",
            "product_name": "Made-up coffee grinder",
        }
    )
    agent = LiveDiscoveryAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "schema_invalid_fallback"
    assert result.outcome == DiscoveryAgentOutcome.SELECTED
    assert result.selected_source_ids == (
        input_data.seed_results[0].source_id,
        input_data.seed_results[1].source_id,
    )


@pytest.mark.asyncio
async def test_live_discovery_falls_back_when_model_selects_ineligible_source() -> None:
    input_data = _input()
    runner = RecordingDiscoveryRunner(
        output=DiscoveryAgentOutput(
            selected_source_ids=(input_data.seed_results[2].source_id,),
            outcome=DiscoveryAgentOutcome.SELECTED,
        )
    )
    agent = LiveDiscoveryAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "schema_invalid_fallback"
    assert input_data.seed_results[2].source_id not in result.selected_source_ids
    assert result.selected_source_ids == (
        input_data.seed_results[0].source_id,
        input_data.seed_results[1].source_id,
    )


@pytest.mark.asyncio
async def test_live_discovery_falls_back_on_timeout() -> None:
    runner = RecordingDiscoveryRunner(delay_seconds=0.02)
    agent = LiveDiscoveryAgent(
        settings=_settings(openai_agent_timeout_seconds=0.001),
        model_runner=runner,
    )

    result = await agent.run(_input())

    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "timeout_fallback"
    assert result.outcome == DiscoveryAgentOutcome.SELECTED
    assert len(result.selected_source_ids) == 2


@pytest.mark.asyncio
async def test_live_discovery_falls_back_on_model_error() -> None:
    runner = RecordingDiscoveryRunner(error=RuntimeError("mock model failed"))
    agent = LiveDiscoveryAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_input())

    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "error_fallback"
    assert result.outcome == DiscoveryAgentOutcome.SELECTED
    assert len(result.selected_source_ids) == 2


@pytest.mark.asyncio
async def test_live_discovery_reports_insufficient_candidates_without_product_details() -> None:
    runner = MockDiscoveryModelRunner()
    agent = LiveDiscoveryAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_no_good_input())

    assert runner.calls == 1
    assert result.outcome == DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES
    assert result.selected_source_ids == ()
    assert set(result.model_dump(mode="json")) == {
        "schema_version",
        "search_results",
        "selected_source_ids",
        "outcome",
        "notes",
    }
    assert "product" not in result.model_dump(mode="json")


@pytest.mark.live_provider
@pytest.mark.asyncio
async def test_live_discovery_agent_live_opt_in() -> None:
    if os.getenv("CARTCART_RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("Set CARTCART_RUN_LIVE_PROVIDER_TESTS=1 to allow live calls.")

    settings = Settings(_env_file=None, live_agents_enabled=True)  # type: ignore[call-arg]
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY is not configured.")

    result = await LiveDiscoveryAgent(settings=settings).run(_input())

    assert result.search_results
    assert result.outcome in {
        DiscoveryAgentOutcome.SELECTED,
        DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES,
    }

