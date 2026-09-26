import asyncio
import json
from dataclasses import dataclass
import os
from typing import Any

import pytest

from agents import Agent, RunConfig
from agents.tool_context import ToolContext
from sqlalchemy.ext.asyncio import create_async_engine

from app.agents import (
    DiscoveryAgentInput,
    DiscoveryAgentOutcome,
    DiscoveryAgentOutput,
    DiscoveryNextAction,
    DiscoverySourceDecision,
    DiscoverySourceKind,
    LiveDiscoveryAgent,
    MockDiscoveryModelRunner,
)
from app.core.settings import Settings
from app.agents.research_tools import AgentResearchTools
from app.db.base import Base
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_session_factory
from app.providers.fakes import FakeExtractionProvider
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
from app.schemas.intake import CreateSessionRequest


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
        source_decisions=_decisions(input_data),
        selected_source_ids=(
            input_data.seed_results[0].source_id,
            input_data.seed_results[1].source_id,
        ),
        outcome=DiscoveryAgentOutcome.SELECTED,
        notes=("Select the retailer listing and review source.",),
    )


def _decisions(input_data: DiscoveryAgentInput) -> tuple[DiscoverySourceDecision, ...]:
    return tuple(
        DiscoverySourceDecision(
            source_id=result.source_id,
            classification=(
                DiscoverySourceKind.IRRELEVANT
                if index == 2
                else DiscoverySourceKind.PROFESSIONAL_REVIEW
                if index == 1
                else DiscoverySourceKind.RETAILER_LISTING
            ),
            confidence=0.9,
            reasons=("Fixture source context supports this classification.",),
            intended_treatment="Inspect" if index != 2 else "Ignore",
            next_action=(
                DiscoveryNextAction.IGNORE
                if index == 2
                else DiscoveryNextAction.RETAIN_AS_EVIDENCE
                if index == 1
                else DiscoveryNextAction.FETCH
            ),
        )
        for index, result in enumerate(input_data.seed_results)
    )


@pytest.mark.asyncio
async def test_live_discovery_accepts_valid_mocked_structured_output() -> None:
    input_data = _input()
    runner = RecordingDiscoveryRunner(
        output=DiscoveryAgentOutput(
            source_decisions=_decisions(input_data),
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
    assert len(result.source_decisions) == 3


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
    assert result.outcome == DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES
    assert result.selected_source_ids == ()


@pytest.mark.asyncio
async def test_live_discovery_falls_back_when_model_selects_ineligible_source() -> None:
    input_data = _input()
    runner = RecordingDiscoveryRunner(
        output=DiscoveryAgentOutput(
            source_decisions=tuple(
                decision.model_copy(update={"next_action": DiscoveryNextAction.FETCH})
                if decision.source_id == input_data.seed_results[2].source_id
                else decision
                for decision in _decisions(input_data)
            ),
            selected_source_ids=(input_data.seed_results[2].source_id,),
            outcome=DiscoveryAgentOutcome.SELECTED,
        )
    )
    agent = LiveDiscoveryAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "schema_invalid_fallback"
    assert input_data.seed_results[2].source_id not in result.selected_source_ids
    assert result.selected_source_ids == ()


@pytest.mark.asyncio
async def test_live_discovery_rejects_missing_or_fabricated_source_decisions() -> None:
    input_data = _input()
    partial = DiscoveryAgentOutput(
        source_decisions=_decisions(input_data)[:1],
        selected_source_ids=(input_data.seed_results[0].source_id,),
        outcome=DiscoveryAgentOutcome.SELECTED,
    )
    agent = LiveDiscoveryAgent(
        settings=_settings(), model_runner=RecordingDiscoveryRunner(output=partial)
    )
    result = await agent.run(input_data)
    assert result.outcome == DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES
    assert agent.workbench_activity[0]["status"] == "schema_invalid_fallback"

    forged = DiscoveryAgentOutput(
        source_decisions=(
            DiscoverySourceDecision(
                source_id=new_id(),
                classification=DiscoverySourceKind.RETAILER_LISTING,
                confidence=0.9,
                reasons=("Fabricated source.",),
                intended_treatment="Inspect",
                next_action=DiscoveryNextAction.FETCH,
            ),
        ),
        selected_source_ids=(),
        outcome=DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES,
    )
    agent = LiveDiscoveryAgent(
        settings=_settings(), model_runner=RecordingDiscoveryRunner(output=forged)
    )
    result = await agent.run(input_data)
    assert result.outcome == DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES
    assert agent.workbench_activity[0]["status"] == "schema_invalid_fallback"


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
    assert result.outcome == DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES
    assert len(result.selected_source_ids) == 0


@pytest.mark.asyncio
async def test_live_discovery_falls_back_on_model_error() -> None:
    runner = RecordingDiscoveryRunner(error=RuntimeError("mock model failed"))
    agent = LiveDiscoveryAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_input())

    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "error_fallback"
    assert result.outcome == DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES
    assert len(result.selected_source_ids) == 0


@pytest.mark.asyncio
async def test_live_discovery_reports_insufficient_candidates_without_product_details() -> (
    None
):
    runner = MockDiscoveryModelRunner()
    agent = LiveDiscoveryAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_no_good_input())

    assert runner.calls == 1
    assert result.outcome == DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES
    assert result.selected_source_ids == ()
    assert set(result.model_dump(mode="json")) == {
        "schema_version",
        "search_results",
        "source_decisions",
        "selected_source_ids",
        "outcome",
        "notes",
    }
    assert "product" not in result.model_dump(mode="json")


@pytest.mark.asyncio
async def test_discovery_uses_sdk_search_twice_and_classifies_generic_results() -> None:
    class TwoQuerySearchProvider:
        provider_name = "fixture-search"

        def __init__(self) -> None:
            self.queries: list[str] = []

        async def search(
            self, query: SearchQuery, options: Any = None
        ) -> tuple[SearchResult, ...]:
            self.queries.append(query.query)
            title = (
                "Best TVs review: Aurora A55"
                if len(self.queries) == 1
                else "Aurora A55 at retailer"
            )
            return (
                SearchResult(
                    query=query,
                    url=(
                        "https://reviews.example.com/best-tvs"
                        if len(self.queries) == 1
                        else "https://retailer.example.com/aurora-a55"
                    ),
                    title=title,
                    source_type=SourceType.SEARCH_RESULT,
                    provider=ProviderMetadata(provider_name=self.provider_name),
                ),
            )

    class IterativeRunner:
        async def run(
            self,
            agent: Agent[Any],
            model_input: str,
            *,
            run_config: RunConfig,
            max_turns: int,
        ) -> Any:
            del model_input, run_config
            assert max_turns >= 3
            assert agent.output_type.__name__ == "DiscoveryModelOutput"
            assert "search_results" not in agent.output_type.model_fields
            assert {tool.name for tool in agent.tools} == {
                "search_sources",
                "fetch_source",
            }
            search_tool = next(
                tool for tool in agent.tools if tool.name == "search_sources"
            )
            seen: list[dict[str, Any]] = []
            for index, query in enumerate(
                ("best TVs review", "Aurora A55 official retailer")
            ):
                response = await search_tool.on_invoke_tool(
                    ToolContext(
                        context=None,
                        tool_name="search_sources",
                        tool_call_id=f"search-{index}",
                        tool_arguments="{}",
                    ),
                    json.dumps({"query": query, "region_code": "US", "max_results": 5}),
                )
                seen.append(json.loads(response)["sources"][0])
            return _RunResult(
                final_output=DiscoveryAgentOutput(
                    source_decisions=(
                        DiscoverySourceDecision(
                            source_id=seen[0]["source_id"],
                            classification=DiscoverySourceKind.PROFESSIONAL_REVIEW,
                            confidence=0.94,
                            reasons=("Editorial comparison of named TVs.",),
                            intended_treatment="Retain review evidence",
                            candidate_model_hints=("Aurora A55",),
                            next_action=DiscoveryNextAction.RETAIN_AS_EVIDENCE,
                        ),
                        DiscoverySourceDecision(
                            source_id=seen[1]["source_id"],
                            classification=DiscoverySourceKind.RETAILER_LISTING,
                            confidence=0.88,
                            reasons=("A model-specific retailer page.",),
                            intended_treatment="Inspect listing",
                            next_action=DiscoveryNextAction.FETCH,
                        ),
                    ),
                    selected_source_ids=(seen[0]["source_id"], seen[1]["source_id"]),
                    outcome=DiscoveryAgentOutcome.SELECTED,
                )
            )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            shopping_session = await SessionRepository(session).create(
                original_input=CreateSessionRequest(query="Which TV should I buy?"),
                current_brief=_brief(),
            )
            run = await RunRepository(session).create(shopping_session.session_id)
            await session.commit()
        search_provider = TwoQuerySearchProvider()
        tools = AgentResearchTools(
            agent_name="DiscoveryAgent",
            run_id=run.run_id,
            session_factory=factory,
            search_provider=search_provider,
            extraction_provider=FakeExtractionProvider(),
        )
        agent = LiveDiscoveryAgent(
            settings=_settings(),
            model_runner=IterativeRunner(),
            research_tools_factory=lambda run_id: tools,
        )
        result = await agent.run(
            DiscoveryAgentInput(
                run_id=run.run_id,
                brief=_brief(),
                search_plan=_plan(),
            )
        )
        assert search_provider.queries == [
            "best TVs review",
            "Aurora A55 official retailer",
        ]
        assert len(result.search_results) == 2
        assert all(
            item.source_type == SourceType.SEARCH_RESULT
            for item in result.search_results
        )
        assert {item.classification for item in result.source_decisions} == {
            DiscoverySourceKind.PROFESSIONAL_REVIEW,
            DiscoverySourceKind.RETAILER_LISTING,
        }
        assert [item["tool_name"] for item in agent.workbench_activity] == [
            "search_sources",
            "search_sources",
            "openai_agents_structured_output",
        ]
        async with factory() as session:
            saved = await SearchSourceRepository(session).list_search_results(
                run.run_id
            )
            assert {item.source_id for item in saved} == set(result.selected_source_ids)
    finally:
        await engine.dispose()


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
