import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agents import Agent, FunctionTool
from agents.tool_context import ToolContext
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.util.concurrency import await_only

from app.agents.contracts import GeneralShoppingAgentInput
from app.agents.hosted_web_search import HostedWebCitation
from app.agents.live_general_shopping import (
    GeneralModelOutput,
    LiveGeneralShoppingAgent,
)
from app.agents.live_source_intelligence_manager import (
    SourceManagerInput,
    SourceManagerResult,
)
from app.core.settings import AgentWorkflowMode, Settings
from app.db.base import Base
from app.db.repositories.products import ProductRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_database_engine, create_session_factory
from app.providers.contracts import (
    SearchProviderOptions,
    SourceAllowAvoidPolicy,
    SourcePolicyAction,
    SourcePolicyRule,
)
from app.providers.fakes import FakeExtractionProvider
from app.schemas.ids import SourceId, new_id
from app.schemas.intake import (
    CreateSessionRequest,
    FieldSource,
    RegionPreference,
    ShoppingBrief,
)
from app.schemas.money import Money
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.schemas.regions import Region
from app.schemas.search_sources import (
    ExtractedPageContent,
    ExtractionStatus,
    ProviderMetadata,
    SearchQuery,
    SearchResult,
    SourceSnapshot,
    SourceType,
)
from app.services.runs import RunService


class _SearchProvider:
    provider_name = "fixture-concurrency"

    def __init__(self) -> None:
        self.regions: list[str | None] = []

    async def search(
        self, query: SearchQuery, options: SearchProviderOptions | None = None
    ) -> tuple[SearchResult, ...]:
        assert options is not None
        self.regions.append(options.region_code)
        return (
            SearchResult(
                query=query,
                url=f"https://example.com/cane-{len(self.regions)}",
                title="Oak walking cane",
                source_type=SourceType.PRODUCT_PAGE,
                provider=ProviderMetadata(provider_name=self.provider_name),
            ),
        )


async def _invoke(agent: Agent[Any], name: str, **arguments: Any) -> dict[str, Any]:
    tool = next(
        item
        for item in agent.tools
        if isinstance(item, FunctionTool) and item.name == name
    )
    payload = json.dumps(arguments)
    result = await tool.on_invoke_tool(
        ToolContext(
            context=None,
            tool_name=name,
            tool_call_id=f"offline-{name}",
            tool_arguments=payload,
        ),
        payload,
    )
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return {"tool_error": result}


async def _overlap_commit(
    session: AsyncSession,
    write: Callable[[], Awaitable[Any]],
    read: Callable[[], Awaitable[Any]],
) -> tuple[Any, Any]:
    committed = asyncio.Event()
    release = asyncio.Event()

    def pause_commit(_: Any) -> None:
        committed.set()
        await_only(release.wait())

    event.listen(session.sync_session, "after_commit", pause_commit)
    writer = asyncio.create_task(write())
    reader = None
    try:
        await asyncio.wait_for(committed.wait(), timeout=2)
        reader = asyncio.create_task(read())
        await asyncio.sleep(0)
        release.set()
        values = await asyncio.wait_for(asyncio.gather(writer, reader), timeout=2)
        return values[0], values[1]
    finally:
        release.set()
        event.remove(session.sync_session, "after_commit", pause_commit)
        for task in (writer, reader):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (writer, reader) if task is not None),
            return_exceptions=True,
        )


class _Runner:
    def __init__(self, exercise: Callable[[Agent[Any]], Awaitable[None]]) -> None:
        self.exercise = exercise

    async def run(self, agent: Agent[Any], model_input: str, **kwargs: Any) -> Any:
        del model_input, kwargs
        await self.exercise(agent)
        return SimpleNamespace(
            final_output=GeneralModelOutput(
                rationale="There is not enough checked evidence to choose a product yet.",
                category="walking cane",
            ),
            raw_responses=(),
        )


@asynccontextmanager
async def _normal_owner(tmp_path: Path) -> AsyncIterator[Any]:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_path=tmp_path / "owner-concurrency.sqlite3",
        agent_workflow_mode=AgentWorkflowMode.LIVE,
        live_agents_enabled=True,
        openai_api_key="fixture-only-key",
        openai_model="gpt-6-sol",
    )
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            brief = ShoppingBrief(
                original_query="Find a wooden walking cane",
                region=RegionPreference(
                    region=Region(country_code="PH", currency="PHP"),
                    source=FieldSource.USER_PROVIDED,
                ),
            )
            shopping = await SessionRepository(session).create(
                original_input=CreateSessionRequest(query=brief.original_query),
                current_brief=brief,
            )
            run = await RunRepository(session).create(shopping.session_id)
            product = await ProductRepository(session).add_canonical_product(
                run.run_id,
                CanonicalProduct(name="Oak walking cane", category="walking cane"),
            )
            listing = await ProductRepository(session).add_product_listing(
                run.run_id,
                ProductListing(
                    product_id=product.product_id,
                    title=product.name,
                    url="https://example.com/cane-listing",
                    seller=SellerProfile(seller_name="Cane Shop"),
                    price=Money(amount="1200", currency="PHP"),
                    source_ids=(new_id(),),
                ),
            )
            await session.commit()
            provider = _SearchProvider()
            service = RunService(
                session_repository=SessionRepository(session),
                run_repository=RunRepository(session),
                search_source_repository=SearchSourceRepository(session),
                search_provider=provider,
                extraction_provider=FakeExtractionProvider(
                    snapshot=SourceSnapshot(
                        url="https://example.com/cane-1",
                        source_type=SourceType.PRODUCT_PAGE,
                        provider=ProviderMetadata(provider_name="fixture-extraction"),
                        extraction_status=ExtractionStatus.SUCCEEDED,
                        extracted_content=ExtractedPageContent(
                            text="Oak walking cane has a comfortable handle.",
                            extractor="fixture",
                            word_count=9,
                        ),
                    )
                ),
                settings=settings,
            )
            owner = service._live_agent_kwargs()["general_shopping_agent"]
            assert isinstance(owner, LiveGeneralShoppingAgent)
            yield owner, session, factory, run.run_id, brief, listing, provider
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize("helper", ["read_run_evidence", "check_listing_trust"])
async def test_normal_owner_sdk_tools_share_session_safely(
    tmp_path: Path, parallel: bool, helper: str
) -> None:
    async with _normal_owner(tmp_path) as state:
        owner, session, factory, run_id, brief, listing, provider = state
        results: dict[str, Any] = {}

        async def exercise(agent: Agent[Any]) -> None:
            initial = await _invoke(
                agent, "search_sources", query="wooden cane", max_results=1
            )
            results["initial"] = initial
            source_id = initial["sources"][0]["source_id"]
            results["fetched"] = await _invoke(
                agent, "fetch_source", source_id=source_id
            )
            results["quote"] = await _invoke(
                agent,
                "record_source_quote",
                source_id=source_id,
                quote="Oak walking cane has a comfortable handle.",
            )

            async def write() -> dict[str, Any]:
                return await _invoke(
                    agent, "search_sources", query="cane review", max_results=1
                )

            async def read() -> dict[str, Any]:
                arguments = (
                    {"source_id": source_id}
                    if helper == "read_run_evidence"
                    else {"listing_id": str(listing.listing_id)}
                )
                return await _invoke(agent, helper, **arguments)

            if parallel:
                results["search"], results["helper"] = await _overlap_commit(
                    session, write, read
                )
            else:
                results["search"] = await write()
                results["helper"] = await read()
            results["wrong_region"] = await _invoke(
                agent,
                "search_sources",
                query="cane in another region",
                region_code="US",
            )

        owner.model_runner = _Runner(exercise)
        await asyncio.wait_for(
            owner.run(GeneralShoppingAgentInput(run_id=run_id, brief=brief)), 5
        )
        assert results["initial"]["status"] == "succeeded"
        assert (
            results["fetched"]["text"] == "Oak walking cane has a comfortable handle."
        )
        assert results["quote"]["status"] == "succeeded"
        assert results["search"]["status"] == "succeeded"
        assert results["helper"].get("status") == "succeeded", results["helper"]
        assert results["wrong_region"]["status"] == "invalid_request"
        assert provider.regions == ["PH", "PH"]
        if helper == "read_run_evidence":
            assert results["helper"]["evidence"] == [
                {
                    "evidence_id": results["quote"]["evidence_id"],
                    "quote": "Oak walking cane has a comfortable handle.",
                    "source_id": results["fetched"]["snapshot_id"],
                }
            ]
        else:
            assert results["helper"]["listing_id"] == str(listing.listing_id)
            assert results["helper"]["level"] == "unknown"
        async with factory() as fresh:
            repo = SearchSourceRepository(fresh)
            for result in (results["initial"], results["search"]):
                saved = await repo.get_search_result_for_run(
                    run_id, SourceId(result["sources"][0]["source_id"])
                )
                assert saved is not None
                assert saved.title == "Oak walking cane"
                assert saved.query.region_code == "PH"
            evidence = await repo.list_source_evidence(run_id)
            assert [item.claim for item in evidence] == [
                "Oak walking cane has a comfortable handle."
            ]


@pytest.mark.asyncio
async def test_normal_owner_hosted_citation_commit_can_overlap_evidence_read(
    tmp_path: Path,
) -> None:
    async with _normal_owner(tmp_path) as state:
        owner, session, factory, run_id, brief, _, _ = state
        manager = owner.source_intelligence_manager
        assert manager is not None and manager.citation_store_factory is not None
        store = manager.citation_store_factory(run_id)
        results: dict[str, Any] = {}
        policy = SourceAllowAvoidPolicy(
            avoid=(
                SourcePolicyRule(
                    action=SourcePolicyAction.AVOID,
                    domain="blocked.example",
                    reason="Excluded fixture source",
                ),
            )
        )

        async def exercise(agent: Agent[Any]) -> None:
            initial = await _invoke(
                agent, "search_sources", query="wooden cane", max_results=1
            )

            async def write() -> Any:
                return await store.persist(
                    agent_name="YouTubeReviewIntelligenceAgent",
                    citations=(
                        HostedWebCitation(
                            url="https://example.com/cane-review?utm_source=fixture",
                            title="Cane review",
                            cited_text="A cited cane review, not a verified claim.",
                            call_id="fixture-hosted-call",
                        ),
                        HostedWebCitation(
                            url="https://blocked.example/cane",
                            title="Excluded cane review",
                            cited_text="Excluded fixture text",
                            call_id="fixture-blocked-call",
                        ),
                    ),
                    query="wooden cane video review",
                    region_code="PH",
                    source_policy=policy,
                )

            async def read() -> dict[str, Any]:
                return await _invoke(
                    agent,
                    "read_run_evidence",
                    source_id=initial["sources"][0]["source_id"],
                )

            results["citations"], results["read"] = await _overlap_commit(
                session, write, read
            )

        owner.model_runner = _Runner(exercise)
        await asyncio.wait_for(
            owner.run(GeneralShoppingAgentInput(run_id=run_id, brief=brief)), 5
        )
        assert results["read"].get("status") == "succeeded", results["read"]
        citations, decisions = results["citations"]
        assert decisions == (
            ("https://example.com/cane-review", "retained"),
            ("https://blocked.example/cane", "source_rejected"),
        )
        assert [item.url for item in citations] == ["https://example.com/cane-review"]
        async with factory() as fresh:
            repo = SearchSourceRepository(fresh)
            saved = await repo.get_search_result_for_run(run_id, citations[0].source_id)
            assert saved is not None
            assert saved.query.region_code == "PH"
            assert saved.quality.level.value == "weak"
            evidence = await repo.list_source_evidence(run_id)
            assert [(str(item.evidence_id), item.claim) for item in evidence] == [
                (
                    str(citations[0].evidence_id),
                    "A cited cane review, not a verified claim.",
                )
            ]


@pytest.mark.asyncio
async def test_normal_owner_nested_source_citation_persistence_does_not_deadlock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _normal_owner(tmp_path) as state:
        owner, _, factory, run_id, brief, listing, _ = state
        manager = owner.source_intelligence_manager
        assert manager is not None and manager.citation_store_factory is not None
        store = manager.citation_store_factory(run_id)
        results: dict[str, Any] = {}

        async def nested_source(request: SourceManagerInput) -> SourceManagerResult:
            results["region"] = request.region_code
            results["product"] = request.products[0].name
            results["citations"], _ = await store.persist(
                agent_name="YouTubeReviewIntelligenceAgent",
                citations=(
                    HostedWebCitation(
                        url="https://example.com/nested-cane-review",
                        title="Nested cane review",
                        cited_text="A nested fixture citation; verified video evidence is unavailable.",
                        call_id="fixture-nested-call",
                    ),
                ),
                query=request.products[0].name,
                region_code=request.region_code,
                source_policy=SourceAllowAvoidPolicy(),
            )
            return SourceManagerResult(
                notes=("No verified fixture video evidence is available.",)
            )

        monkeypatch.setattr(manager, "run", nested_source)

        async def exercise(agent: Agent[Any]) -> None:
            results["consult"] = await _invoke(
                agent,
                "consult_source_intelligence",
                capability="video_review",
                product_id=str(listing.product_id),
            )
            results["trust"] = await _invoke(
                agent, "check_listing_trust", listing_id=str(listing.listing_id)
            )

        owner.model_runner = _Runner(exercise)
        await asyncio.wait_for(
            owner.run(GeneralShoppingAgentInput(run_id=run_id, brief=brief)), 5
        )
        assert results["consult"]["status"] == "gap"
        assert results["consult"]["notes"] == [
            "No verified fixture video evidence is available."
        ]
        assert results["trust"]["status"] == "succeeded"
        assert results["region"] == "PH"
        assert results["product"] == "Oak walking cane"
        async with factory() as fresh:
            saved = await SearchSourceRepository(fresh).get_search_result_for_run(
                run_id,
                results["citations"][0].source_id,
            )
            assert saved is not None
            assert str(saved.url) == "https://example.com/nested-cane-review"
