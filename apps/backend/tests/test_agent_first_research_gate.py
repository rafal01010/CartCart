"""Offline gate replay for the originally observed TV research-result shape."""

import json
import os
from pathlib import Path

import httpx
import pytest
from pydantic import AnyHttpUrl

import app.db.models  # noqa: F401
from app.agents.contracts import DiscoveryAgentInput, ExtractionAgentInput
from app.agents.fixture_research import FixtureDiscoveryAgent, FixtureExtractionAgent
from app.agents.fakes import FakeQueryPlannerAgent
from app.agents.workbench import AgentWorkbenchRunRequest, AgentWorkbenchRunner
from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.repositories.source_intelligence import SourceIntelligenceRepository
from app.db.repositories.video_sources import VideoReviewRepository
from app.db.session import create_database_engine, create_session_factory
from app.orchestration.shopping_runs import (
    RepositoryShoppingRunPersistenceHooks,
    ShoppingRunOrchestrator,
)
from app.providers import (
    ExtractionProviderOptions,
    SearchProviderOptions,
    TavilySearchProvider,
)
from app.schemas.intake import CreateSessionRequest, FieldSource, ShoppingBrief
from app.schemas.search_sources import (
    ExtractedPageContent,
    ExtractionStatus,
    ProviderMetadata,
    SearchIntent,
    SearchPlan,
    SearchQuery,
    SearchResult,
    SourceSnapshot,
    SourceType,
)


class _ObservedShapeTavilyProvider:
    """Replay Tavily responses, retaining the eight originally typed reviews."""

    provider_name = "tavily"

    def __init__(self, delegate: TavilySearchProvider) -> None:
        self.delegate = delegate

    async def search(
        self, query: SearchQuery, options: SearchProviderOptions | None = None
    ) -> tuple[SearchResult, ...]:
        results = await self.delegate.search(query, options)
        if query.intent == SearchIntent.REVIEW:
            return tuple(
                item.model_copy(update={"source_type": SourceType.PROFESSIONAL_REVIEW})
                for item in results
            )
        return results


class _RecordingFixtureDiscovery:
    def __init__(self) -> None:
        self.inputs: list[DiscoveryAgentInput] = []
        self.delegate = FixtureDiscoveryAgent()

    async def run(self, input_data: DiscoveryAgentInput):
        self.inputs.append(input_data)
        return await self.delegate.run(input_data)


class _RecordingFixtureExtraction:
    def __init__(self) -> None:
        self.inputs: list[ExtractionAgentInput] = []
        self.delegate = FixtureExtractionAgent()

    async def run(self, input_data: ExtractionAgentInput):
        self.inputs.append(input_data)
        return await self.delegate.run(input_data)


class _ReadableTVPages:
    provider_name = "fixture-page"

    async def extract(
        self, url: AnyHttpUrl, options: ExtractionProviderOptions | None = None
    ) -> SourceSnapshot:
        return SourceSnapshot(
            url=url,
            source_type=options.source_type if options else SourceType.SEARCH_RESULT,
            provider=ProviderMetadata(provider_name=self.provider_name),
            extraction_status=ExtractionStatus.SUCCEEDED,
            extracted_content=ExtractedPageContent(
                text=f"Readable TV source at {url}; no verified item-level offer in fixture.",
                extractor="fixture",
                word_count=12,
            ),
        )


def _observed_response(query: str) -> dict[str, object]:
    if query == "TV reviews":
        group, count = "reviews", 8
    elif query == "TV shopping first":
        group, count = "shopping-first", 9
    else:
        assert query == "TV shopping second"
        group, count = "shopping-second", 9
    return {
        "request_id": f"observed-{group}",
        "query": query,
        "results": [
            {
                "title": (
                    f"Best TVs review {index}: Aurora A55 and Northstar N65"
                    if group == "reviews"
                    else f"TV shopping result {group}-{index}"
                ),
                "url": f"https://{group}.example.com/tv-{index}",
                "content": "TV source result; details require page interpretation.",
            }
            for index in range(count)
        ],
    }


@pytest.mark.asyncio
async def test_observed_tv_tavily_shape_ends_with_honest_insufficient_evidence(
    tmp_path: Path,
) -> None:
    """Eight reviews plus eighteen generic results must never become monitors."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_observed_response(json.loads(request.content)["query"])
        )

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "observed-tv-shape.sqlite3",
    )
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        brief = ShoppingBrief(
            original_query="Which TV should I buy?",
            category="tv",
            category_source=FieldSource.INFERRED,
        )
        async with factory() as session:
            shopping_session = await SessionRepository(session).create(
                original_input=CreateSessionRequest(query=brief.original_query),
                current_brief=brief,
            )
            run = await RunRepository(session).create(shopping_session.session_id)
            await session.commit()

        plan = SearchPlan(
            queries=(
                SearchQuery(query="TV reviews", intent=SearchIntent.REVIEW),
                SearchQuery(query="TV shopping first", intent=SearchIntent.DISCOVERY),
                SearchQuery(query="TV shopping second", intent=SearchIntent.DISCOVERY),
            )
        )
        discovery = _RecordingFixtureDiscovery()
        extraction = _RecordingFixtureExtraction()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = _ObservedShapeTavilyProvider(
                TavilySearchProvider(api_key="synthetic-gate-key", client=client)
            )
            async with factory() as session:
                context = await ShoppingRunOrchestrator(
                    RepositoryShoppingRunPersistenceHooks(
                        run_repository=RunRepository(session),
                        result_repository=ResultRepository(session),
                        search_source_repository=SearchSourceRepository(session),
                        product_repository=ProductRepository(session),
                        source_intelligence_repository=SourceIntelligenceRepository(
                            session
                        ),
                        video_review_repository=VideoReviewRepository(session),
                    ),
                    query_planner=FakeQueryPlannerAgent(output=plan),
                    discovery_agent=discovery,
                    extraction_agent=extraction,
                    search_provider=provider,
                    extraction_provider=_ReadableTVPages(),
                ).run(run.run_id, brief)
                await session.commit()

        async with factory() as session:
            stored_results = await SearchSourceRepository(session).list_search_results(
                run.run_id
            )
            stored_snapshots = await SearchSourceRepository(
                session
            ).list_source_snapshots(run.run_id)
            products = await ProductRepository(session).list_canonical_products_for_run(
                run.run_id
            )
            result = await ResultRepository(session).load_latest_result_bundle(
                run.run_id
            )

        assert len(discovery.inputs) == 1
        assert len(discovery.inputs[0].seed_results) == len(stored_results) == 26
        assert (
            sum(
                item.source_type == SourceType.PROFESSIONAL_REVIEW
                for item in stored_results
            )
            == 8
        )
        generic = [
            item
            for item in discovery.inputs[0].seed_results
            if item.source_type == SourceType.SEARCH_RESULT
        ]
        assert len(generic) == 18
        assert all(item.provider.provider_name == "tavily" for item in generic)
        assert len(extraction.inputs) == 12
        snapshot_ids = {item.source_id for item in stored_snapshots}
        assert all(
            input_data.snapshot_ids[0] in snapshot_ids
            for input_data in extraction.inputs
        )
        assert any(
            item.source_type == SourceType.SEARCH_RESULT
            for item in context.search_results
            if item.source_id in context.selected_source_ids
        )
        assert products == ()
        assert result is not None
        assert result.recommendation_bundle.no_strong_buy
        assert result.recommendation_bundle.final_product_id is None
        assert result.comparison_matrix.rows == ()
        assert not any("monitor" in item.name.casefold() for item in products)
        assert context.fixture_output is None
    finally:
        await engine.dispose()


@pytest.mark.live_provider
@pytest.mark.asyncio
async def test_tv_research_workbench_live_opt_in() -> None:
    """Optional model smoke; never run in the ordinary offline gate."""

    if os.getenv("CARTCART_RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("Set CARTCART_RUN_LIVE_PROVIDER_TESTS=1 to allow live calls.")
    settings = Settings(
        environment="test",
        agent_workbench_enabled=True,
        live_agents_enabled=True,
    )
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY is not configured.")
    result = await AgentWorkbenchRunner(settings).run(
        AgentWorkbenchRunRequest(
            agent_name="DiscoveryAgent",
            scenario_name="discovery/tv-review-and-generic-results",
            mode="live",
        )
    )
    assert result.output is not None
    inspected = {item["source_id"] for item in result.input["seed_results"]}
    decisions = result.output["source_decisions"]
    assert {item["source_id"] for item in decisions} == inspected
    assert set(result.output["selected_source_ids"]) <= inspected
