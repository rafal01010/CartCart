import json
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from agents.items import ModelResponse
from agents.models.interface import Model, ModelProvider
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import app.db.models  # noqa: F401
from app.agents.context_management import BoundedRunner, ContextBudget, context_scope
from app.agents.contracts import (
    ComparisonDecisionAgentInput,
    GeneralShoppingAgentInput,
    GeneralShoppingOutcome,
    VerificationAgentInput,
)
from app.agents.live_comparison_decision import LiveComparisonDecisionAgent
from app.agents.extraction_tools import SnapshotInterpretationTools
from app.agents.live_general_shopping import LiveGeneralShoppingAgent
from app.agents.live_verifier_critic import LiveVerifierCriticAgent
from app.agents.research_tools import AgentResearchTools
from app.core.settings import AgentWorkflowMode, Settings
from app.db.base import Base
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_session_factory, get_db_session
from app.main import create_app
from app.api.routes.results import SessionResultsResponse
from app.orchestration.shopping_runs import (
    RepositoryShoppingRunPersistenceHooks,
    ShoppingRunContext,
    ShoppingRunOrchestrator,
)
from app.schemas.analysis import (
    ComparisonCriterion,
    ComparisonMatrix,
    ComparisonRow,
    ListingTrustAssessment,
    ListingTrustLevel,
    RecommendationBundle,
    RecommendationMode,
    RecommendationModeResult,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.intake import (
    BudgetConstraint,
    BudgetMode,
    CreateSessionRequest,
    FieldSource,
    RegionPreference,
    ShoppingBrief,
)
from app.schemas.money import Money
from app.schemas.ids import new_id
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.providers.fakes import FakeExtractionProvider, FakeSearchProvider
from app.schemas.regions import Region
from app.schemas.runs import RunStage, RunStatus
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


def _message(value: dict[str, Any]) -> list[ResponseOutputMessage]:
    return [
        ResponseOutputMessage(
            id="answer",
            type="message",
            role="assistant",
            status="completed",
            content=[
                ResponseOutputText(
                    type="output_text", annotations=[], text=json.dumps(value)
                )
            ],
        )
    ]


def _call(name: str, arguments: dict[str, Any]) -> list[ResponseFunctionToolCall]:
    return [
        ResponseFunctionToolCall(
            type="function_call",
            call_id=str(new_id()),
            name=name,
            arguments=json.dumps(arguments),
        )
    ]


class _ScriptModel(Model):
    def __init__(self, steps):
        self.steps = list(steps)
        self.inputs = []

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
        self.inputs.append(input)
        step = self.steps.pop(0)
        output = step(input, handoffs) if callable(step) else step
        return ModelResponse(
            output=output,
            response_id=None,
            usage=Usage(
                requests=1, input_tokens=200, output_tokens=100, total_tokens=300
            ),
        )

    async def stream_response(self, *args, **kwargs):
        raise AssertionError(
            "These regression tests make no streaming or live requests."
        )
        yield


class _ScriptProvider(ModelProvider):
    def __init__(self, models):
        self.models = models

    def get_model(self, model_name):
        return self.models[model_name]


class _BoundedSDKRunner:
    def __init__(self, models):
        self.provider = _ScriptProvider(models)

    async def run(self, agent, model_input, *, run_config, max_turns):
        return await BoundedRunner.run(
            agent,
            model_input,
            run_config=replace(
                run_config, model_provider=self.provider, tracing_disabled=True
            ),
            max_turns=max_turns,
        )


def _tool_results(input):
    return [
        json.loads(item["output"])
        for item in input
        if isinstance(item, dict)
        and item.get("type") == "function_call_output"
        and isinstance(item.get("output"), str)
        and item["output"].startswith("{")
    ]


def _settings():
    return Settings(
        _env_file=None,
        environment="test",
        live_agents_enabled=True,
        openai_api_key="offline-placeholder",
        openai_model="gpt-6-sol",
        openai_agent_overrides={
            "TechnologyDomainAnalystAgent": {"model": "gpt-6-astra"},
            "SmartphoneSpecialistAgent": {"model": "gpt-6-luna"},
        },
    )


@pytest_asyncio.fixture
async def stored_research():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


async def _seed(factory, *, phone: bool):
    name = "Aster Pro 512GB PH" if phone else "Amber Desk Lamp PH"
    brief = ShoppingBrief(
        original_query="I need to buy a phone, budget is not a problem"
        if phone
        else "Buy a reading lamp in the Philippines",
        category="smartphone" if phone else "reading lamp",
        category_source=FieldSource.INFERRED,
        region=RegionPreference(
            region=Region(country_code="PH"), source=FieldSource.USER_PROVIDED
        ),
    )
    quotes = (
        (
            "Aster Pro 512GB PH has a two year local warranty. Next generation timing is unconfirmed.",
            "Aster Pro 512GB PH lasts a full day. Low-light photos are weaker than its competitor.",
            "Aster Pro imported 256GB has no local warranty and is not the PH 512GB variant.",
        )
        if phone
        else (
            "Amber Desk Lamp PH costs PHP 2499.00 from Example Official Store.",
            "Amber Desk Lamp PH has even light for reading. Brightness is limited for detailed work.",
            "Amber Desk Lamp imported offer costs PHP 4999.00 and has no local warranty.",
        )
    )
    async with factory() as session:
        shopping_session = await SessionRepository(session).create(
            original_input=CreateSessionRequest(query=brief.original_query),
            current_brief=brief,
        )
        run = await RunRepository(session).create(shopping_session.session_id)
        repository = SearchSourceRepository(session)
        sources, snapshots = [], []
        for index, (domain, source_type, quote) in enumerate(
            zip(
                ("example.com", "reviews.example.org", "shop.example.net"),
                (
                    SourceType.PRODUCT_PAGE,
                    SourceType.PROFESSIONAL_REVIEW,
                    SourceType.RETAILER_LISTING,
                ),
                quotes,
                strict=True,
            )
        ):
            source = SearchResult(
                query=SearchQuery(
                    query=name, intent=SearchIntent.DISCOVERY, region_code="PH"
                ),
                url=f"https://{domain}/product-{index}",
                title=name,
                source_type=source_type,
                provider=ProviderMetadata(provider_name="offline"),
                quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.7),
            )
            text = "Unrelated navigation and catalogue text. " * 1600 + quote
            snapshot = SourceSnapshot(
                url=source.url,
                title=source.title,
                source_type=source_type,
                provider=source.provider,
                quality=source.quality,
                extraction_status=ExtractionStatus.SUCCEEDED,
                extracted_content=ExtractedPageContent(
                    text=text, extractor="offline", word_count=len(text.split())
                ),
            )
            await repository.add_search_result(run.run_id, source)
            await repository.add_source_snapshot(
                run.run_id, snapshot, search_result_id=source.source_id
            )
            sources.append(source)
            snapshots.append(snapshot)
        await session.commit()
    return shopping_session, run, brief, sources, snapshots, quotes


def _owner(factory, run, brief, sources, quotes, *, phone: bool, unsafe: bool = False, rationale: str | None = None):
    name = "Aster Pro 512GB PH" if phone else "Amber Desk Lamp PH"
    steps = []
    for source, quote in zip(sources, quotes, strict=True):
        steps.append(
            _call(
                "fetch_source",
                {"source_id": str(source.source_id), "focus": quote[:80]},
            )
        )
        steps.append(
            _call(
                "record_source_quote",
                {"source_id": str(source.source_id), "quote": quote},
            )
        )

    def decision(input, handoffs):
        results = _tool_results(input)
        recorded = [item for item in results if item.get("evidence_id")]
        assert len(recorded) == 3
        assert all(
            item["status"] == "succeeded" for item in results if "status" in item
        )
        assert all(len(item["text"]) <= 4000 for item in results if "text" in item)
        assert all(quote in json.dumps(input) for quote in quotes)
        return _message(
            {
                "category": "smartphone" if phone else "reading lamp",
                "candidates": [
                    {
                        "name": name,
                        "evidence_ids": [
                            item["evidence_id"]
                            for item in recorded[: 2 if unsafe else 3]
                        ],
                    }
                ],
                "selected_candidate_name": name,
                "rationale": rationale
                or (
                    "Aster Pro 512GB PH lasts a full day. Low-light photos are weaker than its competitor. "
                    "Next generation timing is unconfirmed. A two year local warranty supports this choice."
                    if phone
                    else "Amber Desk Lamp PH has even light for reading. Brightness is limited for detailed work."
                ),
            }
        )

    steps.append(decision)
    research_model = _ScriptModel(steps)
    models = {"gpt-6-luna" if phone else "gpt-6-sol": research_model}
    if phone:

        def transfer(input, handoffs):
            return _call(
                handoffs[0].tool_name,
                {
                    "technology_category": "smartphone",
                    "reason": "Check phone camera and software support.",
                },
            )

        def specialist(input, handoffs):
            target = next(
                item
                for item in handoffs
                if item.agent_name == "SmartphoneSpecialistAgent"
            )
            return _call(
                target.tool_name,
                {
                    "product_category": "phone",
                    "reason": "Compare phone cameras and local variants.",
                },
            )

        models.update(
            {
                "gpt-6-sol": _ScriptModel([transfer]),
                "gpt-6-astra": _ScriptModel([specialist]),
            }
        )

    def tools(run_id, region_code, agent_name="GeneralShoppingAgent"):
        return AgentResearchTools(
            agent_name=agent_name,
            run_id=run_id,
            session_factory=factory,
            required_region_code=region_code,
            search_provider=FakeSearchProvider(),
            extraction_provider=FakeExtractionProvider(),
        )

    owner = LiveGeneralShoppingAgent(
        settings=_settings(),
        session_factory=factory,
        regional_research_tools_factory=tools,
        technology_research_tools_factory=lambda run_id, region_code: tools(
            run_id, region_code, "TechnologyDomainAnalystAgent"
        ),
        model_runner=_BoundedSDKRunner(models),
    )
    return (
        owner,
        GeneralShoppingAgentInput(run_id=run.run_id, brief=brief),
        research_model,
    )


async def _owner_bundle(factory, shopping_session, run, brief, owner, draft):
    async with factory() as session:
        hooks = RepositoryShoppingRunPersistenceHooks(
            run_repository=RunRepository(session),
            result_repository=ResultRepository(session),
            search_source_repository=SearchSourceRepository(session),
            product_repository=ProductRepository(session),
        )
        context = ShoppingRunContext(
            run_id=run.run_id,
            session_id=shopping_session.session_id,
            trace_id="offline",
            active_brief=brief,
            general_owner_draft=draft,
        )
        bundle = await ShoppingRunOrchestrator(
            hooks, general_shopping_agent=owner
        )._owner_recommendation(context)
        await session.commit()
    return bundle, context


@pytest.mark.asyncio
async def test_long_phone_pages_reach_production_draft_and_unknown_price_decision(
    stored_research,
):
    factory = stored_research
    shopping_session, run, brief, sources, snapshots, quotes = await _seed(
        factory, phone=True
    )
    owner, request, model = _owner(factory, run, brief, sources, quotes, phone=True)
    budget = ContextBudget()
    with context_scope(budget):
        draft = await owner.run(request)
    assert draft.outcome == GeneralShoppingOutcome.DRAFT, (
        draft,
        owner.workbench_activity[-1],
        len(model.inputs),
        len(model.steps),
    )
    assert draft.owner_agent_name == "SmartphoneSpecialistAgent"
    assert draft.selected_candidate_name == "Aster Pro 512GB PH"
    assert [item.quote for item in draft.candidates[0].evidence] == [
        "Aster Pro 512GB PH has a two year local warranty. Next generation timing is unconfirmed.",
        "Aster Pro 512GB PH lasts a full day. Low-light photos are weaker than its competitor.",
        "Aster Pro imported 256GB has no local warranty and is not the PH 512GB variant.",
    ]
    bundle, context = await _owner_bundle(
        factory, shopping_session, run, brief, owner, draft
    )
    assert context.owner_products[0].name == "Aster Pro 512GB PH"
    assert bundle.final_product_id == context.owner_products[0].product_id
    assert bundle.final_listing_id is None
    assert context.owner_listings == ()
    assert bundle.handoff_chain == (
        "GeneralShoppingAgent -> TechnologyDomainAnalystAgent",
        "TechnologyDomainAnalystAgent -> SmartphoneSpecialistAgent",
    )
    assert (
        "A two year local warranty supports this choice."
        in bundle.final_rationale
    )
    assert len(model.inputs) == 7
    async with factory() as session:
        saved = await SearchSourceRepository(session).list_source_snapshots(run.run_id)
        assert all(len(item.extracted_content.text) > 60000 for item in saved)
        evidence = await SearchSourceRepository(session).list_source_evidence(
            run.run_id
        )
        verifier = LiveVerifierCriticAgent(
            settings=_settings(),
            model_runner=_BoundedSDKRunner(
                {
                    "gpt-6-sol": _ScriptModel(
                        [
                            _message(
                                {
                                    "approved": True,
                                    "recommendation_bundle": bundle.model_dump(
                                        mode="json"
                                    ),
                                }
                            )
                        ]
                    ),
                }
            ),
            snapshot_tools_factory=lambda _: SnapshotInterpretationTools(
                run_id=run.run_id,
                allowed_snapshot_ids=tuple(item.source_id for item in snapshots),
                shared_session=session,
                agent_name="VerifierCriticAgent",
            ),
        )
        report = await verifier.run(
            VerificationAgentInput(
                run_id=run.run_id,
                brief=brief,
                recommendation_bundle=bundle,
                products=context.owner_products,
                evidence=evidence,
            )
        )
        assert report.approved is True, report.blocking_issues
        assert report.recommendation_bundle.final_listing_id is None
        assert (
            "Next generation timing is unconfirmed."
            in report.recommendation_bundle.final_rationale
        )
        assert (
            "Low-light photos are weaker than its competitor."
            in report.recommendation_bundle.final_rationale
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe", [False, True])
async def test_long_generic_pages_keep_pick_but_block_suspicious_offer(
    stored_research, unsafe
):
    factory = stored_research
    shopping_session, run, brief, sources, _, quotes = await _seed(factory, phone=False)
    if unsafe:
        async with factory() as session:
            product = await ProductRepository(session).add_canonical_product(
                run.run_id, CanonicalProduct(name="Amber Desk Lamp PH")
            )
            listing = await ProductRepository(session).add_product_listing(
                run.run_id,
                ProductListing(
                    product_id=product.product_id,
                    title=product.name,
                    url=sources[0].url,
                    seller=SellerProfile(seller_name="Unverified reseller"),
                    price=Money(amount="2499", currency="PHP"),
                    source_ids=(sources[0].source_id,),
                ),
            )
            await ResultRepository(session).add_listing_trust_assessment(
                run.run_id,
                ListingTrustAssessment(
                    listing_id=listing.listing_id,
                    level=ListingTrustLevel.SUSPICIOUS,
                    confidence=Confidence(score=0.9, level=ConfidenceLevel.HIGH),
                    summary="Seller identity contradicts the official store claim.",
                    evidence_ids=(sources[0].source_id,),
                    source_ids=(sources[0].source_id,),
                ),
            )
            await session.commit()
    owner, request, _ = _owner(
        factory, run, brief, sources, quotes, phone=False, unsafe=unsafe
    )
    draft = await owner.run(request)
    bundle, context = await _owner_bundle(
        factory, shopping_session, run, brief, owner, draft
    )
    assert draft.owner_agent_name == "GeneralShoppingAgent"
    if unsafe:
        assert draft.outcome == GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
        assert draft.evidence_gaps == (
            "A cited listing has suspicious seller or listing signals.",
        )
        assert bundle.no_strong_buy is True
        assert bundle.final_product_id is None
    else:
        assert draft.outcome == GeneralShoppingOutcome.DRAFT
        assert draft.selected_candidate_name == "Amber Desk Lamp PH"
        assert context.owner_products[0].name == "Amber Desk Lamp PH"
        assert bundle.final_product_id == context.owner_products[0].product_id
        assert bundle.final_listing_id is None
        assert (
            draft.candidates[0].evidence[0].quote
            == "Amber Desk Lamp PH costs PHP 2499.00 from Example Official Store."
        )


@pytest.mark.asyncio
async def test_saved_research_refinement_uses_current_ph_hard_cap(stored_research):
    factory = stored_research
    shopping_session, prior_run, brief, sources, _, quotes = await _seed(
        factory, phone=False
    )
    owner, request, _ = _owner(factory, prior_run, brief, sources, quotes, phone=False)
    draft = await owner.run(request)
    prior_bundle, context = await _owner_bundle(
        factory, shopping_session, prior_run, brief, owner, draft
    )
    async with factory() as session:
        product = context.owner_products[0]
        listing = await ProductRepository(session).add_product_listing(
            prior_run.run_id,
            ProductListing(
                product_id=product.product_id,
                title="Amber Desk Lamp PH",
                url=sources[0].url,
                seller=SellerProfile(seller_name="Example Official Store"),
                price=Money(amount="2499.00", currency="PHP"),
                source_ids=(sources[0].source_id,),
            ),
        )
        evidence = await SearchSourceRepository(session).list_source_evidence(
            prior_run.run_id
        )
        offer_evidence = next(
            item
            for item in evidence
            if item.claim.startswith("Amber Desk Lamp PH costs")
        )
        trust = ListingTrustAssessment(
            listing_id=listing.listing_id,
            level=ListingTrustLevel.STRONG,
            confidence=Confidence(score=0.9, level=ConfidenceLevel.HIGH),
            summary="Known official store, checked offer.",
            evidence_ids=(offer_evidence.evidence_id,),
            source_ids=(sources[0].source_id,),
        )
        saved = await ResultRepository(session).save_result_bundle(
            prior_run.run_id,
            trust_assessments=(trust,),
            category_analyses=(),
            agent_records=(),
            recommendation_bundle=prior_bundle,
        )
        refined_run = await RunRepository(session).create(shopping_session.session_id)
        await session.commit()
    async with factory() as session:
        products = await ProductRepository(session).list_canonical_products_for_run(
            prior_run.run_id
        )
        listings = await ProductRepository(session).list_product_listings_for_run(
            prior_run.run_id
        )
        reused_evidence = await SearchSourceRepository(session).list_source_evidence(
            prior_run.run_id
        )
        persisted_session = await SessionRepository(session).get(
            shopping_session.session_id
        )
        old_brief = persisted_session.current_brief
        assert old_brief.budget is None
        current_brief = old_brief.model_copy(
            update={
                "budget": BudgetConstraint(
                    amount=Money(amount="2000.00", currency="PHP"),
                    mode=BudgetMode.HARD_CAP,
                )
            }
        )
        await SessionRepository(session).update_current_brief(
            shopping_session.session_id, current_brief
        )
        persisted_session = await SessionRepository(session).get(
            shopping_session.session_id
        )
        current_brief = persisted_session.current_brief
        stale_pick = RecommendationBundle(
            final_product_id=product.product_id,
            final_listing_id=listing.listing_id,
            final_rationale="An even light for reading from the checked official store.",
            mode_results=tuple(
                RecommendationModeResult(
                    mode=mode,
                    product_id=product.product_id,
                    listing_id=listing.listing_id,
                    title="Selected lamp",
                    rationale="An even light for reading.",
                    confidence=Confidence(score=0.8, level=ConfidenceLevel.HIGH),
                    evidence_ids=(offer_evidence.evidence_id,),
                    source_ids=(offer_evidence.source_id,),
                )
                for mode in (
                    RecommendationMode.BEST_OVERALL,
                    RecommendationMode.BEST_VALUE,
                )
            ),
            comparison_matrix=ComparisonMatrix(
                criteria=(ComparisonCriterion(name="Reading comfort"),),
                rows=(
                    ComparisonRow(
                        product_id=product.product_id,
                        listing_id=listing.listing_id,
                        evidence_ids=(offer_evidence.evidence_id,),
                        summary="Even reading light.",
                    ),
                ),
            ),
            evidence_ids=tuple(item.evidence_id for item in reused_evidence),
            source_ids=tuple(item.source_id for item in reused_evidence),
        )
        old_input = ComparisonDecisionAgentInput(
            run_id=prior_run.run_id,
            brief=old_brief,
            products=products,
            listings=listings,
            evidence=reused_evidence,
            trust_assessments=(trust,),
        )
        before = await LiveComparisonDecisionAgent(
            settings=_settings(),
            model_runner=_BoundedSDKRunner(
                {
                    "gpt-6-sol": _ScriptModel(
                        [_message(stale_pick.model_dump(mode="json"))]
                    ),
                }
            ),
        ).run(old_input)
        assert before.final_listing_id == listing.listing_id
        assert before.no_strong_buy is False

        def old_decision(input, handoffs):
            prompt = json.loads(input[0]["content"])
            assert prompt["brief"]["region"]["region"]["country_code"] == "PH"
            assert prompt["brief"]["budget"]["amount"] == {
                "amount": "2000.00",
                "currency": "PHP",
            }
            assert prompt["brief"]["budget"]["mode"] == "hard_cap"
            assert {item["evidence_id"] for item in prompt["evidence"]} == {
                str(item.evidence_id) for item in reused_evidence
            }
            return _message(stale_pick.model_dump(mode="json"))

        model = _ScriptModel([old_decision])
        comparison = LiveComparisonDecisionAgent(
            settings=_settings(),
            model_runner=_BoundedSDKRunner({"gpt-6-sol": model}),
        )
        result = await comparison.run(
            old_input.model_copy(
                update={"run_id": refined_run.run_id, "brief": current_brief}
            )
        )
        assert comparison.workbench_activity[0]["status"] == "schema_invalid_fallback"
        assert result.no_strong_buy is True
        assert result.final_product_id is None
        assert result.final_listing_id is None
        assert result.no_strong_buy_reason == (
            "No candidate is a strong buy within the hard budget cap. "
            "Next, wait for a sale, raise the hard budget, or relax a non-critical requirement before choosing one."
        )
        assert result.comparison_matrix.rows[0].listing_id == listing.listing_id
        assert result.comparison_matrix.rows[0].summary == "Above the hard budget cap."
        assert set(result.evidence_ids).issubset(
            {item.evidence_id for item in reused_evidence}
        )
        original = await ResultRepository(session).load_latest_result_bundle(
            prior_run.run_id
        )
        assert (
            original.result_version.result_version_id
            == saved.result_version.result_version_id
        )
        assert original.recommendation_bundle.final_product_id == product.product_id
        assert original.recommendation_bundle.final_listing_id is None
        assert (
            original.recommendation_bundle.final_rationale
            == prior_bundle.final_rationale
        )
        assert {item.claim for item in reused_evidence} == {
            "Amber Desk Lamp PH costs PHP 2499.00 from Example Official Store.",
            "Amber Desk Lamp PH has even light for reading. Brightness is limited for detailed work.",
            "Amber Desk Lamp imported offer costs PHP 4999.00 and has no local warranty.",
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("phone", [False, True], ids=["general", "two-hop-phone"])
@pytest.mark.parametrize(
    "verification",
    ["approve", "unsupported", "revise", "unexplained-revision", "blank-revision"],
)
async def test_owner_primary_explanation_survives_sdk_verification_and_saved_api(
    stored_research, phone: bool, verification: str
):
    factory = stored_research
    shopping_session, run, brief, sources, snapshots, quotes = await _seed(
        factory, phone=phone
    )
    authored = (
        "For all-day use, Aster Pro 512GB PH lasts a full day. "
        "Its low-light photos are weaker than its competitor."
        if phone
        else "For reading, Amber Desk Lamp PH has even light. "
        "Its brightness is limited for detailed work."
    )
    if verification == "unsupported":
        authored += " It has an 8000mAh battery."
    owner, request, model = _owner(
        factory, run, brief, sources, quotes, phone=phone, rationale=authored
    )
    draft = await owner.run(request)
    assert draft.outcome == GeneralShoppingOutcome.DRAFT
    assert draft.rationale == authored
    expected_owner = "SmartphoneSpecialistAgent" if phone else "GeneralShoppingAgent"
    assert draft.owner_agent_name == expected_owner
    bundle, context = await _owner_bundle(
        factory, shopping_session, run, brief, owner, draft
    )
    assert bundle.final_rationale == authored
    assert bundle.mode_results[0].rationale == authored
    expected_chain = (
        (
            "GeneralShoppingAgent -> TechnologyDomainAnalystAgent",
            "TechnologyDomainAnalystAgent -> SmartphoneSpecialistAgent",
        )
        if phone
        else ()
    )
    assert bundle.handoff_chain == expected_chain
    revised = (
        "Aster Pro 512GB PH lasts a full day. Low-light photos are weaker than its competitor."
        if phone
        else "Amber Desk Lamp PH has even light for reading. Brightness is limited for detailed work."
    )
    reviewed = bundle
    if verification in {"revise", "unexplained-revision", "blank-revision"}:
        reviewed = bundle.model_copy(
            update={
                "final_rationale": revised,
                "mode_results": (
                    bundle.mode_results[0].model_copy(update={"rationale": revised}),
                ),
            }
        )
    verifier_model = _ScriptModel(
        [
            _message(
                {
                    "approved": True,
                    "recommendation_bundle": reviewed.model_dump(mode="json"),
                    "notes": ["Shortened the explanation to the checked source facts."]
                    if verification == "revise"
                    else [" \t\n"]
                    if verification == "blank-revision"
                    else [],
                }
            )
        ]
    )
    async with factory() as session:
        hooks = RepositoryShoppingRunPersistenceHooks(
            run_repository=RunRepository(session),
            result_repository=ResultRepository(session),
            search_source_repository=SearchSourceRepository(session),
            product_repository=ProductRepository(session),
        )
        verifier = LiveVerifierCriticAgent(
            settings=_settings(),
            model_runner=_BoundedSDKRunner({"gpt-6-sol": verifier_model}),
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
        context.recommendation_bundle = bundle
        await orchestrator._run_verification(context)
        await hooks.persist_live_output(context)
        await RunRepository(session).append_event(
            run.run_id,
            stage=RunStage.COMPLETE,
            status=RunStatus.SUCCEEDED,
            message="Offline primary explanation checked.",
        )
        await session.commit()
    app = create_app(_settings())

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        async with factory() as fresh_session:
            yield fresh_session

    app.dependency_overrides[get_db_session] = override_db_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/sessions/{shopping_session.session_id}/results"
        )
    assert response.status_code == 200
    saved = SessionResultsResponse.model_validate(response.json())
    result = saved.recommendation_bundle
    assert result.result_author == expected_owner
    assert result.handoff_chain == expected_chain
    assert saved.result_version.version == 1
    assert saved.result_version.run_id == run.run_id
    if verification in {"unsupported", "unexplained-revision", "blank-revision"}:
        assert result.verification_action == "blocked"
        assert result.no_strong_buy is True
        assert result.final_rationale is None
        assert result.mode_results == ()
        reason = (
            "final rationale includes a factual claim not backed by its evidence."
            if verification == "unsupported"
            else "Verifier revision did not include an audit reason."
        )
        assert reason in result.verification_changes
        if verification == "unsupported":
            assert verifier_model.inputs == []
    else:
        expected = revised if verification == "revise" else authored
        assert result.final_rationale == expected
        assert result.mode_results[0].rationale == expected
        assert result.verification_action == (
            "revised" if verification == "revise" else "approved"
        )
        assert result.no_strong_buy is False
        assert result.final_product_id == saved.products[0].product_id
        assert result.evidence_ids == tuple(
            item.evidence_id for item in draft.candidates[0].evidence
        )
        assert result.source_ids == tuple(
            item.snapshot_id for item in draft.candidates[0].evidence
        )
        assert len(model.inputs) == 7
        if verification == "revise":
            assert "final_rationale" in result.verification_changes
            assert "mode_results" in result.verification_changes
            assert (
                "Shortened the explanation to the checked source facts."
                in result.verification_changes
            )
