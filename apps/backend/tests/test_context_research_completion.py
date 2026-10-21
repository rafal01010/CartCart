import json
from dataclasses import dataclass, replace
from math import ceil
from pathlib import Path
from unittest.mock import patch

import pytest
from agents.items import ModelResponse
from agents.models.interface import Model, ModelProvider
from agents.usage import Usage
from sqlalchemy.ext.asyncio import create_async_engine

import app.db.models  # noqa: F401
from app.agents import context_management
from app.agents.context_management import (
    BoundedRunner,
    ContextBudget,
    ContextLimits,
    context_scope,
)
from app.agents.decision_sources import input_projection
from app.agents.context_metrics import measure
from app.agents.research_history import ResearchHistory
from app.agents.contracts import (
    ComparisonDecisionAgentInput,
    GeneralShoppingAgentInput,
    GeneralShoppingOutcome,
    VerificationAgentInput,
)
from app.agents.live_comparison_decision import LiveComparisonDecisionAgent
from app.agents.live_general_shopping import LiveGeneralShoppingAgent
from app.agents.live_verifier_critic import LiveVerifierCriticAgent
from app.agents.extraction_tools import SnapshotInterpretationTools
from app.agents.research_tools import (
    AgentResearchTools,
    SearchSourcesResult,
    _tool_source,
)
from app.db.base import Base
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_session_factory
from app.schemas.intake import (
    CreateSessionRequest,
    FieldSource,
    RegionPreference,
    ShoppingBrief,
)
from app.schemas.regions import Region
from app.schemas.ids import new_id
from app.schemas.analysis import RecommendationMode
from app.schemas.search_sources import (
    ExtractedPageContent,
    ExtractionStatus,
    ProviderMetadata,
    SearchIntent,
    SearchQuery,
    SearchResult,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
)
from test_context_decision_fidelity import (
    _call,
    _message,
    _owner_bundle,
    _settings,
    _tool_results,
)


@dataclass(frozen=True)
class ResearchCase:
    category: str
    selected_name: str
    competitor_name: str
    imported_name: str
    good_quote: str
    review_quote: str
    unsafe_quote: str


PHONE = ResearchCase(
    "smartphone",
    "Aster Pro 512GB PH",
    "Beryl Max 512GB PH",
    "Aster Pro imported 256GB",
    "Aster Pro 512GB PH has a two year local warranty and lasts a full day.",
    "Aster Pro 512GB PH has weaker low-light photos than Beryl Max 512GB PH.",
    "Aster Pro imported 256GB costs PHP 90000. No local warranty. This is not the PH 512GB variant.",
)
LAMP = ResearchCase(
    "reading lamp",
    "Amber Desk Lamp PH",
    "Beryl Reading Lamp PH",
    "Amber Desk Lamp imported",
    "Amber Desk Lamp PH has a two year local warranty and even light for reading.",
    "Amber Desk Lamp PH is dimmer for detailed work than Beryl Reading Lamp PH.",
    "Amber Desk Lamp imported costs PHP 4999. No local warranty. The seller is unverified.",
)


class SavedShapeSearch:
    provider_name = "offline-search"

    def __init__(self, case, snippet_chars=950):
        self.calls = []
        self.leads = []
        for index in range(16):
            name = (case.competitor_name, case.imported_name, case.selected_name)[
                index % 3
            ]
            if index == 15:
                name = case.selected_name
            detail = f"{name}. Philippine model and seller comparison. Cámara, garantía, 家用購入比較庫. "
            snippet = (detail * 30)[:snippet_chars]
            if index == 0:
                snippet += " Unverified claim: Ten day battery life."
            if index == 15:
                snippet += " Later official lead. Two year local warranty."
            if index == 1:
                snippet += " No local warranty. Seller identity unverified."
            self.leads.append(
                SearchResult(
                    query=SearchQuery(
                        query=f"query-{index // 6}",
                        intent=SearchIntent.DISCOVERY,
                        region_code="PH",
                    ),
                    url=f"https://{'official.example.com' if index == 15 else 'reviews.example.org'}/lead-{index}",
                    title=f"{name} {case.category} | {'Official PH store' if index == 15 else f'Offer {index}'}",
                    snippet=snippet,
                    source_type=SourceType.PRODUCT_PAGE
                    if index == 15
                    else SourceType.PROFESSIONAL_REVIEW,
                    provider=ProviderMetadata(
                        provider_name=self.provider_name,
                        raw={
                            "private_vendor_debug": "must-not-enter-prompt",
                            "rank": index,
                        },
                    ),
                    quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.8),
                )
            )

    async def search(self, query, options=None):
        self.calls.append(query.query)
        group = int(query.query.rsplit(" ", 1)[-1])
        return tuple(self.leads[(0, 5, 10)[group] : (5, 10, 16)[group]])


class SavedShapeExtraction:
    provider_name = "offline-extraction"

    def __init__(self, case):
        self.case = case

    async def extract(self, url, options=None):
        index = int(str(url).rsplit("-", 1)[-1])
        quote = {
            15: self.case.good_quote,
            0: self.case.review_quote,
            1: self.case.unsafe_quote,
        }[index]
        text = (
            quote
            + " Catalogue navigation, accessory compatibility and shipping terms. "
            * 120
        )
        return SourceSnapshot(
            url=url,
            title="Canonical offline page",
            source_type=options.source_type,
            provider=ProviderMetadata(provider_name=self.provider_name),
            extraction_status=ExtractionStatus.SUCCEEDED,
            extracted_content=ExtractedPageContent(
                text=text, extractor="offline", word_count=len(text.split())
            ),
        )


class OriginalSearchResult(SearchSourcesResult):
    def model_dump_json(self, **kwargs):
        payload = self.model_dump(mode="json")
        fields = {
            "source_id",
            "url",
            "title",
            "snippet",
            "provider_source_type",
            "provider_name",
        }
        return json.dumps(
            {
                "status": payload["status"],
                "sources": [
                    {key: value for key, value in source.items() if key in fields}
                    for source in payload["sources"]
                ],
                "gap": payload["gap"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


class OriginalSearchTools(AgentResearchTools):
    def for_agent(self, agent_name):
        receiving = super().for_agent(agent_name)
        receiving.__class__ = OriginalSearchTools
        return receiving

    async def search(self, request):
        result = await super().search(request)
        if result.status != "succeeded":
            return result
        async with self._session() as session:
            originals = await SearchSourceRepository(session).list_search_results(
                self._run_id
            )
        selected = [item for item in originals if item.query.query == request.query]
        return OriginalSearchResult(
            status=result.status,
            sources=tuple(
                _tool_source(item, "offline-search").model_copy(
                    update={"snippet": item.snippet, "material_cautions": ()}
                )
                for item in selected
            ),
            gap=result.gap,
        )


class AcceptanceModel(Model):
    def __init__(self, steps):
        self.steps = list(steps)
        self.inputs = []
        self.transport = []

    async def get_response(
        self,
        instructions,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing,
        **kwargs,
    ):
        self.inputs.append(json.loads(json.dumps(input)))
        items = [] if isinstance(input, str) else input
        schemas = context_management._schema_payload(tools, output_schema, handoffs)
        components = {
            "instructions": measure(instructions or ""),
            "schemas": measure(schemas),
            "active_history": measure(input),
        }
        simulated_input = ceil(
            sum(item["characters"] for item in components.values()) / 4
        )
        self.transport.append(
            {
                "components": components,
                "tool_output_characters": sum(
                    len(item.get("output", ""))
                    for item in items
                    if isinstance(item, dict)
                    and item.get("type") == "function_call_output"
                ),
                "simulated_input_tokens": simulated_input,
                "simulated_output_tokens": 100,
                "search_calls_in_history": sum(
                    item.get("name") == "search_sources"
                    for item in items
                    if isinstance(item, dict)
                ),
                "fetch_calls_in_history": sum(
                    item.get("name") == "fetch_source"
                    for item in items
                    if isinstance(item, dict)
                ),
            }
        )
        if (instructions or "").startswith("Select useful exact passages"):
            output = _message({"spans": []})
        else:
            assert self.steps, (
                "Unexpected model call beyond independently scripted outcome."
            )
            step = self.steps.pop(0)
            output = step(input, handoffs) if callable(step) else step
        return ModelResponse(
            output=output,
            response_id=None,
            usage=Usage(
                requests=1,
                input_tokens=simulated_input,
                output_tokens=100,
                total_tokens=simulated_input + 100,
            ),
        )

    async def stream_response(self, *args, **kwargs):
        raise AssertionError("Acceptance forbids streaming and live calls.")
        yield


class AcceptanceProvider(ModelProvider):
    def __init__(self, models):
        self.models = models

    def get_model(self, model_name):
        return self.models[model_name]


class AcceptanceRunner:
    def __init__(self, models):
        self.provider = AcceptanceProvider(models)

    async def run(self, agent, model_input, *, run_config, max_turns):
        return await BoundedRunner.run(
            agent,
            model_input,
            run_config=replace(
                run_config, model_provider=self.provider, tracing_disabled=True
            ),
            max_turns=max_turns,
        )


def _assert_context_complete(events):
    calls = [event for event in events if event["tool_name"] == "context_call"]
    assert calls and all(event["status"] == "completed" for event in calls)
    selections = [event for event in events if event["tool_name"] == "decision_source_selection"]
    assert all(event["status"] == "transported" for event in selections)


def _find_sources(input):
    projection = input_projection(input)
    if projection is not None:
        return [
            {**packet.model_dump(mode="json"), "snippet": "\n".join(packet.excerpts)}
            for packet in projection.sources
        ]
    return [
        source
        for result in _tool_results(input)
        for source in result.get("sources", [])
    ]


def _visible_archive_views(input):
    names = {item.get("call_id"): item.get("name") for item in input if isinstance(item, dict) and item.get("type") == "function_call"}
    return [
        {**json.loads(item["output"]), "_research_view": {"view_id": json.loads(item["output"])["archive_view_id"], "tool": names.get(item.get("call_id"))}}
        for item in input
        if isinstance(item, dict) and item.get("type") == "function_call_output"
        and isinstance(item.get("output"), str) and item["output"].startswith("{")
        and json.loads(item["output"]).get("archive_view_id")
    ]


async def run_saved_shape(case, mode, *, snippet_chars=950):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    brief = ShoppingBrief(
        original_query=f"Buy a {case.category} in the Philippines, budget is not a problem",
        category=case.category,
        category_source=FieldSource.INFERRED,
        region=RegionPreference(
            region=Region(country_code="PH"), source=FieldSource.USER_PROVIDED
        ),
    )
    async with factory() as session:
        shopping_session = await SessionRepository(session).create(
            original_input=CreateSessionRequest(query=brief.original_query),
            current_brief=brief,
        )
        run = await RunRepository(session).create(shopping_session.session_id)
        await session.commit()
    search = SavedShapeSearch(case, snippet_chars)
    extraction = SavedShapeExtraction(case)
    tools_type = AgentResearchTools if mode == "repair" else OriginalSearchTools
    created_tools = []

    def research_tools(run_id, region_code, agent_name="GeneralShoppingAgent"):
        tools = tools_type(
            agent_name=agent_name,
            run_id=run_id,
            session_factory=factory,
            required_region_code=region_code,
            search_provider=search,
            extraction_provider=extraction,
        )
        created_tools.append(tools)
        return tools

    known_sources = {}
    views = {}

    def observe(input):
        for source in _find_sources(input):
            known_sources[source["url"].rsplit("-", 1)[-1]] = source
        for result in [*_tool_results(input), *_visible_archive_views(input)]:
            if result.get("source_id"):
                for index, original in enumerate(search.leads):
                    if str(original.source_id) == result["source_id"] and str(index) not in known_sources:
                        known_sources[str(index)] = {"source_id": result["source_id"]}
            if result.get("source_id") and result.get("url") and result.get("snippet"):
                known_sources[result["url"].rsplit("-", 1)[-1]] = result
            if result.get("_research_view"):
                views[result["_research_view"]["view_id"]] = result

    def checkpoint(tool, facts=None):
        def complete(input, handoffs):
            observe(input)
            view_id, result = next(
                (key, value)
                for key, value in reversed(list(views.items()))
                if value["_research_view"]["tool"] == tool
            )
            selected = (
                facts
                if facts
                else [item["title"] for item in result.get("sources", [])][:1]
            )
            return _call(
                "complete_research_result",
                {"view_id": view_id, "retained_facts": selected},
            )

        return complete

    steps = []
    for index in range(3):
        steps.append(
            _call(
                "search_sources",
                {
                    "query": f"{case.category} PH distinct search {index}",
                    "intent": "discovery",
                    "region_code": "PH",
                    "max_results": 6,
                },
            )
        )

    def complete_many(tool, facts_by_source=None):
        def complete(input, handoffs):
            observe(input)
            outputs = []
            for view_id, result in views.items():
                if result["_research_view"]["tool"] != tool:
                    continue
                facts = (
                    facts_by_source[result["source_id"]]
                    if facts_by_source
                    else [item["title"] for item in result.get("sources", [])][:1] or [source["title"] for source in known_sources.values()][:1]
                )
                outputs.extend(
                    _call(
                        "complete_research_result",
                        {"view_id": view_id, "retained_facts": facts},
                    )
                )
            return outputs

        return complete

    if mode == "repair":
        steps.append(complete_many("search_sources"))

        def later_page(input, handoffs):
            observe(input)
            projection = input_projection(input)
            assert projection is not None
            visible_ids = {
                identifier
                for packet in projection.sources
                for identifier in (packet.source_id, *packet.equivalent_source_ids)
            } | set(projection.deferred_source_ids) | {
                identifier for result in _tool_results(input)
                for identifier in result.get("deferred_source_ids", [])
            }
            visible_ids = {str(identifier) for identifier in visible_ids}
            requested = [
                source for index in (15, 0, 1)
                if str(index) not in known_sources
                for source in (search.leads[index],)
            ]
            assert all(str(source.source_id) in visible_ids for source in requested)
            return (
                _call("search_sources", {
                    "query": f"{case.category} PH distinct search 2",
                    "intent": "discovery", "region_code": "PH", "max_results": 6,
                })
                + [call for source in requested for call in _call(
                    "read_search_results", {"source_id": str(source.source_id)}
                )]
            )

        steps.append(later_page)

    def source_call(index, name, **args):
        def selected(input, handoffs):
            observe(input)
            source = known_sources[str(index)]
            return _call(name, {"source_id": source["source_id"], **args})

        return selected

    sources_and_quotes = (
        (15, case.good_quote),
        (0, case.review_quote),
        (1, case.unsafe_quote),
    )
    if mode == "repair":

        def fetch_many(input, handoffs):
            observe(input)
            return [
                call
                for index, quote in sources_and_quotes
                for call in source_call(index, "fetch_source", focus=quote[:50])(
                    input, handoffs
                )
            ]

        def quote_many(input, handoffs):
            observe(input)
            return [
                call
                for index, quote in sources_and_quotes
                for call in source_call(index, "record_source_quote", quote=quote)(
                    input, handoffs
                )
            ]

        def complete_fetches(input, handoffs):
            observe(input)
            return complete_many(
                "fetch_source",
                {
                    known_sources[str(index)]["source_id"]: [quote]
                    for index, quote in sources_and_quotes
                },
            )(input, handoffs)

        def interpret_and_quote(input, handoffs):
            projection = input_projection(input)
            diagnostic = Path(__file__).resolve().parents[3] / "data/artifacts/task212" / f"source-interpret-{case.category.replace(' ', '-')}.json"
            diagnostic.write_text(json.dumps(projection.model_dump(mode="json") if projection else input, indent=2))
            for _, quote in sources_and_quotes:
                assert quote in json.dumps(input)
            return (
                quote_many(input, handoffs)
                + complete_fetches(input, handoffs)
                + source_call(1, "fetch_source", start_char=4000)(input, handoffs)

            )

        steps.extend([fetch_many, interpret_and_quote])
    else:
        for index, quote in sources_and_quotes:
            steps.append(source_call(index, "fetch_source", focus=quote[:50]))
            steps.append(source_call(index, "record_source_quote", quote=quote))

    def decision(input, handoffs):
        payload = json.dumps(input, ensure_ascii=False)
        assert "must-not-enter-prompt" not in payload
        for quote in (case.good_quote, case.review_quote, case.unsafe_quote):
            assert quote in payload
        results = _tool_results(input)
        if mode == "repair":
            projection = input_projection(input)
            assert projection is not None
            assert case.unsafe_quote in " ".join(caution for source in projection.sources for caution in source.material_cautions)
        projection = input_projection(input)
        recorded = ([{"evidence_id": str(identifier)} for source in projection.sources for identifier in source.evidence_ids]
                    if projection is not None else [item for item in results if item.get("evidence_id")])
        recorded = list({item["evidence_id"]: item for item in recorded}.values())
        assert len(recorded) == 3
        return _message(
            {
                "category": case.category,
                "selected_candidate_name": case.selected_name,
                "candidates": [
                    {
                        "name": case.selected_name,
                        "choice_group": "primary",
                        "evidence_ids": [str(identifier) for source in projection.sources if source.source_id in {search.leads[0].source_id, search.leads[15].source_id} for identifier in source.evidence_ids] if projection is not None else [item["evidence_id"] for item in recorded],
                    }
                ],
                "rationale": case.good_quote + " " + case.review_quote,
                "evidence_gap": "Imported offer has no local warranty and remains excluded.",
            }
        )

    steps.append(decision)
    model = AcceptanceModel(steps)
    models = {"gpt-6-luna" if case == PHONE else "gpt-6-sol": model}
    if case == PHONE:

        def general_handoff(input, handoffs):
            return _call(
                handoffs[0].tool_name,
                {
                    "reason": "Compare phone warranty and PH variants.",
                },
            )

        def specialist_handoff(input, handoffs):
            target = next(
                item
                for item in handoffs
                if item.agent_name == "SmartphoneSpecialistAgent"
            )
            return _call(
                target.tool_name,
                {
                    "reason": "Compare phone warranty and PH variants.",
                },
            )

        models.update(
            {
                "gpt-6-sol": AcceptanceModel([general_handoff]),
                "gpt-6-astra": AcceptanceModel([specialist_handoff]),
            }
        )
    settings = _settings().model_copy(update={"openai_agent_max_turns": 40})
    owner = LiveGeneralShoppingAgent(
        settings=settings,
        session_factory=factory,
        regional_research_tools_factory=research_tools,
        technology_research_tools_factory=lambda run_id, region: research_tools(
            run_id, region, "TechnologyDomainAnalystAgent"
        ),
        model_runner=AcceptanceRunner(models),
    )
    limits = (
        ContextLimits()
        if mode == "repair"
        else replace(
            ContextLimits(),
            input_tokens=16000 if mode == "old" else 19000,
            decision_reserve=21000 if mode == "old" else 24000,
            verification_reserve=21000 if mode == "old" else 24000,
        )
    )
    budget = ContextBudget(limits=limits)
    error = None
    draft = None
    baseline_history = []

    def preserve_history(items):
        baseline_history.append(
            {
                "search_calls_in_history": sum(
                    item.get("name") == "search_sources" for item in items
                ),
                "fetch_calls_in_history": sum(
                    item.get("name") == "fetch_source" for item in items
                ),
                "tool_output_characters": sum(
                    len(item.get("output", ""))
                    for item in items
                    if item.get("type") == "function_call_output"
                ),
            }
        )
        return items

    async def preserve_legacy_context(self, prepared, *args, **kwargs):
        return prepared, {"status": "irreducible"}

    try:
        if mode == "repair":
            with context_scope(budget):
                draft = await owner.run(
                    GeneralShoppingAgentInput(run_id=run.run_id, brief=brief)
                )
        else:
            with (
                patch.object(
                    context_management, "prepare_history", side_effect=preserve_history
                ),
                patch.object(
                    ResearchHistory,
                    "register",
                    side_effect=lambda tool, output, **kwargs: output,
                ),
                patch.object(
                    context_management.BudgetedModel,
                    "_shorten",
                    preserve_legacy_context,
                ),
                patch.object(context_management, "project_owner_sources", side_effect=lambda value: (value, None)),
                context_scope(budget),
            ):
                draft = await owner.run(
                    GeneralShoppingAgentInput(run_id=run.run_id, brief=brief)
                )
    except context_management.ContextBudgetExceeded as exc:
        error = str(exc)
    error = error or next(
        (
            event["status"]
            for event in budget.events
            if event["status"].startswith("blocked")
        ),
        None,
    )
    async with factory() as session:
        originals = await SearchSourceRepository(session).list_search_results(
            run.run_id
        )
        snapshots = await SearchSourceRepository(session).list_source_snapshots(
            run.run_id
        )
    report = {
        "case": case.category,
        "mode": mode,
        "search_calls": len(search.calls),
        "durable_leads": len(originals),
        "original_snippet_characters": sum(
            len(item.snippet or "") for item in originals
        ),
        "transport": {name: item.transport for name, item in models.items()},
        "budget_events": budget.events,
        "simulated_total_tokens": budget.spent,
        "reserved_tokens": budget.reserved,
        "blocked": error,
        "owner_outcome": draft.outcome.value if draft else None,
        "owner_activity": list(owner.workbench_activity),
        "snapshots": len(snapshots),
        "post_search_tool_characters": next(
            (
                item["tool_output_characters"]
                for item in (model.transport if mode == "repair" else baseline_history)
                if item["search_calls_in_history"] == len(search.calls)
                and item["fetch_calls_in_history"] == 0
            ),
            budget.events[-1].get("output", {}).get("input_breakdown", {}).get(
                "characters_by_component", {}
            ).get("tool_results", 0),
        ),
    }
    artifact = Path(__file__).resolve().parents[3] / "data/artifacts/task212" / f"context-replay-{case.category.replace(' ', '-')}-{mode}.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(report, indent=2, default=str) + "\n")
    if mode == "repair":
        activity = owner.workbench_activity
        fetches = [item for item in activity if item.get("tool_name") == "fetch_source"]
        assert len(fetches) == 4 and fetches[-1]["status"] == "cached", [(item.get("tool_name"), item.get("status")) for item in owner.workbench_activity]
        quotes = [item for item in activity if item.get("tool_name") == "record_source_quote"]
        assert len(quotes) == 3 and all(item["status"] == "succeeded" for item in quotes)
    if draft is not None and draft.outcome == GeneralShoppingOutcome.DRAFT:
        report["selected_candidate"] = draft.selected_candidate_name
        report["cited_quotes"] = [item.quote for item in draft.candidates[0].evidence]
        assert draft.selected_candidate_name == case.selected_name
        assert set(report["cited_quotes"]) == {case.good_quote, case.review_quote}
        assert [
            item["status"]
            for item in owner.workbench_activity
            if item["tool_name"] == "sdk_handoff"
        ] == (["completed", "completed"] if case == PHONE else [])
        bundle, context = await _owner_bundle(
            factory, shopping_session, run, brief, owner, draft
        )
        async with factory() as session:
            evidence = await SearchSourceRepository(session).list_source_evidence(
                run.run_id
            )
            originals_again = await SearchSourceRepository(session).list_search_results(
                run.run_id
            )
            assert [item.snippet for item in originals_again] == [
                item.snippet for item in originals
            ]
            assert len({item.source_id for item in originals}) == 16
            for original in originals:
                fetched = json.loads(
                    await created_tools[0].read_search_results(
                        source_id=str(original.source_id)
                    )
                )
                assert fetched["status"] == "succeeded"
                assert fetched["snippet"] == original.snippet
            assert any("No local warranty." in item.claim for item in evidence)
            value_mode = bundle.mode_results[0].model_copy(
                update={
                    "mode": RecommendationMode.BEST_VALUE,
                    "title": "Best value",
                    "rationale": case.good_quote,
                }
            )
            bundle = bundle.model_copy(
                update={
                    "primary_product_ids": (bundle.final_product_id,),
                    "mode_results": (*bundle.mode_results, value_mode),
                    "warnings": (case.unsafe_quote,),
                    "evidence_ids": tuple(item.evidence_id for item in evidence),
                    "source_ids": tuple(item.source_id for item in evidence),
                }
            )
            comparison_model = AcceptanceModel(
                [_message(bundle.model_dump(mode="json"))]
            )
            verifier_model = AcceptanceModel([])
            with context_scope(budget):
                compared = await LiveComparisonDecisionAgent(
                    settings,
                    model_runner=AcceptanceRunner({"gpt-6-sol": comparison_model}),
                ).run(
                    ComparisonDecisionAgentInput(
                        run_id=run.run_id,
                        brief=brief,
                        products=context.owner_products,
                        evidence=evidence,
                    )
                )
                report["comparison_selected"] = str(compared.final_product_id)
                verifier_model.steps.append(
                    _message(
                        {
                            "approved": True,
                        }
                    )
                )
                verified = await LiveVerifierCriticAgent(
                    settings=settings,
                    model_runner=AcceptanceRunner({"gpt-6-sol": verifier_model}),
                    snapshot_tools_factory=lambda _: SnapshotInterpretationTools(
                        run_id=run.run_id,
                        allowed_snapshot_ids=tuple(
                            item.source_id for item in snapshots
                        ),
                        shared_session=session,
                        agent_name="VerifierCriticAgent",
                    ),
                ).run(
                    VerificationAgentInput(
                        run_id=run.run_id,
                        brief=brief,
                        recommendation_bundle=compared,
                        products=context.owner_products,
                        evidence=evidence,
                    )
                )
            assert compared.final_product_id == context.owner_products[0].product_id
            assert verified.approved, verified.blocking_issues
            assert (
                verified.recommendation_bundle.final_rationale
                == compared.final_rationale
            )
            assert case.unsafe_quote in verified.recommendation_bundle.warnings
            report["verifier_approved"] = verified.approved
            report["transport"]["comparison"] = comparison_model.transport
            report["transport"]["verifier"] = verifier_model.transport
            report["simulated_total_tokens"] = budget.spent
            report["reserved_tokens"] = budget.reserved
    artifact = Path(__file__).resolve().parents[3] / "data/artifacts/task212" / f"context-replay-{case.category.replace(' ', '-')}-{mode}.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(report, indent=2, default=str) + "\n")
    await engine.dispose()
    return report


@pytest.mark.asyncio
async def test_saved_shape_old_limit_blocks_before_research_completes():
    result = await run_saved_shape(PHONE, "old")
    assert result["search_calls"] == 2
    assert result["durable_leads"] == 10
    assert result["blocked"] is not None
    assert result["reserved_tokens"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", [PHONE, LAMP], ids=["phone_handoffs", "generic_category"]
)
async def test_saved_shape_repair_keeps_late_lead_cited_decision_and_warnings(case):
    old = await run_saved_shape(case, "old")
    headroom = await run_saved_shape(case, "headroom")
    repaired = await run_saved_shape(case, "repair")
    assert old["search_calls"] == 2
    assert old["durable_leads"] == 10
    assert headroom["search_calls"] == 2
    assert headroom["durable_leads"] == 10
    assert repaired["search_calls"] == 3, {key: repaired[key] for key in ("search_calls", "durable_leads", "blocked", "owner_outcome", "owner_activity")}
    assert repaired["durable_leads"] == 16
    assert old["blocked"] == headroom["blocked"] == "blocked_closed_research"
    assert repaired["blocked"] is None
    assert (
        repaired["post_search_tool_characters"]
        <= old["post_search_tool_characters"] / 2
    )
    assert repaired["owner_outcome"] == "draft", [(item.get("tool_name"), item.get("status"), item.get("output")) for item in repaired["owner_activity"] if item.get("tool_name") == "general_owner"]
    assert repaired["selected_candidate"] == case.selected_name
    assert repaired["verifier_approved"] is True
    assert repaired["simulated_total_tokens"] < 150_000
    assert repaired["reserved_tokens"] == 0
    assert all(
        event["output"]["estimated_input_tokens"] <= ContextLimits().input_tokens
        for event in repaired["budget_events"] if event["tool_name"] == "context_call"
    )
    assert set(repaired["cited_quotes"]) == {case.good_quote, case.review_quote}
    _assert_context_complete(repaired["budget_events"])
    actual_transports = [
        item for calls in repaired["transport"].values() for item in calls
    ]
    assert repaired["simulated_total_tokens"] == sum(
        item["simulated_input_tokens"] + item["simulated_output_tokens"]
        for item in actual_transports
    )


async def run_evidence_reader_continuation():
    from agents import Agent, RunConfig
    from app.agents.research_history import history_tools
    from app.agents.owner_research import OwnerResearchContext
    from test_context_decision_fidelity import _seed

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    _, run, brief, sources, snapshots, quotes = await _seed(factory, phone=False)
    owner_tools = OwnerResearchContext(
        agent_name="GeneralShoppingAgent",
        run_id=run.run_id,
        brief=brief,
        region_code="PH",
        session_factory=factory,
        allowed_source_ids=lambda: frozenset(item.source_id for item in sources),
    )
    original_texts = [item.extracted_content.text for item in snapshots]
    assert original_texts[2].index("no local warranty") > 2000
    read_ids = [str(sources[0].source_id), str(sources[2].source_id)]
    represented = {}

    def complete_reads(input, handoffs):
        outputs = []
        for result in _tool_results(input):
            reference = result.get("_research_view")
            if reference:
                represented[reference["view_id"]] = result
        for view_id, result in represented.items():
            nested = result.get("sources", [result])
            facts = [item["title"] for item in nested]
            outputs.extend(
                _call(
                    "complete_research_result",
                    {"view_id": view_id, "retained_facts": facts},
                )
            )
        return outputs

    def child_decision(input, handoffs):
        serialized = json.dumps(input)
        assert "no local warranty" in serialized
        assert "Unrelated navigation and catalogue text." not in serialized
        return _message(
            {"decision": "Exclude the imported offer because it has no local warranty."}
        )

    child = AcceptanceModel(
        [
            _call("compare_evidence", {"source_ids": read_ids}),
            complete_reads,
            child_decision,
        ]
    )
    child_agent = Agent(
        name="SourceIntelligenceManagerAgent",
        model="nested",
        tools=[*owner_tools.sdk_tools(), *history_tools()],
    )
    nested = child_agent.as_tool(
        tool_name="compare_saved_sources",
        tool_description="Independently compare the saved warranty conflict.",
    )

    def parent_decision(input, handoffs):
        results = _tool_results(input)
        assert "no local warranty" in json.dumps(input)
        assert "Unrelated navigation and catalogue text." in json.dumps(input)
        assert any(item.get("status") == "processed" for item in results)
        assert any(item.get("deferred_text") for item in results)
        reads = [item for item in results if item.get("text")]
        assert reads and all(len(item["text"]) <= 2000 for item in reads)
        assert all(item.get("source_id") in read_ids for item in reads)
        assert read_ids[1] in json.dumps(input)
        return _message(
            {
                "decision": "Choose Amber Desk Lamp PH and exclude the imported offer without local warranty."
            }
        )

    parent = AcceptanceModel(
        [
            _call("read_run_evidence", {"source_id": read_ids[0]})
            + _call("read_run_evidence", {"source_id": read_ids[0]})
            + _call("read_run_evidence", {"source_id": read_ids[1]}),
            complete_reads,
            _call(
                "compare_saved_sources",
                {"input": "Check the imported warranty conflict."},
            ),
            _call("read_run_evidence", {"source_id": read_ids[0]}),
            parent_decision,
        ]
    )
    budget = ContextBudget()
    config = RunConfig(
        model_provider=AcceptanceProvider({"parent": parent, "nested": child}),
        tracing_disabled=True,
    )
    with context_scope(budget):
        result = await BoundedRunner.run(
            Agent(
                name="GeneralShoppingAgent",
                model="parent",
                tools=[*owner_tools.sdk_tools(), *history_tools(), nested],
            ),
            "Decide using exact saved source evidence and preserve the warranty conflict.",
            run_config=config,
            max_turns=10,
        )
    assert (
        json.loads(result.final_output)["decision"]
        == "Choose Amber Desk Lamp PH and exclude the imported offer without local warranty."
    )
    async with factory() as session:
        after = await SearchSourceRepository(session).list_source_snapshots(run.run_id)
        assert [item.extracted_content.text for item in after] == original_texts
    report = {
        "case": "repeated_evidence_and_nested_comparison",
        "parent_transport": parent.transport,
        "child_transport": child.transport,
        "budget_events": budget.events,
        "simulated_total_tokens": budget.spent,
        "parent_final_decision": json.loads(result.final_output)["decision"],
    }
    assert budget.spent == sum(
        item["simulated_input_tokens"] + item["simulated_output_tokens"]
        for item in [*parent.transport, *child.transport]
    )
    final_raw_text = sum(len(item.get("text", "")) for item in _tool_results(parent.inputs[-1]))
    initial_raw_text = sum(len(item.get("text", "")) for item in _tool_results(parent.inputs[1]))
    assert final_raw_text <= initial_raw_text <= 4000
    assert sum(bool(item.get("deferred_text")) for item in _tool_results(parent.inputs[-1])) == 2
    await engine.dispose()
    return report


@pytest.mark.asyncio
async def test_actual_sdk_repeated_evidence_and_nested_comparison_keep_late_caution():
    report = await run_evidence_reader_continuation()
    _assert_context_complete(report["budget_events"])
    assert len(report["child_transport"]) == 3


async def run_source_manager_continuation(kind):
    from app.agents.contracts import (
        AmazonProductIntelligenceAgentInput,
        IKEAStoreIntelligenceAgentInput,
    )
    from app.agents.live_source_intelligence_manager import (
        SourceIntelligenceManagerAgent,
        SourceManagerInput,
    )
    from app.agents.workbench import (
        _WorkbenchAmazonProductIntelligenceProvider,
        _WorkbenchIKEAStoreIntelligenceProvider,
        _scenario_amazon_third_party_seller_region_gap,
        _scenario_ikea_available_regional_product,
    )
    from app.schemas.search_sources import SourceIntelligenceCapability

    amazon = kind == "amazon"
    capability = (
        SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW
        if amazon
        else SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE
    )
    input_model = (
        AmazonProductIntelligenceAgentInput
        if amazon
        else IKEAStoreIntelligenceAgentInput
    )
    scenario = (
        _scenario_amazon_third_party_seller_region_gap()
        if amazon
        else _scenario_ikea_available_regional_product()
    )
    supplied = input_model.model_validate(scenario.input)
    expected_claim = (
        "Amazon product page states: 27-inch QHD monitor, USB-C video input, height-adjustable stand."
        if amazon
        else "Official IKEA product page: MICKE desk, white. Product number: 902.143.08."
    )
    validated_claim = (
        expected_claim
        if amazon
        else "Official IKEA regional product result: MICKE desk, white. Product number: 902.143.08."
    )
    prefix = "amazon" if amazon else "ikea"
    product_id = str(supplied.products[0].product_id)
    saved_read = {}

    def repeated_reads(input, handoffs):
        found = next(result for result in _tool_results(input) if result.get("sources"))
        source_id = found["sources"][0]["source_id"]
        return _call(f"read_{prefix}_product", {"source_id": source_id}) + _call(
            f"read_{prefix}_product", {"source_id": source_id}
        )

    def complete_source(input, handoffs):
        outputs = []
        for result in _tool_results(input):
            reference = result.get("_research_view")
            if reference and reference["tool"] == f"read_{prefix}_product":
                assert expected_claim in json.dumps(result)
                saved_read.update(result)
                outputs.extend(
                    _call(
                        "complete_research_result",
                        {
                            "view_id": reference["view_id"],
                            "retained_facts": [expected_claim],
                        },
                    )
                )
        return outputs[:1]

    def select_source(input, handoffs):
        assert expected_claim in json.dumps(input)
        if amazon:
            assert any(
                result.get("status") == "processed_unchanged"
                for result in _tool_results(input)
            )
        else:
            tiny = [
                result
                for result in _tool_results(input)
                if result.get("source_reference")
            ]
            assert len(tiny) == 2
            assert all(
                "_research_view" not in result and len(json.dumps(result)) < 900
                for result in tiny
            )
            saved_read.update(tiny[-1])
        selected = {
            "product_id": product_id,
            "source_id": saved_read["source_reference"]["source_id"],
            "identity": "match",
            "identity_reason": "The recorded source matches the assigned product.",
        }
        if amazon:
            selected["selected_evidence_ids"] = [
                item["evidence_id"] for item in saved_read["provider_evidence"]
            ]
        else:
            selected["product_name"] = "MICKE desk, white"
            selected["product_code"] = "902.143.08"
            selected["price"] = {"amount": "3990", "currency": "PHP"}
            selected["availability"] = "available"
            selected["store_name"] = "IKEA Pasay City"
            selected["delivery_area"] = "Available for delivery in Metro Manila."
        return _message({"selected_sources": [selected]})

    child = AcceptanceModel(
        [
            _call(f"search_{prefix}_products", {"product_id": product_id}),
            repeated_reads,
            *([complete_source] if amazon else []),
            select_source,
        ]
    )

    def complete_bundle(input, handoffs):
        result = next(result for result in _tool_results(input) if result.get("bundle"))
        assert validated_claim in json.dumps(result)
        assert result.get("_research_view"), (
            "Completed source bundle must have canonical lookup before retirement."
        )
        return _call(
            "complete_research_result",
            {
                "view_id": result["_research_view"]["view_id"],
                "retained_facts": [validated_claim],
            },
        )

    def finish_parent(input, handoffs):
        serialized = json.dumps(input)
        assert validated_claim in serialized
        if amazon:
            assert "Fixture Deals" in serialized
            assert "Ships from Fixture Deals" in serialized
            assert "Amazon shipping to PH could not be confirmed." in serialized
            assert "not independently authenticated" in serialized
        else:
            assert "Available for delivery in Metro Manila." in serialized
            assert any(
                reference.get("price") == {"amount": "3990", "currency": "PHP"}
                for result in _tool_results(input)
                for reference in result.get("retained", {}).get("references", [])
            )
            assert "3990" in serialized
        assert any(
            result.get("tool") == f"consult_{capability.value}"
            and result.get("status") == "processed"
            for result in _tool_results(input)
        )
        return _message(
            {
                "summary": "Use the exact recorded product fact and keep regional and seller gaps unresolved.",
                "skipped_sources": [],
            }
        )

    parent = AcceptanceModel(
        [
            _call(
                f"consult_{capability.value}",
                {
                    "input": "Inspect this assigned product and retain regional and seller cautions."
                },
            ),
            complete_bundle,
            finish_parent,
        ]
    )
    settings = type(_settings()).model_validate(
        {
            **_settings().model_dump(),
            "live_agents_enabled": False,
            "openai_api_key": None,
            "openai_agent_overrides": {
                "SourceIntelligenceManagerAgent": {"model": "gpt-6-astra"},
                "AmazonProductIntelligenceAgent": {"model": "gpt-6-luna"},
                "IKEAStoreIntelligenceAgent": {"model": "gpt-6-sol"},
            },
        }
    )
    manager = SourceIntelligenceManagerAgent(
        settings=settings,
        amazon_provider=_WorkbenchAmazonProductIntelligenceProvider(),
        ikea_provider=_WorkbenchIKEAStoreIntelligenceProvider(),
        model_runner=AcceptanceRunner(
            {"gpt-6-astra": parent, "gpt-6-luna" if amazon else "gpt-6-sol": child}
        ),
    )
    budget = ContextBudget()
    with context_scope(budget):
        result = await manager.run(
            SourceManagerInput(
                run_id=supplied.run_id,
                brief=supplied.brief,
                products=supplied.products,
                listings=supplied.listings,
                source_snapshots=(),
                query_hints=(supplied.products[0].name,),
                region_code="PH",
                allowed_capabilities=(capability,),
            )
        )
    bundles = result.amazon_bundles if amazon else result.ikea_bundles
    assert len(bundles) == 1 and bundles[0].evidence
    assert validated_claim in [item.claim for item in bundles[0].evidence]
    assert all(
        item.target.product_id in (None, supplied.products[0].product_id)
        for item in bundles[0].evidence
    )
    assert any(
        item["tool_name"] == "agent_as_tool" and item["status"] == "validated"
        for item in result.activity
    )
    assert budget.spent == sum(
        item["simulated_input_tokens"] + item["simulated_output_tokens"]
        for item in [*parent.transport, *child.transport]
    )
    assert budget.spent < 30_000
    return {
        "case": f"actual_source_manager_{kind}",
        "parent_transport": parent.transport,
        "child_transport": child.transport,
        "budget_events": budget.events,
        "simulated_total_tokens": budget.spent,
        "exact_claim": expected_claim,
        "canonical_evidence_count": len(bundles[0].evidence),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["amazon", "ikea"])
async def test_actual_source_manager_repeated_reads_and_completed_bundle_continue(kind):
    report = await run_source_manager_continuation(kind)
    _assert_context_complete(report["budget_events"])
    assert len(report["parent_transport"]) == 3
    assert len(report["child_transport"]) == (4 if kind == "amazon" else 3)


async def run_partial_quote_owner_coverage(
    assurance, *, assurance_in_mode=False, quoted_warranty=False, discarded_mode=False
):
    from app.db.repositories.products import ProductRepository
    from app.db.repositories.results import ResultRepository
    from app.providers.fakes import FakeSearchProvider

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    name = "Amber Desk Lamp PH"
    price_quote = (
        "Price PHP 90000. This lamp has a local warranty."
        if quoted_warranty
        else "Price PHP 90000."
    )
    qualified = "Price PHP 90000. Check the unreviewed warranty and seller details before deciding."
    brief = ShoppingBrief(
        original_query="Buy a reading lamp in the Philippines, budget is not a problem",
        category="reading lamp",
        category_source=FieldSource.INFERRED,
        region=RegionPreference(
            region=Region(country_code="PH"), source=FieldSource.USER_PROVIDED
        ),
    )
    source = SearchResult(
        query=SearchQuery(
            query="Amber desk lamp PH", intent=SearchIntent.DISCOVERY, region_code="PH"
        ),
        url="https://official.example.com/amber-lamp",
        title=name,
        source_type=SourceType.PRODUCT_PAGE,
        provider=ProviderMetadata(provider_name="offline"),
        quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.8),
    )
    original = (
        price_quote
        + " Unrelated navigation and accessory catalogue. " * 75
        + "No local warranty. Seller details are unverified."
    )
    assert original.index("No local warranty.") > 2000
    snapshot = SourceSnapshot(
        url=source.url,
        title=name,
        source_type=source.source_type,
        provider=source.provider,
        quality=source.quality,
        extraction_status=ExtractionStatus.SUCCEEDED,
        extracted_content=ExtractedPageContent(
            text=original, extractor="offline", word_count=len(original.split())
        ),
    )
    review_quote = "Amber Desk Lamp PH has even light for reading."
    review_source = SearchResult.model_validate(
        {
            **source.model_dump(mode="python"),
            "source_id": new_id(),
            "url": "https://reviews.example.org/amber-review",
            "source_type": SourceType.PROFESSIONAL_REVIEW,
        }
    )
    review_snapshot = snapshot.model_copy(
        update={
            "source_id": new_id(),
            "url": review_source.url,
            "source_type": review_source.source_type,
            "extracted_content": ExtractedPageContent(
                text=review_quote,
                extractor="offline",
                word_count=len(review_quote.split()),
            ),
        }
    )

    class Extraction:
        provider_name = "offline-extraction"

        async def extract(self, url, options=None):
            return snapshot if str(url) == str(source.url) else review_snapshot

    async with factory() as session:
        shopping_session = await SessionRepository(session).create(
            original_input=CreateSessionRequest(query=brief.original_query),
            current_brief=brief,
        )
        run = await RunRepository(session).create(shopping_session.session_id)
        await SearchSourceRepository(session).add_search_result(run.run_id, source)
        await SearchSourceRepository(session).add_search_result(
            run.run_id, review_source
        )
        await session.commit()

    def checkpoint(input, handoffs):
        projection = input_projection(input)
        assert projection is not None
        assert any("No local warranty." in packet.material_cautions for packet in projection.sources)
        fetched = next(result for result in _tool_results(input) if result.get("source_id") == str(source.source_id) and result.get("archive_view_id"))
        return _call(
            "complete_research_result",
            {
                "view_id": fetched["archive_view_id"],
                "retained_facts": [price_quote],
            },
        )

    def decision(input, handoffs):
        serialized = json.dumps(input)
        projection = input_projection(input)
        assert projection is not None
        assert all(sum(len(text) for text in packet.excerpts) <= 4200 for packet in projection.sources)
        assert "No local warranty." in serialized
        assert "unreviewed" in serialized
        recorded = next(
            result for result in _tool_results(input) if result.get("evidence_id")
        )
        assert any(price_quote == excerpt for packet in projection.sources for excerpt in packet.excerpts)
        modes = (
            [
                {
                    "mode": "best_overall" if discarded_mode else "best_value",
                    "candidate_name": name,
                    "rationale": assurance,
                    "evidence_ids": [recorded["evidence_id"]],
                }
            ]
            if assurance_in_mode
            else []
        )
        return _message(
            {
                "category": "reading lamp",
                "candidates": [
                    {
                        "name": name,
                        "choice_group": "primary",
                        "evidence_ids": [
                            item["evidence_id"]
                            for item in _tool_results(input)
                            if item.get("evidence_id")
                        ],
                    }
                ],
                "selected_candidate_name": name,
                "rationale": qualified
                if assurance_in_mode or assurance is None
                else assurance,
                "mode_selections": modes,
            }
        )

    model = AcceptanceModel(
        [
            _call("fetch_source", {"source_id": str(source.source_id)})
            + _call("fetch_source", {"source_id": str(review_source.source_id)}),
            _call(
                "record_source_quote",
                {"source_id": str(source.source_id), "quote": price_quote},
            )
            + _call(
                "record_source_quote",
                {"source_id": str(review_source.source_id), "quote": review_quote},
            ),
            checkpoint,
            decision,
        ]
    )
    settings = _settings()

    def tools(run_id, region_code):
        return AgentResearchTools(
            agent_name="GeneralShoppingAgent",
            run_id=run_id,
            session_factory=factory,
            required_region_code=region_code,
            search_provider=FakeSearchProvider(),
            extraction_provider=Extraction(),
        )

    owner = LiveGeneralShoppingAgent(
        settings=settings,
        session_factory=factory,
        regional_research_tools_factory=tools,
        technology_research_tools_factory=lambda run_id, region: tools(
            run_id, region
        ).for_agent("TechnologyDomainAnalystAgent"),
        model_runner=AcceptanceRunner({"gpt-6-sol": model}),
    )
    budget = ContextBudget()
    with context_scope(budget):
        draft = await owner.run(
            GeneralShoppingAgentInput(run_id=run.run_id, brief=brief)
        )
    actual = [
        event
        for event in owner.workbench_activity
        if event["tool_name"] == "general_owner"
    ][-1]
    assert len(model.transport) == 4 and not model.steps
    assert not any(
        event["tool_name"] == "owner_recovery" for event in owner.workbench_activity
    )
    assert budget.spent == sum(
        item["simulated_input_tokens"] + item["simulated_output_tokens"]
        for item in model.transport
    )
    assert budget.reserved == 0
    _assert_context_complete(budget.events)
    async with factory() as session:
        saved = await SearchSourceRepository(session).get_snapshot_for_search_result(
            run.run_id, source.source_id
        )
        assert saved.extracted_content.text == original
        evidence = await SearchSourceRepository(session).list_source_evidence(
            run.run_id
        )
        assert {item.claim for item in evidence} == {price_quote, review_quote}
        assert (
            await ProductRepository(session).list_canonical_products_for_run(run.run_id)
            == ()
        )
        assert (
            await ResultRepository(session).load_latest_result_bundle(run.run_id)
            is None
        )
    if assurance is None or discarded_mode:
        assert draft.outcome == GeneralShoppingOutcome.DRAFT
        assert draft.selected_candidate_name == name
        assert draft.rationale == qualified
        assert {item.quote for item in draft.candidates[0].evidence} == {
            price_quote,
            review_quote,
        }
    else:
        assert draft.outcome == GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
        assert draft.selected_candidate_name is None
        assert draft.candidates == () and draft.mode_selections == ()
        assert actual["output"]["failure_code"] == "unreviewed_research"
    report = {
        "case": "partial_quote_discarded_mode"
        if discarded_mode
        else "partial_quote_qualified"
        if assurance is None
        else "partial_quote_unsafe_mode"
        if assurance_in_mode
        else "partial_quote_unsafe_primary",
        "model_assurance": assurance,
        "owner_outcome": draft.outcome.value,
        "selected_candidate": draft.selected_candidate_name,
        "failure_code": actual["output"].get("failure_code"),
        "transport": model.transport,
        "budget_events": budget.events,
        "simulated_total_tokens": budget.spent,
        "exact_recorded_quote": price_quote,
        "canonical_warning": "No local warranty.",
        "quoted_warranty": quoted_warranty,
        "discarded_mode": discarded_mode,
        "original_characters": len(original),
        "sdk_calls": len(model.transport),
        "saved_recommendation": False,
    }
    await engine.dispose()
    return report


@pytest.mark.asyncio
async def test_actual_owner_accepts_qualified_partial_quote_with_retained_warranty_caution():
    await run_partial_quote_owner_coverage(None)
