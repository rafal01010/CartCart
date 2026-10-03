import json
from pathlib import Path
from uuid import uuid4

import pytest
from agents.tool_context import ToolContext
from pydantic import AnyHttpUrl

from app.agents.research_tools import (
    AgentResearchTools,
    FetchSourceRequest,
    ResearchToolLimits,
    ResearchToolStatus,
    SearchSourcesRequest,
)
from app.agents.workbench import _workbench_activity
from app.agents.extraction_tools import SnapshotInterpretationTools
from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_database_engine, create_session_factory
from app.providers.contracts import (
    ExtractionProviderOptions,
    SearchProviderOptions,
    SourceAllowAvoidPolicy,
    SourcePolicyAction,
    SourcePolicyRule,
)
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
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


class RecordingSearchProvider:
    provider_name = "fixture-search"

    def __init__(
        self, results: tuple[SearchResult, ...] = (), error: Exception | None = None
    ):
        self.results = results
        self.error = error
        self.calls: list[tuple[SearchQuery, SearchProviderOptions]] = []

    async def search(
        self, query: SearchQuery, options: SearchProviderOptions | None = None
    ):
        assert options is not None
        self.calls.append((query, options))
        if self.error is not None:
            raise self.error
        return self.results


class RecordingExtractionProvider:
    provider_name = "fixture-extraction"

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[tuple[AnyHttpUrl, ExtractionProviderOptions]] = []

    async def extract(
        self, url: AnyHttpUrl, options: ExtractionProviderOptions | None = None
    ):
        assert options is not None
        self.calls.append((url, options))
        if self.error is not None:
            raise self.error
        return SourceSnapshot(
            url=url,
            source_type=options.source_type,
            provider=ProviderMetadata(
                provider_name=self.provider_name,
                raw={"api_key": "must-not-leak"},
            ),
            extraction_status=ExtractionStatus.SUCCEEDED,
            extracted_content=ExtractedPageContent(
                text="A review covering several TVs. " * 100,
                extractor="fixture",
                word_count=600,
                published_date="2020-10-03",
            ),
        )


class FailedExtractionProvider(RecordingExtractionProvider):
    async def extract(
        self, url: AnyHttpUrl, options: ExtractionProviderOptions | None = None
    ):
        assert options is not None
        self.calls.append((url, options))
        return SourceSnapshot(
            url=url,
            source_type=options.source_type,
            provider=ProviderMetadata(
                provider_name=self.provider_name,
                raw={
                    "extraction_failure_code": "blocked",
                    "extraction_failure_message": "secret token in provider message",
                },
            ),
            extraction_status=ExtractionStatus.FAILED,
        )


@pytest.mark.asyncio
async def test_late_source_span_exact_quote_and_same_run_scope(tmp_path: Path) -> None:
    engine, factory, run_id, other_run = await _database(tmp_path)
    quote = "Imported 256GB offer has no local warranty; PH 512GB is a different variant."
    page = "Unrelated navigation. " * 2000 + quote
    source = _generic_result()
    snapshot = SourceSnapshot(url=source.url, source_type=SourceType.PRODUCT_PAGE,
        provider=ProviderMetadata(provider_name="fixture"), extraction_status=ExtractionStatus.SUCCEEDED,
        extracted_content=ExtractedPageContent(text=page, extractor="fixture", word_count=4000))
    try:
        async with factory() as session:
            repository = SearchSourceRepository(session)
            await repository.add_search_result(run_id, source)
            await repository.add_source_snapshot(run_id, snapshot, search_result_id=source.source_id)
            await session.commit()
        tools = AgentResearchTools(agent_name="SmartphoneSpecialistAgent", run_id=run_id,
            session_factory=factory, search_provider=RecordingSearchProvider(),
            extraction_provider=RecordingExtractionProvider())
        first = await tools.fetch(FetchSourceRequest(source_id=source.source_id))
        assert first.text == page[:4000]
        assert (await tools.record_quote(source.source_id, quote)).status == ResearchToolStatus.GAP
        late = await tools.fetch(FetchSourceRequest(source_id=source.source_id, focus="Imported 256GB"))
        assert quote in (late.text or "")
        assert late.start_char > 4000 and late.total_characters == len(page)
        recorded = await tools.record_quote(source.source_id, quote)
        assert recorded.quote == quote and recorded.evidence_id is not None
        reader = SnapshotInterpretationTools(run_id=run_id, allowed_snapshot_ids=(snapshot.source_id,), session_factory=factory)
        assert quote in ((await reader.read(str(snapshot.source_id), focus="Imported 256GB")).text or "")
        other = SnapshotInterpretationTools(run_id=other_run, allowed_snapshot_ids=(snapshot.source_id,), session_factory=factory)
        assert (await other.read(str(snapshot.source_id))).status == "unknown_snapshot"
        assert (await reader.read("/private/tmp/page.txt")).status == "invalid_request"
        async with factory() as session:
            repository = SearchSourceRepository(session)
            durable = await repository.get_source_snapshot_for_run(run_id, snapshot.source_id)
            evidence = await repository.list_source_evidence(run_id)
        assert durable is not None and durable.extracted_content is not None
        assert durable.extracted_content.text == page
        assert evidence[0].claim == quote
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_search_dedup_keeps_distinct_variant_urls_and_derived_query(tmp_path: Path) -> None:
    engine, factory, run_id, _ = await _database(tmp_path)
    first = _generic_result("https://shop.example.com/phone?variant=256")
    second = _generic_result("https://shop.example.com/phone?variant=512")
    provider = RecordingSearchProvider((first, first, second))
    tools = AgentResearchTools(agent_name="GeneralShoppingAgent", run_id=run_id, session_factory=factory,
                              search_provider=provider, extraction_provider=RecordingExtractionProvider())
    try:
        found = await tools.search(SearchSourcesRequest(query="current phone Philippines official warranty"))
        reused = await tools.search(SearchSourcesRequest(query="current phone Philippines official warranty"))
        followup = await tools.search(SearchSourcesRequest(query="phone 512GB Philippines seller"))
        assert [item.source_id for item in found.sources] == [first.source_id, second.source_id]
        assert [item.source_id for item in followup.sources] == [first.source_id, second.source_id]
        assert reused == found
        assert [q.query for q, _ in provider.calls] == [
            "current phone Philippines official warranty", "phone 512GB Philippines seller"]
        assert tools.workbench_activity[-1]["input"]["query"] == "phone 512GB Philippines seller"
        async with factory() as session:
            assert len(await SearchSourceRepository(session).list_search_results(run_id)) == 2
    finally:
        await engine.dispose()


async def _database(tmp_path: Path):
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, database_path=tmp_path / "research-tools.sqlite3"
    )
    engine = create_database_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        shopping_session = await SessionRepository(session).create(
            original_input=CreateSessionRequest(query="Which TV should I buy?"),
            current_brief=ShoppingBrief(original_query="Which TV should I buy?"),
        )
        run = await RunRepository(session).create(shopping_session.session_id)
        other_run = await RunRepository(session).create(shopping_session.session_id)
        await session.commit()
    return engine, factory, run.run_id, other_run.run_id


def _generic_result(
    url: str = "https://shop.example.com/tvs?token=private&utm_source=x",
):
    return SearchResult(
        query=SearchQuery(query="best TVs", intent=SearchIntent.DISCOVERY),
        url=url,
        title="TV options",
        snippet="Several models and prices",
        source_type=SourceType.SEARCH_RESULT,
        provider=ProviderMetadata(
            provider_name="fixture-search",
            raw={"api_key": "must-not-leak", "vendor_argument": "hidden"},
        ),
    )


@pytest.mark.asyncio
async def test_sdk_tools_persist_generic_sources_and_fetch_by_run_scoped_id(
    tmp_path: Path,
):
    engine, factory, run_id, _ = await _database(tmp_path)
    try:
        source = _generic_result()
        search = RecordingSearchProvider((source,))
        extraction = RecordingExtractionProvider()
        tools = AgentResearchTools(
            agent_name="DiscoveryAgent",
            run_id=run_id,
            session_factory=factory,
            search_provider=search,
            extraction_provider=extraction,
            limits=ResearchToolLimits(max_page_text_chars=500),
        )
        sdk_search, sdk_fetch = tools.sdk_tools()
        assert {sdk_search.name, sdk_fetch.name} == {"search_sources", "fetch_source"}
        assert "url" not in json.dumps(sdk_fetch.params_json_schema)
        assert "api_key" not in json.dumps(sdk_search.params_json_schema)
        assert sdk_fetch.params_json_schema["additionalProperties"] is False

        search_context = ToolContext(
            context=None,
            tool_name="search_sources",
            tool_call_id="search-1",
            tool_arguments="{}",
        )
        searched = json.loads(
            await sdk_search.on_invoke_tool(
                search_context,
                json.dumps(
                    {
                        "query": "best TVs",
                        "intent": "review",
                        "region_code": "ph",
                        "max_results": 5,
                    }
                ),
            )
        )
        assert searched["status"] == "succeeded"
        assert searched["sources"][0]["source_id"] == str(source.source_id)
        assert searched["sources"][0]["provider_source_type"] == "search_result"
        assert searched["sources"][0]["url"] == "https://shop.example.com/tvs"
        assert "must-not-leak" not in json.dumps(searched)
        assert search.calls[0][0].region_code == "PH"
        assert search.calls[0][1].max_results == 5

        invalid_fetch = json.loads(
            await sdk_fetch.on_invoke_tool(
                ToolContext(
                    context=None,
                    tool_name="fetch_source",
                    tool_call_id="fetch-invalid",
                    tool_arguments="{}",
                ),
                json.dumps({"source_id": "https://attacker.example/secret"}),
            )
        )
        assert invalid_fetch["status"] == "invalid_request"
        assert extraction.calls == []

        fetched = json.loads(
            await sdk_fetch.on_invoke_tool(
                ToolContext(
                    context=None,
                    tool_name="fetch_source",
                    tool_call_id="fetch-1",
                    tool_arguments="{}",
                ),
                json.dumps({"source_id": str(source.source_id)}),
            )
        )
        assert fetched["published_date"] == "2020-10-03"
        assert fetched["status"] == "succeeded"
        assert fetched["source_id"] == str(source.source_id)
        assert fetched["snapshot_id"] != fetched["source_id"]
        assert fetched["text_truncated"] is True
        assert len(fetched["text"]) == 500
        assert "must-not-leak" not in json.dumps(fetched)
        assert extraction.calls[0][1].source_type == SourceType.SEARCH_RESULT
        repeated = await tools.fetch(FetchSourceRequest(source_id=source.source_id))
        assert str(repeated.snapshot_id) == fetched["snapshot_id"]
        assert len(extraction.calls) == 1

        async with factory() as session:
            repository = SearchSourceRepository(session)
            saved_result = await repository.get_search_result_for_run(
                run_id, source.source_id
            )
            assert saved_result is not None
            assert saved_result.provider.raw == {}
            assert await repository.get_source_snapshot_for_run(
                run_id, fetched["snapshot_id"]
            )
        assert [item.tool_name for item in _workbench_activity(tools)] == [
            "search_sources",
            "fetch_source",
            "fetch_source",
        ]
        assert all(
            {key: item.input[key] for key in ("agent", "run_id")}
            == {"agent": "DiscoveryAgent", "run_id": str(run_id)}
            for item in _workbench_activity(tools)
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_shared_run_session_commits_search_before_returning_source_id(
    tmp_path: Path,
) -> None:
    engine, factory, run_id, _ = await _database(tmp_path)
    try:
        async with factory() as shared_session:
            source = _generic_result("https://shop.example.com/shared-session-tv")
            tools = AgentResearchTools(
                agent_name="DiscoveryAgent",
                run_id=run_id,
                session_factory=None,
                shared_session=shared_session,
                search_provider=RecordingSearchProvider((source,)),
                extraction_provider=RecordingExtractionProvider(),
            )
            result = await tools.search(SearchSourcesRequest(query="TV shopping"))
            assert result.status == ResearchToolStatus.SUCCEEDED
            assert result.sources[0].source_id == source.source_id
            async with factory() as second_session:
                saved = await SearchSourceRepository(
                    second_session
                ).get_search_result_for_run(run_id, source.source_id)
                assert saved is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_fetch_rejects_unknown_and_cross_run_source_ids_without_provider_call(
    tmp_path: Path,
):
    engine, factory, run_id, other_run_id = await _database(tmp_path)
    try:
        source = _generic_result()
        async with factory() as session:
            await SearchSourceRepository(session).add_search_result(
                other_run_id, source
            )
            await session.commit()
        extraction = RecordingExtractionProvider()
        tools = AgentResearchTools(
            agent_name="DiscoveryAgent",
            run_id=run_id,
            session_factory=factory,
            search_provider=RecordingSearchProvider(),
            extraction_provider=extraction,
        )
        assert (
            await tools.fetch(FetchSourceRequest(source_id=source.source_id))
        ).status == (ResearchToolStatus.UNKNOWN_SOURCE)
        assert (await tools.fetch(FetchSourceRequest(source_id=uuid4()))).status == (
            ResearchToolStatus.UNKNOWN_SOURCE
        )
        assert extraction.calls == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_limits_failures_and_unsafe_provider_urls_are_typed(tmp_path: Path):
    engine, factory, run_id, _ = await _database(tmp_path)
    try:
        safe = _generic_result("https://shop.example.com/tvs")
        unsafe = _generic_result("http://127.0.0.1/private")
        search = RecordingSearchProvider((safe, unsafe))
        extraction = RecordingExtractionProvider(error=RuntimeError("secret token"))
        tools = AgentResearchTools(
            agent_name="DiscoveryAgent",
            run_id=run_id,
            session_factory=factory,
            search_provider=search,
            extraction_provider=extraction,
            limits=ResearchToolLimits(max_search_calls=1, max_fetch_calls=1),
        )
        first = await tools.search(SearchSourcesRequest(query="TVs"))
        assert first.status == ResearchToolStatus.SUCCEEDED
        assert [item.source_id for item in first.sources] == [safe.source_id]
        assert (await tools.search(SearchSourcesRequest(query="more TVs"))).status == (
            ResearchToolStatus.BUDGET_EXHAUSTED
        )
        failed = await tools.fetch(FetchSourceRequest(source_id=safe.source_id))
        assert failed.status == ResearchToolStatus.PROVIDER_UNAVAILABLE
        assert "secret" not in failed.model_dump_json()
        assert (
            await tools.fetch(FetchSourceRequest(source_id=safe.source_id))
        ).status == (ResearchToolStatus.BUDGET_EXHAUSTED)

        unavailable = AgentResearchTools(
            agent_name="DiscoveryAgent",
            run_id=run_id,
            session_factory=factory,
            search_provider=RecordingSearchProvider(error=RuntimeError("api key")),
            extraction_provider=extraction,
        )
        failure = await unavailable.search(SearchSourcesRequest(query="TVs"))
        assert failure.status == ResearchToolStatus.PROVIDER_UNAVAILABLE
        assert "api key" not in failure.model_dump_json()
    finally:
        await engine.dispose()


def test_non_approved_agent_cannot_receive_research_tools() -> None:
    with pytest.raises(ValueError, match="not approved"):
        AgentResearchTools(
            agent_name="ComparisonDecisionAgent",
            run_id=uuid4(),
            session_factory=None,  # type: ignore[arg-type]
            search_provider=RecordingSearchProvider(),
            extraction_provider=RecordingExtractionProvider(),
        )


@pytest.mark.asyncio
async def test_backend_domain_policy_filters_provider_results_even_if_adapter_does_not(
    tmp_path: Path,
) -> None:
    engine, factory, run_id, _ = await _database(tmp_path)
    try:
        allowed = _generic_result("https://shop.example.com/tvs")
        excluded = _generic_result("https://blocked.example.net/tvs")
        tools = AgentResearchTools(
            agent_name="DiscoveryAgent",
            run_id=run_id,
            session_factory=factory,
            search_provider=RecordingSearchProvider((allowed, excluded)),
            extraction_provider=RecordingExtractionProvider(),
            source_policy=SourceAllowAvoidPolicy(
                avoid=(
                    SourcePolicyRule(
                        action=SourcePolicyAction.AVOID,
                        reason="Disallowed merchant.",
                        domain="blocked.example.net",
                    ),
                ),
            ),
        )
        result = await tools.search(SearchSourcesRequest(query="TVs"))
        assert [item.source_id for item in result.sources] == [allowed.source_id]
        async with factory() as session:
            saved = await SearchSourceRepository(session).list_search_results(run_id)
        assert [item.source_id for item in saved] == [allowed.source_id]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_page_snapshot_is_persisted_as_citable_gap(tmp_path: Path) -> None:
    engine, factory, run_id, _ = await _database(tmp_path)
    try:
        source = _generic_result("https://shop.example.com/tvs")
        tools = AgentResearchTools(
            agent_name="DiscoveryAgent",
            run_id=run_id,
            session_factory=factory,
            search_provider=RecordingSearchProvider((source,)),
            extraction_provider=FailedExtractionProvider(),
        )
        await tools.search(SearchSourcesRequest(query="TVs"))
        result = await tools.fetch(FetchSourceRequest(source_id=source.source_id))
        assert result.status == ResearchToolStatus.GAP
        assert result.snapshot_id is not None
        assert result.extraction_status == ExtractionStatus.FAILED
        assert "secret" not in result.model_dump_json()
        async with factory() as session:
            snapshot = await SearchSourceRepository(
                session
            ).get_source_snapshot_for_run(run_id, result.snapshot_id)
        assert snapshot is not None
        assert snapshot.provider.raw["extraction_failure_code"] == "blocked"
        assert "extraction_failure_message" not in snapshot.provider.raw
    finally:
        await engine.dispose()
