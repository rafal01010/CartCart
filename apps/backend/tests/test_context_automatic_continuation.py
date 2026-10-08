import asyncio
import json
from contextlib import nullcontext
from math import ceil
from unittest.mock import patch

import pytest
from agents.items import ModelResponse
from agents.usage import Usage
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

import app.db.models  # noqa: F401
from app.agents import context_management
from app.agents.context_management import ContextBudget, context_scope
from app.agents.context_metrics import measure
from app.agents.contracts import (
    ComparisonDecisionAgentInput,
    GeneralShoppingAgentInput,
    GeneralShoppingOutcome,
)
from app.agents.extraction_tools import SnapshotInterpretationTools
from app.agents.live_comparison_decision import LiveComparisonDecisionAgent
from app.agents.live_general_shopping import LiveGeneralShoppingAgent
from app.agents.live_verifier_critic import LiveVerifierCriticAgent
from app.agents.research_tools import AgentResearchTools
from app.api.routes.results import SessionResultsResponse
from app.core.settings import AgentWorkflowMode
from app.db.base import Base
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_session_factory, get_db_session
from app.main import create_app
from app.orchestration.shopping_runs import (
    RepositoryShoppingRunPersistenceHooks,
    ShoppingRunOrchestrator,
)
from app.schemas.intake import (
    CreateSessionRequest,
    FieldSource,
    RegionPreference,
    ShoppingBrief,
)
from app.schemas.regions import Region
from app.schemas.analysis import (
    RecommendationMode,
    ListingTrustAssessment,
    ListingTrustLevel,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.money import Money
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.schemas.runs import RunStage, RunStatus
from app.schemas.search_sources import (
    ExtractedPageContent,
    ExtractionStatus,
    ProviderMetadata,
    SearchResult,
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
from test_context_research_completion import (
    AcceptanceModel,
    AcceptanceRunner,
    LAMP,
    PHONE,
    SavedShapeSearch,
)


class AutomaticModel(AcceptanceModel):
    def __init__(self, steps, rewrite_behavior="success"):
        super().__init__(steps)
        self.seen_page_views = []
        self.rewrite_behavior = rewrite_behavior
        self.failed_assertions = []

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
        if not (instructions or "").startswith("Select useful exact passages"):
            self.seen_page_views.extend(
                result["text"]
                for result in _tool_results(input)
                if isinstance(result.get("text"), str)
            )
            self.seen_page_views.extend(
                span["text"]
                for result in _tool_results(input)
                for span in result.get("source_spans", [])
                if isinstance(span.get("text"), str)
            )
            try:
                return await super().get_response(
                    instructions,
                    input,
                    model_settings,
                    tools,
                    output_schema,
                    handoffs,
                    tracing,
                    **kwargs,
                )
            except AssertionError as exc:
                self.failed_assertions.append(str(exc))
                raise
        if self.rewrite_behavior == "failure":
            raise RuntimeError("Offline rewrite failure.")
        if self.rewrite_behavior == "timeout":
            await asyncio.sleep(0.05)
            raise AssertionError("The bounded rewrite should already have timed out.")
        chunks = json.loads(input)["chunks"]
        spans = []
        useful_quotes = [
            quote
            for case in (PHONE, LAMP)
            for quote in (case.good_quote, case.review_quote, case.unsafe_quote)
        ]
        for chunk in chunks:
            found = [quote for quote in useful_quotes if quote in chunk["text"]]
            for quote in found:
                start = chunk["text"].index(quote)
                spans.append(
                    {
                        "field_id": chunk["field_id"],
                        "start": start,
                        "end": start + len(quote),
                    }
                )
            if not found:
                spans.append(
                    {
                        "field_id": chunk["field_id"],
                        "start": 0,
                        "end": min(len(chunk["text"]), 300),
                    }
                )
        components = {
            "instructions": measure(instructions),
            "schemas": measure(
                context_management._schema_payload(tools, output_schema, handoffs)
            ),
            "active_history": measure(input),
        }
        tokens = ceil(sum(item["characters"] for item in components.values()) / 4)
        self.transport.append(
            {
                "components": components,
                "simulated_input_tokens": tokens,
                "simulated_output_tokens": 100,
                "shortening": True,
            }
        )
        return ModelResponse(
            output=_message(
                {"spans": spans}
                if self.rewrite_behavior == "success"
                else {"invented_claim": "All sellers are verified."}
            ),
            response_id=None,
            usage=Usage(
                requests=1,
                input_tokens=tokens,
                output_tokens=100,
                total_tokens=tokens + 100,
            ),
        )


class DistinctPages:
    provider_name = "offline-distinct-pages"

    def __init__(self, case):
        self.case = case
        self.calls = []
        self.originals = {}

    async def extract(self, url, options=None):
        self.calls.append(str(url))
        index = int(str(url).rsplit("-", 1)[-1])
        first = {
            15: self.case.good_quote,
            0: self.case.review_quote,
            1: self.case.imported_name + " is offered for sale.",
            3: self.case.competitor_name + " has a different design.",
        }[index]
        text = first + (
            f" Page {index} navigation and catalogue. Cámara, garantía, 家用購入比較庫. "
            * 190
        )
        if index == 1:
            text += self.case.unsafe_quote
        self.originals[index] = text
        return SourceSnapshot(
            url=url,
            title="Persisted distinct page",
            source_type=options.source_type,
            provider=ProviderMetadata(provider_name=self.provider_name),
            extraction_status=ExtractionStatus.SUCCEEDED,
            extracted_content=ExtractedPageContent(
                text=text, extractor="offline", word_count=len(text.split())
            ),
        )


async def run_automatic_continuation(
    case=PHONE,
    *,
    baseline=False,
    database_path=None,
    insufficient=False,
    rewrite_behavior="success",
    unsafe_listing=False,
):
    database_url = (
        "sqlite+aiosqlite:///:memory:"
        if database_path is None
        else f"sqlite+aiosqlite:///{database_path}"
    )
    engine = create_async_engine(database_url)
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
    search = SavedShapeSearch(case)
    search.leads[1] = SearchResult.model_validate(
        {
            **search.leads[1].model_dump(mode="python"),
            "source_type": SourceType.RETAILER_LISTING,
            "url": "https://retailer.example.net/lead-1",
        }
    )
    extraction = DistinctPages(case)
    if unsafe_listing:
        async with factory() as session:
            product = await ProductRepository(session).add_canonical_product(
                run.run_id, CanonicalProduct(name=case.selected_name)
            )
            listing = await ProductRepository(session).add_product_listing(
                run.run_id,
                ProductListing(
                    product_id=product.product_id,
                    title=product.name,
                    url=search.leads[15].url,
                    seller=SellerProfile(seller_name="Unverified reseller"),
                    price=Money(amount="2499", currency="PHP"),
                    source_ids=(search.leads[15].source_id,),
                ),
            )
            await ResultRepository(session).add_listing_trust_assessment(
                run.run_id,
                ListingTrustAssessment(
                    listing_id=listing.listing_id,
                    level=ListingTrustLevel.SUSPICIOUS,
                    confidence=Confidence(score=0.9, level=ConfidenceLevel.HIGH),
                    summary="Seller identity contradicts the official store claim.",
                    evidence_ids=(search.leads[15].source_id,),
                    source_ids=(search.leads[15].source_id,),
                ),
            )
            await session.commit()
    created_tools = []

    def research_tools(run_id, region_code, agent_name="GeneralShoppingAgent"):
        tools = AgentResearchTools(
            agent_name=agent_name,
            run_id=run_id,
            session_factory=factory,
            required_region_code=region_code,
            search_provider=search,
            extraction_provider=extraction,
        )
        created_tools.append(tools)
        return tools

    steps = [
        _call(
            "search_sources",
            {
                "query": f"{case.category} PH distinct search {index}",
                "intent": "discovery",
                "region_code": "PH",
                "max_results": 6,
            },
        )
        for index in range(3)
    ]
    selected_indexes = (15, 0, 1, 3)
    steps.append(
        [
            call
            for index in (15,)
            for call in _call(
                "read_search_results", {"source_id": str(search.leads[index].source_id)}
            )
        ]
    )

    def fetch_batch(input, handoffs):
        exact = {
            result["source_id"]: result
            for result in _tool_results(input)
            if result.get("snippet")
        }
        assert str(search.leads[15].source_id) in exact
        assert (
            "Later official lead." in exact[str(search.leads[15].source_id)]["snippet"]
        )
        return [
            call
            for index in selected_indexes
            for call in _call(
                "fetch_source", {"source_id": str(search.leads[index].source_id)}
            )
        ]

    steps.append(fetch_batch)

    def inspect_late_warning(input, handoffs):
        assert "No local warranty." in json.dumps(input)
        assert not any(case.unsafe_quote in text for text in model.seen_page_views)
        return _call(
            "fetch_source",
            {"source_id": str(search.leads[1].source_id), "focus": case.unsafe_quote},
        ) + (
            _call(
                "record_source_quote",
                {
                    "source_id": str(search.leads[15].source_id),
                    "quote": case.good_quote,
                },
            )
            if insufficient
            else []
        )

    steps.append(inspect_late_warning)
    quotes = ((15, case.good_quote), (0, case.review_quote), (1, case.unsafe_quote))
    if not insufficient:
        rereads = 0

        def record_checked_quotes(input, handoffs):
            nonlocal rereads
            missing = [
                (index, quote)
                for index, quote in quotes
                if not any(quote in text for text in model.seen_page_views)
            ]
            if missing:
                assert rereads < 3, (
                    "Bounded original rereads did not expose the exact quote."
                )
                rereads += 1
                model.steps.insert(0, record_checked_quotes)
                outputs = []
                for index, quote in missing:
                    reference = next(
                        result
                        for result in reversed(_tool_results(input))
                        if str(result.get("source_id"))
                        == str(search.leads[index].source_id)
                        and result.get("_research_view")
                    )
                    outputs.extend(
                        _call(
                            "read_research_result",
                            {
                                "view_id": reference["_research_view"]["view_id"],
                                "focus": quote,
                            },
                        )
                    )
                return outputs
            for index, quote in quotes:
                assert any(quote in text for text in model.seen_page_views), (
                    f"Exact quote was omitted from transported page views: {quote}"
                )
            return [
                call
                for index, quote in quotes
                for call in _call(
                    "record_source_quote",
                    {"source_id": str(search.leads[index].source_id), "quote": quote},
                )
            ]

        steps.append(record_checked_quotes)
    rationale = case.good_quote + " " + case.review_quote
    limited_reason = "Research was shortened before enough independent support could be checked. Local warranty and seller details still need checking."

    def owner_decision(input, handoffs):
        serialized = json.dumps(input, ensure_ascii=False)
        assert "must-not-enter-prompt" not in serialized
        assert "No local warranty." in serialized
        records = [
            result for result in _tool_results(input) if result.get("evidence_id")
        ]
        assert len(records) == (1 if insufficient else 3)
        return _message(
            {
                "category": case.category,
                "selected_candidate_name": None if insufficient else case.selected_name,
                "candidates": []
                if insufficient
                else [
                    {
                        "name": case.selected_name,
                        "evidence_ids": [record["evidence_id"] for record in records],
                    }
                ],
                "rationale": limited_reason if insufficient else rationale,
                "evidence_gap": limited_reason
                if insufficient
                else "Imported offer has no local warranty and remains excluded.",
            }
        )

    steps.append(owner_decision)
    model = AutomaticModel(steps, rewrite_behavior)
    models = {"gpt-6-luna" if case == PHONE else "gpt-6-sol": model}
    if case == PHONE:
        models.update(
            {
                "gpt-6-sol": AutomaticModel(
                    [
                        lambda input, handoffs: _call(
                            handoffs[0].tool_name,
                            {
                                "technology_category": "smartphone",
                                "reason": "Compare phone warranty and PH variants.",
                            },
                        )
                    ]
                ),
                "gpt-6-astra": AutomaticModel(
                    [
                        lambda input, handoffs: _call(
                            next(
                                item.tool_name
                                for item in handoffs
                                if item.agent_name == "SmartphoneSpecialistAgent"
                            ),
                            {
                                "product_category": "phone",
                                "reason": "Compare phone warranty and PH variants.",
                            },
                        )
                    ]
                ),
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
    budget = ContextBudget()
    report = {
        "case": case.category,
        "baseline": baseline,
        "insufficient": insufficient,
        "unsafe_listing": unsafe_listing,
        "rewrite_behavior": rewrite_behavior,
        "session_id": str(shopping_session.session_id),
        "run_id": str(run.run_id),
    }

    async def unchanged(self, prepared, *args, **kwargs):
        return prepared, {"status": "irreducible"}

    disabled = (
        patch.object(context_management.BudgetedModel, "_shorten", unchanged)
        if baseline
        else nullcontext()
    )
    draft = None
    try:
        with (
            disabled,
            patch.object(context_management, "SHORTENING_TIMEOUT_SECONDS", 0.01),
            context_scope(budget),
        ):
            draft = await owner.run(
                GeneralShoppingAgentInput(run_id=run.run_id, brief=brief)
            )
    except context_management.ContextBudgetExceeded as exc:
        report["error"] = str(exc)
    report["blocked"] = any(
        event["status"].startswith("blocked") for event in budget.events
    )
    report["owner_outcome"] = draft.outcome.value if draft else None
    report["owner_activity"] = list(owner.workbench_activity)
    report["search_calls"] = len(search.calls)
    report["page_fetches"] = len(extraction.calls)
    if not baseline:
        assert not model.failed_assertions, model.failed_assertions
        assert draft is not None
        assert not report["blocked"], json.dumps(
            [
                (
                    event["status"],
                    event["output"].get("estimated_input_tokens"),
                    event["output"].get("compaction"),
                    event["output"].get("context_pressure_finalizing"),
                )
                for event in budget.events
            ]
        )
        assert draft.outcome == (
            GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
            if insufficient or unsafe_listing
            else GeneralShoppingOutcome.DRAFT
        ), draft.model_dump(mode="json")
        assert draft.selected_candidate_name == (
            None if insufficient or unsafe_listing else case.selected_name
        )
        bundle, context = await _owner_bundle(
            factory, shopping_session, run, brief, owner, draft
        )
        async with factory() as session:
            repository = SearchSourceRepository(session)
            evidence = await repository.list_source_evidence(run.run_id)
            snapshots = await repository.list_source_snapshots(run.run_id)
            originals = await repository.list_search_results(run.run_id)
            assert len(originals) == 16
            for index in selected_indexes:
                snapshot = await repository.get_snapshot_for_search_result(
                    run.run_id, search.leads[index].source_id
                )
                assert snapshot.extracted_content.text == extraction.originals[index]
            assert extraction.originals[1].index(case.unsafe_quote) > 6500
            if not insufficient and not unsafe_listing:
                assert context.owner_products[0].name == case.selected_name
                assert context.owner_listings == ()
                assert bundle.final_listing_id is None
                assert bundle.final_rationale == rationale
                assert case.unsafe_quote in bundle.warnings, bundle.warnings
                warning_evidence = next(
                    item for item in evidence if item.claim == case.unsafe_quote
                )
                assert warning_evidence.evidence_id in bundle.evidence_ids
                assert warning_evidence.source_id in bundle.source_ids
                bundle = bundle.model_copy(
                    update={
                        "mode_results": (
                            *bundle.mode_results,
                            bundle.mode_results[0].model_copy(
                                update={
                                    "mode": RecommendationMode.BEST_VALUE,
                                    "title": "Best value",
                                    "rationale": case.good_quote,
                                }
                            ),
                        ),
                    }
                )
            comparison_model = AutomaticModel([])
            compared = bundle
            if not insufficient and not unsafe_listing:
                comparison_model.steps.append(_message(bundle.model_dump(mode="json")))
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

            def review_final(input, handoffs):
                serialized = json.dumps(input)
                if not unsafe_listing:
                    assert case.good_quote in serialized
                if insufficient:
                    assert limited_reason in serialized
                    assert len(evidence) == 1
                    assert [item.claim for item in evidence] == [case.good_quote]
                elif not unsafe_listing:
                    assert case.review_quote in serialized
                    assert case.unsafe_quote in serialized
                return _message(
                    {
                        "approved": True,
                        "recommendation_bundle": compared.model_dump(mode="json"),
                        "notes": [
                            "Checked the independent support gap and retained warranty and seller cautions."
                        ],
                    }
                )

            verifier_model = AutomaticModel([review_final])
            hooks = RepositoryShoppingRunPersistenceHooks(
                run_repository=RunRepository(session),
                result_repository=ResultRepository(session),
                search_source_repository=repository,
                product_repository=ProductRepository(session),
            )
            verifier = LiveVerifierCriticAgent(
                settings=settings,
                model_runner=AcceptanceRunner({"gpt-6-sol": verifier_model}),
                snapshot_tools_factory=lambda _: SnapshotInterpretationTools(
                    run_id=run.run_id,
                    allowed_snapshot_ids=tuple(item.source_id for item in snapshots),
                    shared_session=session,
                    agent_name="VerifierCriticAgent",
                ),
            )
            orchestrator = ShoppingRunOrchestrator(
                hooks,
                agent_workflow_mode=AgentWorkflowMode.LIVE,
                general_shopping_agent=owner,
                verifier_critic_agent=verifier,
            )
            context.recommendation_bundle = compared
            with context_scope(budget):
                await orchestrator._run_verification(context)
            await hooks.persist_live_output(context)
            await RunRepository(session).append_event(
                run.run_id,
                stage=RunStage.COMPLETE,
                status=RunStatus.SUCCEEDED,
                message="Offline automatic continuation checked.",
            )
            await session.commit()
            report["run_record"] = (
                await RunRepository(session).get(run.run_id)
            ).model_dump(mode="json")
        app = create_app(settings)

        async def override_db():
            async with factory() as fresh:
                yield fresh

        app.dependency_overrides[get_db_session] = override_db
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/api/sessions/{shopping_session.session_id}/results"
            )
            assert response.status_code == 200
            saved = SessionResultsResponse.model_validate(response.json())
            exact = await client.get(
                f"/api/sessions/{shopping_session.session_id}/results/{saved.result_version.result_version_id}"
            )
            assert exact.status_code == 200 and exact.json() == response.json()
        assert (
            saved.result_version.run_id == run.run_id
            and saved.result_version.version == 1
        )
        assert saved.recommendation_bundle.no_strong_buy is (
            insufficient or unsafe_listing
        ), saved.recommendation_bundle.verification_changes
        assert saved.recommendation_bundle.verification_action == "approved", (
            saved.recommendation_bundle.verification_changes
        )
        if insufficient:
            assert (
                saved.products == ()
                and saved.recommendation_bundle.final_product_id is None
            )
            assert limited_reason in saved.recommendation_bundle.no_strong_buy_reason
            assert saved.recommendation_bundle.no_strong_buy_reason.startswith(
                "Research was limited because the available material was too large to review fully. "
            )
            assert len(saved.recommendation_bundle.evidence_ids) == 1
            assert len(saved.recommendation_bundle.source_ids) == 1
        elif unsafe_listing:
            assert saved.recommendation_bundle.final_product_id is None
            assert saved.recommendation_bundle.final_listing_id is None
            assert any(
                assessment.level == ListingTrustLevel.SUSPICIOUS
                for assessment in saved.trust_assessments
            )
            assert draft.evidence_gaps == (
                "A cited listing has suspicious seller or listing signals.",
            )
        else:
            assert saved.products[0].name == case.selected_name
            assert (
                saved.recommendation_bundle.final_product_id
                == saved.products[0].product_id
            )
            assert saved.recommendation_bundle.final_rationale == rationale
            assert case.unsafe_quote in saved.recommendation_bundle.warnings
        assert len(comparison_model.transport) == (
            0 if insufficient or unsafe_listing else 1
        )
        assert len(verifier_model.transport) == 1
        report["result_api"] = response.json()
        models.update(comparison=comparison_model, verifier=verifier_model)
    report["transport"] = {name: item.transport for name, item in models.items()}
    report["budget_events"] = budget.events
    report["simulated_settled_tokens"] = budget.spent
    unknown_usage = sum(
        event["output"]["estimated_input_tokens"] + 768
        for event in budget.events
        if event["tool_name"] == "context_shortening"
        and event["output"]["actual_input_tokens"] is None
    )
    report["unknown_usage_reserved_tokens"] = unknown_usage
    report["owner_source_settled_tokens"] = unknown_usage + sum(
        row["simulated_input_tokens"] + row["simulated_output_tokens"]
        for name, sdk_model in models.items()
        if name not in {"comparison", "verifier"}
        for row in sdk_model.transport
    )
    report["reserved_tokens"] = budget.reserved
    assert budget.reserved == 0
    assert budget.spent == unknown_usage + sum(
        row["simulated_input_tokens"] + row["simulated_output_tokens"]
        for item in models.values()
        for row in item.transport
    )
    assert budget.spent < 150000
    assert report["owner_source_settled_tokens"] < 90000
    assert not any(
        item.get("name") == "complete_research_result"
        for sdk_model in models.values()
        for input in sdk_model.inputs
        for item in input
        if isinstance(item, dict)
    )
    await engine.dispose()
    return report


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [PHONE, LAMP], ids=["phone", "lamp"])
async def test_automatic_context_shortening_reaches_exact_saved_product_only_decision(
    case,
):
    report = await run_automatic_continuation(case)
    assert report["result_api"]["recommendation_bundle"]["no_strong_buy"] is False
    assert all(
        event["output"]["estimated_input_tokens"] <= 19000
        for event in report["budget_events"]
        if event["tool_name"] == "context_call"
    )


@pytest.mark.asyncio
async def test_same_distinct_replies_block_without_automatic_shortening():
    report = await run_automatic_continuation(baseline=True)
    assert report["blocked"] is True
    assert "result_api" not in report


@pytest.mark.asyncio
async def test_automatic_context_shortening_saves_independently_reviewed_limited_result():
    report = await run_automatic_continuation(LAMP, insufficient=True)
    assert report["result_api"]["recommendation_bundle"]["no_strong_buy"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("rewrite_behavior", ["failure", "timeout", "invalid"])
async def test_automatic_rewrite_fallback_reaches_same_verified_saved_decision(
    rewrite_behavior,
):
    report = await run_automatic_continuation(LAMP, rewrite_behavior=rewrite_behavior)
    assert report["result_api"]["products"][0]["name"] == "Amber Desk Lamp PH"
    assert (
        report["result_api"]["recommendation_bundle"]["verification_action"]
        == "approved"
    )
    rewriting = [
        event
        for event in report["budget_events"]
        if event["tool_name"] == "context_shortening"
    ]
    assert 1 <= len(rewriting) <= 3
    assert all(event["status"] == "fallback" for event in rewriting)


@pytest.mark.asyncio
async def test_automatic_context_shortening_rejects_actual_suspicious_offer():
    report = await run_automatic_continuation(LAMP, unsafe_listing=True)
    assert report["result_api"]["recommendation_bundle"]["no_strong_buy"] is True
    assert report["result_api"]["recommendation_bundle"]["final_listing_id"] is None
