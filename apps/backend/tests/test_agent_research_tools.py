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
    quote = (
        "Imported 256GB offer has no local warranty; PH 512GB is a different variant."
    )
    page = "Unrelated navigation. " * 2000 + quote
    source = _generic_result()
    snapshot = SourceSnapshot(
        url=source.url,
        source_type=SourceType.PRODUCT_PAGE,
        provider=ProviderMetadata(provider_name="fixture"),
        extraction_status=ExtractionStatus.SUCCEEDED,
        extracted_content=ExtractedPageContent(
            text=page, extractor="fixture", word_count=4000
        ),
    )
    try:
        async with factory() as session:
            repository = SearchSourceRepository(session)
            await repository.add_search_result(run_id, source)
            await repository.add_source_snapshot(
                run_id, snapshot, search_result_id=source.source_id
            )
            await session.commit()
        tools = AgentResearchTools(
            agent_name="SmartphoneSpecialistAgent",
            run_id=run_id,
            session_factory=factory,
            search_provider=RecordingSearchProvider(),
            extraction_provider=RecordingExtractionProvider(),
        )
        first = await tools.fetch(FetchSourceRequest(source_id=source.source_id))
        assert first.text == page[:4000]
        assert (
            await tools.record_quote(source.source_id, quote)
        ).status == ResearchToolStatus.GAP
        late = await tools.fetch(
            FetchSourceRequest(source_id=source.source_id, focus="Imported 256GB")
        )
        assert quote in (late.text or "")
        assert late.start_char > 4000 and late.total_characters == len(page)
        recorded = await tools.record_quote(source.source_id, quote)
        assert recorded.quote == quote and recorded.evidence_id is not None
        reader = SnapshotInterpretationTools(
            run_id=run_id,
            allowed_snapshot_ids=(snapshot.source_id,),
            session_factory=factory,
        )
        assert quote in (
            (await reader.read(str(snapshot.source_id), focus="Imported 256GB")).text
            or ""
        )
        other = SnapshotInterpretationTools(
            run_id=other_run,
            allowed_snapshot_ids=(snapshot.source_id,),
            session_factory=factory,
        )
        assert (await other.read(str(snapshot.source_id))).status == "unknown_snapshot"
        assert (await reader.read("/private/tmp/page.txt")).status == "invalid_request"
        async with factory() as session:
            repository = SearchSourceRepository(session)
            durable = await repository.get_source_snapshot_for_run(
                run_id, snapshot.source_id
            )
            evidence = await repository.list_source_evidence(run_id)
        assert durable is not None and durable.extracted_content is not None
        assert durable.extracted_content.text == page
        assert evidence[0].claim == quote
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_search_dedup_keeps_distinct_variant_urls_and_derived_query(
    tmp_path: Path,
) -> None:
    engine, factory, run_id, _ = await _database(tmp_path)
    first = _generic_result("https://shop.example.com/phone?variant=256")
    second = _generic_result("https://shop.example.com/phone?variant=512")
    provider = RecordingSearchProvider((first, first, second))
    tools = AgentResearchTools(
        agent_name="GeneralShoppingAgent",
        run_id=run_id,
        session_factory=factory,
        search_provider=provider,
        extraction_provider=RecordingExtractionProvider(),
    )
    try:
        found = await tools.search(
            SearchSourcesRequest(query="current phone Philippines official warranty")
        )
        reused = await tools.search(
            SearchSourcesRequest(query="current phone Philippines official warranty")
        )
        followup = await tools.search(
            SearchSourcesRequest(query="phone 512GB Philippines seller")
        )
        assert [item.source_id for item in found.sources] == [
            first.source_id,
            second.source_id,
        ]
        assert [item.source_id for item in followup.sources] == [
            first.source_id,
            second.source_id,
        ]
        assert reused == found
        assert [q.query for q, _ in provider.calls] == [
            "current phone Philippines official warranty",
            "phone 512GB Philippines seller",
        ]
        assert (
            tools.workbench_activity[-1]["input"]["query"]
            == "phone 512GB Philippines seller"
        )
        async with factory() as session:
            assert (
                len(await SearchSourceRepository(session).list_search_results(run_id))
                == 2
            )
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
        sdk = {tool.name: tool for tool in tools.sdk_tools()}
        sdk_search, sdk_fetch = sdk["search_sources"], sdk["fetch_source"]
        assert {
            "read_search_results",
            "complete_research_result",
            "read_research_result",
        }.issubset(sdk)
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


@pytest.mark.asyncio
async def test_search_preview_paging_original_lookup_and_owner_transfer(
    tmp_path: Path,
) -> None:
    engine, factory, run_id, other_run = await _database(tmp_path)
    warning = "Imported offer has no local warranty."
    originals = tuple(
        _generic_result(f"https://shop.example.com/lead-{index}").model_copy(
            update={
                "title": f"Brand {index} 日本",
                "snippet": "Distinct information. " * 40 + warning,
            }
        )
        for index in range(6)
    )
    search = RecordingSearchProvider(originals)
    extraction = RecordingExtractionProvider()
    tools = AgentResearchTools(
        agent_name="GeneralShoppingAgent",
        run_id=run_id,
        session_factory=factory,
        search_provider=search,
        extraction_provider=extraction,
        limits=ResearchToolLimits(max_search_calls=1),
    )
    try:
        result = await tools.search(SearchSourcesRequest(query="shopping discovery"))
        assert (
            len(result.sources) == 4
            and result.total_sources == 6
            and result.next_offset == 4
        )
        assert result.sources[0].snippet == originals[0].snippet[:200]
        assert result.sources[0].unreviewed_content is True
        assert result.sources[0].material_cautions == (warning,)
        assert result.deferred_source_ids == tuple(
            item.source_id for item in originals[4:]
        )
        later = json.loads(
            await tools.read_search_results(
                search_result_id=str(result.search_result_id), offset=4
            )
        )
        assert [item["title"] for item in later["sources"]] == [
            "Brand 4 日本",
            "Brand 5 日本",
        ]
        original = json.loads(
            await tools.read_search_results(
                source_id=str(originals[-1].source_id), focus="Imported"
            )
        )
        assert warning in original["snippet"] and original["start_char"] > 200
        assert original["total_characters"] == len(originals[-1].snippet)
        transferred = tools.for_agent("TechnologyDomainAnalystAgent")
        assert (
            await transferred.search(SearchSourcesRequest(query="shopping discovery"))
            == result
        )
        assert len(search.calls) == 1
        assert (
            json.loads(
                await transferred.read_search_results(
                    search_result_id=str(result.search_result_id), offset=4
                )
            )["sources"]
            == later["sources"]
        )
        other = AgentResearchTools(
            agent_name="GeneralShoppingAgent",
            run_id=other_run,
            session_factory=factory,
            search_provider=search,
            extraction_provider=extraction,
        )
        assert not tools.share_run_state(other)
        assert (
            json.loads(
                await other.read_search_results(source_id=str(originals[-1].source_id))
            )["status"]
            == "unknown_source"
        )
        assert (
            json.loads(
                await other.read_search_results(
                    search_result_id=str(result.search_result_id)
                )
            )["status"]
            == "unknown_source"
        )
        async with factory() as session:
            durable = await SearchSourceRepository(session).list_search_results(run_id)
        assert len(durable) == 6 and all(
            item.snippet.endswith(warning) for item in durable
        )
        sdk = {tool.name: tool for tool in tools.sdk_tools()}
        assert not sdk["search_sources"].is_enabled(None, None)
        assert sdk["read_search_results"].is_enabled is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_changed_same_url_snippet_keeps_distinct_originals(
    tmp_path: Path,
) -> None:
    engine, factory, run_id, _ = await _database(tmp_path)
    source = _generic_result("https://shop.example.com/phone")
    search = RecordingSearchProvider((source,))
    tools = AgentResearchTools(
        agent_name="GeneralShoppingAgent",
        run_id=run_id,
        session_factory=factory,
        search_provider=search,
        extraction_provider=RecordingExtractionProvider(),
    )
    try:
        first = await tools.search(SearchSourcesRequest(query="first discovery"))
        search.results = (
            source.model_copy(
                update={"snippet": "Changed seller offer. No local warranty."}
            ),
        )
        changed = await tools.search(SearchSourcesRequest(query="seller offer check"))
        assert first.sources[0].source_id != changed.sources[0].source_id
        old = json.loads(
            await tools.read_search_results(source_id=str(first.sources[0].source_id))
        )
        new = json.loads(
            await tools.read_search_results(source_id=str(changed.sources[0].source_id))
        )
        assert old["snippet"] == "Several models and prices"
        assert new["snippet"] == "Changed seller offer. No local warranty."
        assert new["material_cautions"] == [
            "Changed seller offer.",
            "No local warranty.",
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_owner_evidence_late_caution_and_original_bundle_lookup(
    tmp_path: Path,
) -> None:
    from app.agents.owner_research import (
        OwnerResearchContext,
        OwnerResearchState,
        _bounded_owner_bundle,
    )
    from app.schemas.search_sources import VideoReviewEvidenceBundle

    engine, factory, run_id, other_run = await _database(tmp_path)
    source = _generic_result()
    caution = "No local warranty."
    text = "Price PHP 90000. " + "Navigation details. " * 200 + caution
    snapshot = SourceSnapshot(
        url=source.url,
        source_type=SourceType.PRODUCT_PAGE,
        provider=ProviderMetadata(provider_name="fixture"),
        extraction_status=ExtractionStatus.SUCCEEDED,
        extracted_content=ExtractedPageContent(
            text=text, extractor="fixture", word_count=500
        ),
    )
    state = OwnerResearchState()
    context = OwnerResearchContext(
        agent_name="GeneralShoppingAgent",
        run_id=run_id,
        brief=ShoppingBrief(original_query="Compare products"),
        region_code=None,
        session_factory=factory,
        allowed_source_ids=lambda: frozenset({source.source_id}),
        research_state=state,
    )
    try:
        async with factory() as session:
            repo = SearchSourceRepository(session)
            await repo.add_search_result(run_id, source)
            await repo.add_source_snapshot(
                run_id, snapshot, search_result_id=source.source_id
            )
            await session.commit()
        first = await context.read_source(str(source.source_id))
        assert caution not in first["text"] and first["material_cautions"] == [caution]
        assert first["text_truncated"] is True and first["unreviewed_content"] is True
        late = await context.read_source(
            str(source.source_id), focus="No local warranty"
        )
        assert caution in late["text"] and late["start_char"] > 2000
        assert late["content_sha256"] == first["content_sha256"]
        bundle = VideoReviewEvidenceBundle(
            transcript_gap_notes=(
                "Transcript unavailable. " * 1000,
                "Seller warranty remains unverified.",
            )
        )
        original = bundle.model_dump(mode="json")
        state.bundles[str(bundle.bundle_id)] = (run_id, "original", original)
        bounded = _bounded_owner_bundle(original, "original")
        assert (
            len(json.dumps(bounded)) <= 5000 and bounded["unreviewed_content"] is True
        )
        assert "Seller warranty remains unverified." in bounded["material_cautions"]
        loaded = context.read_bundle(str(bundle.bundle_id), focus="Seller warranty")
        assert loaded["status"] == "succeeded" and "Seller warranty" in loaded["text"]
        other = OwnerResearchContext(
            agent_name="GeneralShoppingAgent",
            run_id=other_run,
            brief=context.brief,
            region_code=None,
            session_factory=factory,
            research_state=state,
        )
        assert other.read_bundle(str(bundle.bundle_id))["status"] == "unknown_source"
        assert context.read_bundle(str(uuid4()))["status"] == "unknown_source"
        assert state.bundles[str(bundle.bundle_id)][2] == original
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_direct_owner_consultation_retains_original_and_reuses_completion(
    tmp_path: Path,
) -> None:
    import asyncio
    from types import SimpleNamespace

    from app.agents.context_management import context_scope
    from app.agents.research_history import active_history, retired_output
    from app.agents.owner_research import OwnerResearchContext, OwnerResearchState
    from app.db.repositories.products import ProductRepository
    from app.schemas.products import CanonicalProduct
    from app.schemas.search_sources import (
        SourceIntelligenceCapability,
        VideoReviewEvidenceBundle,
    )

    engine, factory, run_id, _ = await _database(tmp_path)
    product = CanonicalProduct(name="Test Phone", category="smartphone")
    bundle = VideoReviewEvidenceBundle(
        transcript_gap_notes=(
            "Transcript unavailable. " * 1000,
            "Seller warranty remains unverified.",
        )
    )

    class Manager:
        calls = 0

        async def run(self, _input):
            self.calls += 1
            return SimpleNamespace(
                video_bundles=(bundle,),
                community_bundles=(),
                amazon_bundles=(),
                ikea_bundles=(),
                activity=(),
                notes=(),
                model_name="offline-fixture",
                total_tokens=0,
            )

    manager = Manager()
    state = OwnerResearchState()
    brief = ShoppingBrief(original_query="Compare smartphone")
    contexts = [
        OwnerResearchContext(
            agent_name=agent,
            run_id=run_id,
            brief=brief,
            region_code="PH",
            session_factory=factory,
            source_manager=manager,
            research_state=state,
        )
        for agent in ("GeneralShoppingAgent", "SmartphoneSpecialistAgent")
    ]
    try:
        async with factory() as session:
            await ProductRepository(session).add_canonical_product(run_id, product)
            await session.commit()
        responses = await asyncio.gather(
            *(
                context.consult_source(
                    SourceIntelligenceCapability.VIDEO_REVIEW,
                    product_id=str(product.product_id),
                )
                for context in contexts
            )
        )
        assert manager.calls == 1 and responses[0] == responses[1]
        assert len(json.dumps(responses[0])) < 12000
        assert responses[0]["bundles"][0]["unreviewed_content"] is True
        assert (
            "Seller warranty remains unverified."
            in responses[0]["bundles"][0]["material_cautions"]
        )
        assert state.bundles[str(bundle.bundle_id)][2] == bundle.model_dump(mode="json")
        with context_scope():
            tools = {tool.name: tool for tool in contexts[0].sdk_tools()}
            arguments = json.dumps(
                {
                    "capability": "video_review",
                    "product_id": str(product.product_id),
                    "product_name": None,
                    "evidence_id": None,
                }
            )
            consulted = json.loads(
                await tools["consult_source_intelligence"].on_invoke_tool(
                    ToolContext(
                        context=None,
                        tool_name="consult_source_intelligence",
                        tool_call_id="consult",
                        tool_arguments=arguments,
                    ),
                    arguments,
                )
            )
            assert consulted["_research_view"]["view_id"]
            view_id = consulted["_research_view"]["view_id"]
            assert (
                active_history().complete(
                    view_id, ["Seller warranty remains unverified."]
                )["status"]
                == "processed"
            )
            retired = json.loads(retired_output(json.dumps(consulted)))
            assert retired["status"] == "processed"
            assert (
                "Seller warranty remains unverified." in retired["retained"]["cautions"]
            )
            loaded = contexts[1].read_bundle(
                str(bundle.bundle_id), focus="Seller warranty"
            )
            assert "Seller warranty remains unverified." in loaded["text"]
        changed_region = OwnerResearchContext(
            agent_name="GeneralShoppingAgent",
            run_id=run_id,
            brief=brief,
            region_code="US",
            session_factory=factory,
            source_manager=manager,
            research_state=state,
        )
        await changed_region.consult_source(
            SourceIntelligenceCapability.VIDEO_REVIEW,
            product_id=str(product.product_id),
        )
        assert manager.calls == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_owner_consultation_unicode_cap_original_notes_and_versioned_sdk_lookup(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace
    from app.agents.context_management import context_scope
    from app.agents.owner_research import OwnerResearchContext, OwnerResearchState
    from app.db.repositories.products import ProductRepository
    from app.schemas.products import CanonicalProduct
    from app.schemas.search_sources import VideoReviewEvidenceBundle

    engine, factory, run_id, other_run = await _database(tmp_path)
    product = CanonicalProduct(name="電話", category="smartphone")
    bundles = tuple(
        VideoReviewEvidenceBundle(
            transcript_gap_notes=(
                "商品情報を確認してください。" * 1000,
                "Seller warranty remains unverified.",
            )
        )
        for _ in range(12)
    )
    late_caution = "Late note says the imported offer has no local warranty."
    notes = ("地域の商品情報。" * 5000,) * 6 + (late_caution,)
    state = OwnerResearchState()

    class Manager:
        async def run(self, _input):
            return SimpleNamespace(
                video_bundles=bundles,
                community_bundles=(),
                amazon_bundles=(),
                ikea_bundles=(),
                activity=(),
                notes=notes,
                model_name="offline-fixture",
                total_tokens=0,
            )

    context = OwnerResearchContext(
        agent_name="GeneralShoppingAgent",
        run_id=run_id,
        brief=ShoppingBrief(original_query="電話を比較"),
        region_code="PH",
        session_factory=factory,
        source_manager=Manager(),
        research_state=state,
    )
    try:
        async with factory() as session:
            await ProductRepository(session).add_canonical_product(run_id, product)
            await session.commit()
        with context_scope():
            tools = {tool.name: tool for tool in context.sdk_tools()}
            arguments = json.dumps(
                {
                    "capability": "video_review",
                    "product_id": str(product.product_id),
                    "product_name": None,
                    "evidence_id": None,
                }
            )
            raw = await tools["consult_source_intelligence"].on_invoke_tool(
                ToolContext(
                    context=None,
                    tool_name="consult_source_intelligence",
                    tool_call_id="unicode",
                    tool_arguments=arguments,
                ),
                arguments,
            )
            assert len(raw) <= 12000 and "商品" in raw and "\\u5546" not in raw
            response = json.loads(raw)
            assert (
                response["status"] == "succeeded"
                and response["unreviewed_content"] is True
            )
            assert response["deferred_bundle_count"] >= 10
            assert late_caution in response["material_cautions"]
            consultation_id = response["consultation_id"]
            canonical = state.bundles[consultation_id][2]
            assert canonical["notes"] == list(notes) and len(canonical["bundles"]) == 12
            arguments = json.dumps(
                {
                    "bundle_id": consultation_id,
                    "start_char": 0,
                    "focus": "Late note",
                    "content_sha256": response["consultation_sha256"],
                }
            )
            loaded = json.loads(
                await tools["read_source_bundle"].on_invoke_tool(
                    ToolContext(
                        context=None,
                        tool_name="read_source_bundle",
                        tool_call_id="notes",
                        tool_arguments=arguments,
                    ),
                    arguments,
                )
            )
            assert late_caution in loaded["text"] and loaded["start_char"] > 4000
            bundle_id = str(bundles[0].bundle_id)
            old_hash = state.bundles[bundle_id][1]
            state.bundles[bundle_id] = (
                run_id,
                "changed",
                {"bundle_id": bundle_id, "notes": ["Changed current original."]},
            )
            arguments = json.dumps(
                {
                    "bundle_id": bundle_id,
                    "start_char": 0,
                    "focus": "Seller warranty",
                    "content_sha256": old_hash,
                }
            )
            loaded = json.loads(
                await tools["read_source_bundle"].on_invoke_tool(
                    ToolContext(
                        context=None,
                        tool_name="read_source_bundle",
                        tool_call_id="version",
                        tool_arguments=arguments,
                    ),
                    arguments,
                )
            )
            assert "Seller warranty remains unverified." in loaded["text"]
            other = OwnerResearchContext(
                agent_name="GeneralShoppingAgent",
                run_id=other_run,
                brief=context.brief,
                region_code="PH",
                session_factory=factory,
                research_state=state,
            )
            assert other.read_bundle(consultation_id)["status"] == "unknown_source"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_owner_missing_page_original_keeps_explicit_unreviewed_gap(
    tmp_path: Path,
) -> None:
    from app.agents.owner_research import OwnerResearchContext

    engine, factory, run_id, _ = await _database(tmp_path)
    source = _generic_result()
    context = OwnerResearchContext(
        agent_name="GeneralShoppingAgent",
        run_id=run_id,
        brief=ShoppingBrief(original_query="Compare"),
        region_code=None,
        session_factory=factory,
        allowed_source_ids=lambda: frozenset({source.source_id}),
    )
    try:
        async with factory() as session:
            await SearchSourceRepository(session).add_search_result(run_id, source)
            await session.commit()
        result = await context.read_source(str(source.source_id))
        assert result["text"] is None and result["unreviewed_content"] is True
        assert (
            result["gap"]
            == "Page original is unavailable or has no extracted text. Page claims and safety remain unreviewed."
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sdk_long_page_cautions_stay_bounded_and_late_warning_is_retrievable(
    tmp_path: Path,
) -> None:
    from app.agents.context_management import context_scope, prepare_history
    from app.agents.owner_research import OwnerResearchContext
    from app.agents.research_history import active_history

    engine, factory, run_id, _ = await _database(tmp_path)
    source = _generic_result()
    exact_price = "Price PHP 90000."
    late_warning = "No local warranty."
    text = (
        exact_price
        + " "
        + "長いナビゲーション " * 6000
        + "Risk hidden in a long original sentence. "
    )
    text += (
        " ".join(f"Seller risk {index} remains unverified." for index in range(40))
        + " "
        + late_warning
    )
    snapshot = SourceSnapshot(
        url=source.url,
        source_type=SourceType.PRODUCT_PAGE,
        provider=ProviderMetadata(provider_name="fixture"),
        extraction_status=ExtractionStatus.SUCCEEDED,
        extracted_content=ExtractedPageContent(
            text=text, extractor="fixture", word_count=8000
        ),
    )
    research = AgentResearchTools(
        agent_name="GeneralShoppingAgent",
        run_id=run_id,
        session_factory=factory,
        search_provider=RecordingSearchProvider(),
        extraction_provider=RecordingExtractionProvider(),
    )
    owner = OwnerResearchContext(
        agent_name="GeneralShoppingAgent",
        run_id=run_id,
        brief=ShoppingBrief(original_query="Compare phone"),
        region_code=None,
        session_factory=factory,
        allowed_source_ids=lambda: frozenset({source.source_id}),
    )
    try:
        async with factory() as session:
            repo = SearchSourceRepository(session)
            await repo.add_search_result(run_id, source)
            await repo.add_source_snapshot(
                run_id, snapshot, search_result_id=source.source_id
            )
            await session.commit()
        with context_scope():
            research_sdk = {tool.name: tool for tool in research.sdk_owner_tools()}
            owner_sdk = {tool.name: tool for tool in owner.sdk_tools()}
            arguments = json.dumps(
                {"source_id": str(source.source_id), "start_char": 0, "focus": None}
            )
            raw = await research_sdk["fetch_source"].on_invoke_tool(
                ToolContext(
                    context=None,
                    tool_name="fetch_source",
                    tool_call_id="long-fetch",
                    tool_arguments=arguments,
                ),
                arguments,
            )
            fetched = json.loads(raw)
            assert len(raw) < 8500 and len(fetched["text"]) == 4000
            assert len(fetched["material_cautions"]) == 6
            assert all(
                len(caution) <= 300 and caution in text
                for caution in fetched["material_cautions"]
            )
            assert (
                fetched["cautions_truncated"] is True
                and fetched["deferred_caution_count"] >= 35
            )
            assert (
                fetched["unreviewed_cautions"] is True
                and fetched["unreviewed_content"] is True
            )
            assert (
                "warranty" in fetched["caution_focus_terms"]
                and late_warning not in fetched["text"]
            )
            view_id = fetched["_research_view"]["view_id"]
            assert (
                active_history().complete(view_id, [exact_price])["status"]
                == "processed"
            )
            history = prepare_history(
                [
                    {
                        "type": "function_call",
                        "name": "fetch_source",
                        "call_id": "long-fetch",
                        "arguments": arguments,
                    },
                    {
                        "type": "function_call_output",
                        "call_id": "long-fetch",
                        "output": raw,
                    },
                ]
            )
            retired = json.loads(history[1]["output"])
            assert (
                len(history[1]["output"]) < len(raw)
                and retired["status"] == "processed"
            )
            assert "unreviewed" in retired["retained"]["coverage"]
            evidence_args = json.dumps(
                {
                    "source_id": str(source.source_id),
                    "start_char": 0,
                    "focus": None,
                    "evidence_offset": 0,
                }
            )
            evidence_raw = await owner_sdk["read_run_evidence"].on_invoke_tool(
                ToolContext(
                    context=None,
                    tool_name="read_run_evidence",
                    tool_call_id="long-evidence",
                    tool_arguments=evidence_args,
                ),
                evidence_args,
            )
            evidence = json.loads(evidence_raw)
            assert len(evidence_raw) < 6500 and evidence["unreviewed_cautions"] is True
            assert (
                len(evidence["material_cautions"]) <= 6
                and "warranty" in evidence["caution_focus_terms"]
            )
            focused_args = json.dumps(
                {
                    "source_id": str(source.source_id),
                    "start_char": 0,
                    "focus": "No local warranty",
                }
            )
            focused_raw = await research_sdk["fetch_source"].on_invoke_tool(
                ToolContext(
                    context=None,
                    tool_name="fetch_source",
                    tool_call_id="late-warning",
                    tool_arguments=focused_args,
                ),
                focused_args,
            )
            focused = json.loads(focused_raw)
            assert (
                len(focused_raw) < 8500
                and late_warning in focused["text"]
                and focused["start_char"] > 4000
            )
            quote = await research.record_quote(source.source_id, late_warning)
            assert quote.quote == late_warning and quote.evidence_id is not None
            async with factory() as session:
                durable = await SearchSourceRepository(
                    session
                ).get_source_snapshot_for_run(run_id, snapshot.source_id)
                assert durable.extracted_content.text == text
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_owner_bundle_and_note_caution_descriptors_survive_positive_quote_retirement(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace
    from app.agents.context_management import context_scope, prepare_history
    from app.agents.owner_research import OwnerResearchContext, OwnerResearchState
    from app.agents.research_history import active_history
    from app.db.repositories.products import ProductRepository
    from app.schemas.products import CanonicalProduct
    from app.schemas.search_sources import VideoReviewEvidenceBundle

    engine, factory, run_id, _ = await _database(tmp_path)
    product = CanonicalProduct(name="Test Phone", category="smartphone")
    positive = "Verified official offer"
    hidden = "Imported warranty concern."
    late = "No local warranty."
    long_passage = positive + " " + "詳細情報 " * 1200 + hidden
    warnings = (
        (long_passage,)
        + tuple(f"Seller risk {index} remains unverified." for index in range(12))
        + (late, "正規の返品受付は不可。")
    )
    bundle = VideoReviewEvidenceBundle(transcript_gap_notes=warnings)
    state = OwnerResearchState()

    class Manager:
        async def run(self, _input):
            return SimpleNamespace(
                video_bundles=(bundle,),
                community_bundles=(),
                amazon_bundles=(),
                ikea_bundles=(),
                activity=(),
                notes=warnings,
                model_name="offline-fixture",
                total_tokens=0,
            )

    context = OwnerResearchContext(
        agent_name="GeneralShoppingAgent",
        run_id=run_id,
        brief=ShoppingBrief(original_query="Compare phone"),
        region_code="PH",
        session_factory=factory,
        source_manager=Manager(),
        research_state=state,
    )
    try:
        async with factory() as session:
            await ProductRepository(session).add_canonical_product(run_id, product)
            await session.commit()
        with context_scope():
            tools = {tool.name: tool for tool in context.sdk_tools()}
            args = json.dumps(
                {
                    "capability": "video_review",
                    "product_id": str(product.product_id),
                    "product_name": None,
                    "evidence_id": None,
                }
            )
            raw = await tools["consult_source_intelligence"].on_invoke_tool(
                ToolContext(
                    context=None,
                    tool_name="consult_source_intelligence",
                    tool_call_id="consult-cautions",
                    tool_arguments=args,
                ),
                args,
            )
            preview = json.loads(raw)
            assert len(raw) <= 12000
            for caution_view in (preview, preview["bundles"][0]):
                assert len(caution_view["material_cautions"]) <= 6
                assert all(
                    len(item) <= 300 for item in caution_view["material_cautions"]
                )
                assert any(hidden in item for item in caution_view["material_cautions"])
                assert caution_view["cautions_truncated"] is True
                assert caution_view["deferred_caution_count"] >= 8
                assert caution_view["unreviewed_cautions"] is True
                assert "warranty" in caution_view["caution_focus_terms"]
            assert preview["caution_scope"] == "consultation_notes"
            assert preview["bundles"][0]["caution_scope"] == "original_bundle"
            history = active_history()
            assert (
                history.complete(preview["_research_view"]["view_id"], [positive])[
                    "status"
                ]
                == "processed"
            )
            prepared = prepare_history(
                [
                    {
                        "type": "function_call",
                        "name": "consult_source_intelligence",
                        "call_id": "consult-cautions",
                        "arguments": args,
                    },
                    {
                        "type": "function_call_output",
                        "call_id": "consult-cautions",
                        "output": raw,
                    },
                ]
            )
            retained = json.loads(prepared[1]["output"])["retained"]
            assert (
                retained["cautions_truncated"] is True
                and retained["deferred_caution_count"] >= 8
            )
            assert (
                "warranty" in retained["caution_focus_terms"]
                and "unreviewed" in retained["coverage"]
            )
            for original_id, original_hash in (
                (str(bundle.bundle_id), preview["bundles"][0]["content_sha256"]),
                (preview["consultation_id"], preview["consultation_sha256"]),
            ):
                args = json.dumps(
                    {
                        "bundle_id": original_id,
                        "start_char": 0,
                        "focus": None,
                        "content_sha256": original_hash,
                    }
                )
                read_raw = await tools["read_source_bundle"].on_invoke_tool(
                    ToolContext(
                        context=None,
                        tool_name="read_source_bundle",
                        tool_call_id="original-" + original_id,
                        tool_arguments=args,
                    ),
                    args,
                )
                read = json.loads(read_raw)
                assert len(read_raw) < 8500 and late not in read["text"]
                assert (
                    read["cautions_truncated"] is True
                    and read["deferred_caution_count"] >= 8
                )
                assert (
                    read["unreviewed_cautions"] is True
                    and "warranty" in read["caution_focus_terms"]
                )
                assert any(hidden in item for item in read["material_cautions"])
                assert (
                    history.complete(read["_research_view"]["view_id"], [positive])[
                        "status"
                    ]
                    == "processed"
                )
                args = json.dumps(
                    {
                        "bundle_id": original_id,
                        "start_char": 0,
                        "focus": late,
                        "content_sha256": original_hash,
                    }
                )
                focused = json.loads(
                    await tools["read_source_bundle"].on_invoke_tool(
                        ToolContext(
                            context=None,
                            tool_name="read_source_bundle",
                            tool_call_id="focused-" + original_id,
                            tool_arguments=args,
                        ),
                        args,
                    )
                )
                assert late in focused["text"] and focused["start_char"] > 4000
                assert (
                    focused["cautions_truncated"] is True
                    and focused["unreviewed_cautions"] is True
                )
                assert state.bundle_versions[(original_id, original_hash)][1]
    finally:
        await engine.dispose()
