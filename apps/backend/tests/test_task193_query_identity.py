import json
from pathlib import Path

import pytest
from agents.tool_context import ToolContext
from pydantic import AnyHttpUrl

from app.agents.contracts import (
    DiscoveryAgentInput,
    ExtractionAgentInput,
    ExtractionAgentOutput,
)
from app.agents.extraction_tools import SnapshotInterpretationTools
from app.agents.live_discovery import _model_input
from app.agents.live_extraction import LiveExtractionAgent, MockExtractionModelRunner
from app.agents.research_tools import AgentResearchTools, FetchSourceRequest
from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.products import ProductRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_database_engine, create_session_factory
from app.providers.outbound_urls import neutral_outbound_url
from app.schemas.ids import SourceId
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
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


_ITEM = "https://shop.example.com/product?sku=A55"


class _Provider:
    provider_name = "query-fixture"

    def __init__(self, source: SearchResult):
        self.source = source
        self.fetched: list[str] = []

    async def search(self, query, options):
        return (self.source,)

    async def extract(self, url: AnyHttpUrl, options):
        self.fetched.append(str(url))
        return _snapshot(str(url))


def _snapshot(url: str) -> SourceSnapshot:
    return SourceSnapshot(
        url=url,
        source_type=SourceType.PRODUCT_PAGE,
        provider=ProviderMetadata(provider_name="query-fixture"),
        extraction_status=ExtractionStatus.SUCCEEDED,
        extracted_content=ExtractedPageContent(
            text=(
                "A55 desk lamp sold by Example Store. "
                "Navigation https://shop.example.com/product "
                "Other model https://shop.example.com/product?sku=A56 "
                "Separate offer https://shop.example.com/offers/lamp?sku=A55"
            ),
            extractor="fixture",
            word_count=18,
        ),
    )


def _source(url: str) -> SearchResult:
    return SearchResult(
        url=url,
        title="A55 desk lamp",
        query=SearchQuery(query="desk lamp", intent=SearchIntent.DISCOVERY),
        provider=ProviderMetadata(provider_name="query-fixture"),
        source_type=SourceType.PRODUCT_PAGE,
    )


async def _database(tmp_path: Path):
    engine = create_database_engine(
        Settings(_env_file=None, database_path=tmp_path / "query.sqlite3")
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        brief = ShoppingBrief(original_query="Find a desk lamp")
        shopping_session = await SessionRepository(session).create(
            original_input=CreateSessionRequest(query=brief.original_query),
            current_brief=brief,
        )
        run = await RunRepository(session).create(shopping_session.session_id)
        other = await RunRepository(session).create(shopping_session.session_id)
        await session.commit()
    return engine, factory, run.run_id, other.run_id


async def _invoke(tool, **arguments):
    return json.loads(
        await tool.on_invoke_tool(
            ToolContext(
                context=None,
                tool_name=tool.name,
                tool_call_id=f"fixture-{tool.name}",
                tool_arguments=json.dumps(arguments),
            ),
            json.dumps(arguments),
        )
    )


def _output(source_id: SourceId, url: str) -> ExtractionAgentOutput:
    product = CanonicalProduct(name="A55 desk lamp", source_ids=(source_id,))
    listing = ProductListing(
        product_id=product.product_id,
        title=product.name,
        url=url,
        seller=SellerProfile(seller_name="Example Store", source_ids=(source_id,)),
        source_ids=(source_id,),
    )
    return ExtractionAgentOutput(products=(product,), listings=(listing,))


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (_ITEM + "&utm_source=search&tag=affiliate#details", _ITEM),
        (_ITEM + "&token=private", _ITEM),
        (
            "https://shop.example.com/lamp?utm_source=search",
            "https://shop.example.com/lamp",
        ),
        (
            "https://shop.example.com/lamp?variant=256",
            "https://shop.example.com/lamp?variant=256",
        ),
        (
            "https://www.youtube.com/watch?v=review_A55&utm_source=search",
            "https://www.youtube.com/watch?v=review_A55",
        ),
        ("https://user:secret@shop.example.com/lamp", None),
        ("https://shop.example.com/product?configuration=A55", None),
        (_ITEM + "&unrecognized=private", None),
    ],
)
def test_neutral_destination_keeps_supported_identity_and_withholds_unknowns(
    url, expected
):
    assert neutral_outbound_url(url) == expected


@pytest.mark.asyncio
async def test_sdk_search_fetch_read_and_extraction_preserve_query_offer(tmp_path):
    engine, factory, run_id, other_run_id = await _database(tmp_path)
    source = _source(_ITEM + "&utm_source=search&tag=affiliate&token=private#details")
    provider = _Provider(source)
    tools = AgentResearchTools(
        agent_name="GeneralShoppingAgent",
        run_id=run_id,
        session_factory=factory,
        search_provider=provider,
        extraction_provider=provider,
    )
    sdk = {tool.name: tool for tool in tools.sdk_tools()}
    try:
        searched = await _invoke(sdk["search_sources"], query="desk lamp")
        assert searched["sources"][0]["url"] == _ITEM
        assert searched["sources"][0]["source_id"] == str(source.source_id)
        fetched = await _invoke(sdk["fetch_source"], source_id=str(source.source_id))
        assert fetched["status"] == "succeeded"
        assert fetched["url"] == _ITEM
        assert provider.fetched == [_ITEM]
        snapshot_id = SourceId(fetched["snapshot_id"])
        assert snapshot_id != source.source_id
        reader = SnapshotInterpretationTools(
            run_id=run_id, allowed_snapshot_ids=(snapshot_id,), session_factory=factory
        )
        read = await _invoke(reader.sdk_tools()[0], snapshot_id=str(snapshot_id))
        assert read["url"] == _ITEM
        assert read["snapshot_id"] == str(snapshot_id)
        discovery = DiscoveryAgentInput(
            run_id=run_id,
            brief=ShoppingBrief(original_query="desk lamp"),
            search_plan=SearchPlan(queries=(source.query,)),
            seed_results=(source,),
        )
        assert json.loads(_model_input(discovery))["search_results"][0]["url"] == _ITEM
        output = _output(snapshot_id, _ITEM)
        agent = LiveExtractionAgent(
            settings=Settings(_env_file=None, environment="test"),
            snapshot_tools_factory=lambda request: SnapshotInterpretationTools(
                run_id=request.run_id,
                allowed_snapshot_ids=request.snapshot_ids,
                session_factory=factory,
            ),
            model_runner=MockExtractionModelRunner(output),
        )
        accepted = await agent.run(
            ExtractionAgentInput(run_id=run_id, snapshot_ids=(snapshot_id,))
        )
        assert accepted.listings == output.listings
        async with factory() as session:
            products = ProductRepository(session)
            await products.add_canonical_product(run_id, accepted.products[0])
            await products.add_product_listing(run_id, accepted.listings[0])
            await session.commit()
        async with factory() as session:
            repository = SearchSourceRepository(session)
            saved_source = await repository.get_search_result_for_run(
                run_id, source.source_id
            )
            assert str(saved_source.url) == _ITEM
            persisted = await repository.get_snapshot_for_search_result(
                run_id, source.source_id
            )
            assert persisted.source_id == snapshot_id
            assert str(persisted.url) == _ITEM
            listings = await ProductRepository(session).list_product_listings_for_run(
                run_id
            )
            assert str(listings[0].url) == _ITEM
            assert listings[0].source_ids == (snapshot_id,)
            assert (
                await repository.get_source_snapshot_for_run(other_run_id, snapshot_id)
                is None
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("inspected", "proposed", "accepted"),
    [
        (_ITEM, _ITEM, True),
        (_ITEM, "https://shop.example.com/product", False),
        (_ITEM, "https://shop.example.com/product?sku=A56", False),
        (_ITEM, "https://shop.example.com/offers/lamp?sku=A55", True),
        (
            "https://shop.example.com/lamp?utm_source=search&tag=affiliate",
            "https://shop.example.com/lamp",
            True,
        ),
        (
            "https://shop.example.com/product?configuration=A55",
            "https://shop.example.com/product",
            False,
        ),
        (
            "https://user:secret@shop.example.com/product",
            "https://shop.example.com/product",
            False,
        ),
        (_ITEM, _ITEM + "&tag=affiliate", False),
    ],
)
async def test_public_extraction_preserves_inspected_identity(
    tmp_path, inspected, proposed, accepted
):
    engine, factory, run_id, _ = await _database(tmp_path)
    snapshot = _snapshot(inspected)
    try:
        async with factory() as session:
            await SearchSourceRepository(session).add_source_snapshot(run_id, snapshot)
            await session.commit()
        output = _output(snapshot.source_id, proposed)
        agent = LiveExtractionAgent(
            settings=Settings(_env_file=None, environment="test"),
            snapshot_tools_factory=lambda request: SnapshotInterpretationTools(
                run_id=run_id,
                allowed_snapshot_ids=request.snapshot_ids,
                session_factory=factory,
            ),
            model_runner=MockExtractionModelRunner(output),
        )
        result = await agent.run(
            ExtractionAgentInput(run_id=run_id, snapshot_ids=(snapshot.source_id,))
        )
        if accepted:
            assert str(result.listings[0].url) == proposed
            assert result.listings[0].source_ids == (snapshot.source_id,)
        else:
            assert result.listings == ()
            assert result.evidence_gaps[0].source_id == snapshot.source_id
            assert (
                result.evidence_gaps[0].summary
                == "Agent extraction was invalid or timed out."
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@shop.example.com/product?sku=A55",
        "https://shop.example.com/product?configuration=A55",
    ],
)
async def test_fetch_withholds_unsafe_or_unsupported_stored_destination(tmp_path, url):
    engine, factory, run_id, _ = await _database(tmp_path)
    source = _source(url)
    provider = _Provider(source)
    try:
        async with factory() as session:
            await SearchSourceRepository(session).add_search_result(run_id, source)
            await session.commit()
        tools = AgentResearchTools(
            agent_name="GeneralShoppingAgent",
            run_id=run_id,
            session_factory=factory,
            search_provider=provider,
            extraction_provider=provider,
        )
        result = await tools.fetch(FetchSourceRequest(source_id=source.source_id))
        assert result.status == "gap"
        assert result.gap == "Source URL is outside approved retrieval policy."
        assert provider.fetched == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "returned_url",
    [
        "https://shop.example.com/product?configuration=A55",
        "https://user:secret@shop.example.com/product?sku=A55",
    ],
)
async def test_public_fetch_returns_gap_for_unsupported_provider_destination(
    tmp_path, returned_url
):
    engine, factory, run_id, _ = await _database(tmp_path)
    source = _source(_ITEM)

    class RedirectProvider(_Provider):
        async def extract(self, url, options):
            self.fetched.append(str(url))
            return _snapshot(returned_url)

    provider = RedirectProvider(source)
    try:
        tools = AgentResearchTools(
            agent_name="GeneralShoppingAgent",
            run_id=run_id,
            session_factory=factory,
            search_provider=provider,
            extraction_provider=provider,
        )
        sdk = {tool.name: tool for tool in tools.sdk_tools()}
        await _invoke(sdk["search_sources"], query="desk lamp")
        result = await _invoke(sdk["fetch_source"], source_id=str(source.source_id))
        assert result["status"] == "gap"
        assert result["gap"] == "Page retrieval returned an unsafe URL."
        assert provider.fetched == [_ITEM]
        async with factory() as session:
            assert (
                await SearchSourceRepository(session).get_snapshot_for_search_result(
                    run_id, source.source_id
                )
                is None
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_public_extraction_keeps_query_item_link_from_collection(tmp_path):
    engine, factory, run_id, _ = await _database(tmp_path)
    snapshot = _snapshot("https://shop.example.com/product")
    snapshot.extracted_content.text = (
        f"A55 desk lamp sold by Example Store. Item offer {_ITEM}"
    )
    try:
        async with factory() as session:
            await SearchSourceRepository(session).add_source_snapshot(run_id, snapshot)
            await session.commit()
        agent = LiveExtractionAgent(
            settings=Settings(_env_file=None, environment="test"),
            snapshot_tools_factory=lambda request: SnapshotInterpretationTools(
                run_id=run_id,
                allowed_snapshot_ids=request.snapshot_ids,
                session_factory=factory,
            ),
            model_runner=MockExtractionModelRunner(_output(snapshot.source_id, _ITEM)),
        )
        result = await agent.run(
            ExtractionAgentInput(
                run_id=run_id,
                snapshot_ids=(snapshot.source_id,),
                collection_snapshot_ids=(snapshot.source_id,),
            )
        )
        assert str(result.listings[0].url) == _ITEM
        assert result.listings[0].source_ids == (snapshot.source_id,)
        assert result.evidence_gaps == ()
    finally:
        await engine.dispose()
