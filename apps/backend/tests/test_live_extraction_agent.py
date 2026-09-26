import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.agents.contracts import ExtractionAgentInput, ExtractionAgentOutput
from app.agents.extraction_tools import SnapshotInterpretationTools
from app.agents.workbench import AgentWorkbenchRunRequest, AgentWorkbenchRunner
from app.core.settings import AgentWorkflowMode, Settings
from app.db.base import Base
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.repositories.runs import RunRepository
from app.db.session import create_session_factory
from app.orchestration.shopping_runs import (
    RepositoryShoppingRunPersistenceHooks,
    ShoppingRunContext,
    ShoppingRunOrchestrator,
)
from app.schemas.intake import CreateSessionRequest, FieldSource, ShoppingBrief
from app.schemas.ids import new_id
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.schemas.search_sources import (
    ExtractedPageContent,
    ExtractionStatus,
    ProviderMetadata,
    SearchIntent,
    SearchQuery,
    SearchResult,
    SourceSnapshot,
    SourceType,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "products", "listings", "gap"),
    [
        ("extraction-agent/individual-product-page", 1, 1, False),
        ("extraction-agent/ambiguous-page", 0, 0, True),
        ("extraction-agent/malformed-output", 0, 0, True),
        ("extraction-agent/multiple-products", 2, 2, False),
    ],
)
async def test_extraction_workbench_mock_scenarios(
    scenario: str, products: int, listings: int, gap: bool
) -> None:
    runner = AgentWorkbenchRunner(
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            environment="test",
            agent_workbench_enabled=True,
        )
    )
    result = await runner.run(
        AgentWorkbenchRunRequest(
            agent_name="ExtractionAgent", scenario_name=scenario, mode="mock"
        )
    )
    assert result.error is None
    assert result.output is not None
    assert len(result.output["products"]) == products
    assert len(result.output["listings"]) == listings
    assert bool(result.output["evidence_gaps"]) is gap
    assert any(
        item.tool_name == "read_source_snapshot"
        for item in result.allowed_tool_activity
    )
    for product in result.output["products"]:
        assert product["source_ids"]
    for listing in result.output["listings"]:
        assert listing["source_ids"]
        assert listing["product_id"] in {
            product["product_id"] for product in result.output["products"]
        }


class _MultiProductExtractionAgent:
    async def run(self, input_data: ExtractionAgentInput) -> ExtractionAgentOutput:
        source_id = input_data.snapshot_ids[0]
        products = tuple(
            CanonicalProduct(name=f"TV {index}", source_ids=(source_id,))
            for index in (1, 2)
        )
        listings = tuple(
            ProductListing(
                product_id=product.product_id,
                title=product.name,
                url=f"https://shop.example/tv-{index}",
                seller=SellerProfile(
                    seller_name="Example Shop", source_ids=(source_id,)
                ),
                source_ids=(source_id,),
            )
            for index, product in enumerate(products, start=1)
        )
        return ExtractionAgentOutput(products=products, listings=listings)


class _CollectionProvider:
    async def extract(self, url: object, options: object) -> SourceSnapshot:
        del options
        return SourceSnapshot(
            url=url,
            source_type=SourceType.SEARCH_RESULT,
            provider=ProviderMetadata(provider_name="fixture"),
            extraction_status=ExtractionStatus.SUCCEEDED,
            extracted_content=ExtractedPageContent(
                text="TV 1 https://shop.example/tv-1 TV 2 https://shop.example/tv-2",
                extractor="fixture",
                word_count=5,
            ),
        )


@pytest.mark.asyncio
async def test_live_extraction_stage_uses_agent_for_two_listings_from_generic_page() -> (
    None
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            brief = ShoppingBrief(
                original_query="Which TV should I buy?",
                category="tv",
                category_source=FieldSource.INFERRED,
            )
            shopping_session = await SessionRepository(session).create(
                original_input=CreateSessionRequest(query=brief.original_query),
                current_brief=brief,
            )
            run = await RunRepository(session).create(shopping_session.session_id)
            result = SearchResult(
                query=SearchQuery(query="TVs", intent=SearchIntent.DISCOVERY),
                url="https://shop.example/tvs",
                title="TV collection",
                source_type=SourceType.SEARCH_RESULT,
                provider=ProviderMetadata(provider_name="fixture"),
            )
            await SearchSourceRepository(session).add_search_result(run.run_id, result)
            await session.commit()
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(session),
                    result_repository=ResultRepository(session),
                    search_source_repository=SearchSourceRepository(session),
                    product_repository=ProductRepository(session),
                ),
                agent_workflow_mode=AgentWorkflowMode.LIVE,
                extraction_agent=_MultiProductExtractionAgent(),
                extraction_provider=_CollectionProvider(),
            )
            context = ShoppingRunContext(
                run_id=run.run_id,
                session_id=shopping_session.session_id,
                trace_id="test-trace",
                active_brief=brief,
                search_results=(result,),
                selected_source_ids=(result.source_id,),
            )
            stage = await orchestrator._extract_sources(context)
            assert stage.agent_name == "ExtractionAgent"
            assert len(context.source_extractions) == 2
            assert all(
                item.listing_extraction is not None
                for item in context.source_extractions
            )
            assert (
                len(
                    await SearchSourceRepository(session).list_source_snapshots(
                        run.run_id
                    )
                )
                == 1
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_snapshot_tool_requires_assigned_same_run_id_and_bounds_text() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            brief = ShoppingBrief(original_query="Find a TV")
            shopping_session = await SessionRepository(session).create(
                original_input=CreateSessionRequest(query=brief.original_query),
                current_brief=brief,
            )
            run = await RunRepository(session).create(shopping_session.session_id)
            other_run = await RunRepository(session).create(shopping_session.session_id)
            snapshot = SourceSnapshot(
                url="https://shop.example/tvs",
                source_type=SourceType.SEARCH_RESULT,
                provider=ProviderMetadata(provider_name="fixture"),
                extraction_status=ExtractionStatus.SUCCEEDED,
                extracted_content=ExtractedPageContent(
                    text="TV collection with many products and prices",
                    extractor="fixture",
                    word_count=7,
                ),
            )
            await SearchSourceRepository(session).add_source_snapshot(
                run.run_id, snapshot
            )
            await session.commit()
            tools = SnapshotInterpretationTools(
                run_id=run.run_id,
                allowed_snapshot_ids=(snapshot.source_id,),
                shared_session=session,
                max_reads=1,
                max_text_chars=10,
            )
            assert (await tools.read(str(new_id()))).status == "unknown_snapshot"
            fetched = await tools.read(str(snapshot.source_id))
            assert fetched.status == "succeeded"
            assert fetched.text == "TV collect"
            assert fetched.text_truncated
            assert (
                await tools.read(str(snapshot.source_id))
            ).status == "budget_exhausted"
            wrong_run_tools = SnapshotInterpretationTools(
                run_id=other_run.run_id,
                allowed_snapshot_ids=(snapshot.source_id,),
                shared_session=session,
            )
            assert (
                await wrong_run_tools.read(str(snapshot.source_id))
            ).status == "unknown_snapshot"
    finally:
        await engine.dispose()
