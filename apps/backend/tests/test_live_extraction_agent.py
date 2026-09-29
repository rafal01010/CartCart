import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.agents.contracts import (
    DiscoveryAgentInput,
    DiscoveryAgentOutcome,
    DiscoveryAgentOutput,
    DiscoveryNextAction,
    DiscoverySourceDecision,
    DiscoverySourceKind,
    ExtractedProductMention,
    ExtractionAgentInput,
    ExtractionAgentOutput,
    ExtractionEvidenceGap,
    ExtractionLeadMatch,
    ExtractionUserAddedMatch,
)
from app.agents.live_extraction import _validate_extraction
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
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import SourceId, new_id
from app.schemas.products import (
    CanonicalProduct,
    ProductListing,
    SellerProfile,
    UserAddedProduct,
)
from app.schemas.search_sources import (
    ExtractedPageContent,
    ExtractionStatus,
    ProviderMetadata,
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceType,
    SearchIntent,
    SearchPlan,
    SearchQuery,
    SearchResult,
    SourceEvidence,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
)


def _review_evidence(source_id: SourceId, claim: str) -> SourceEvidence:
    return SourceEvidence(
        source_id=source_id,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.SOURCE_METADATA, source_id=source_id
        ),
        evidence_type=EvidenceType.REVIEW_CLAIM,
        claim=claim,
        confidence=Confidence(
            score=0.8,
            level=ConfidenceLevel.HIGH,
            rationale="Named in review fixture.",
        ),
        source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "products", "listings", "gap"),
    [
        ("extraction-agent/individual-product-page", 1, 1, False),
        ("extraction-agent/ambiguous-page", 0, 0, True),
        ("extraction-agent/malformed-output", 0, 0, True),
        ("extraction-agent/multiple-products", 2, 2, False),
        ("extraction-agent/review-roundup", 0, 0, False),
        ("extraction-agent/collection-without-item-urls", 0, 0, True),
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
    if scenario == "extraction-agent/review-roundup":
        assert len(result.output["product_mentions"]) == 3
        assert len(result.output["source_evidence"]) == 3
    if scenario == "extraction-agent/collection-without-item-urls":
        assert len(result.output["product_mentions"]) == 2
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
    def __init__(self) -> None:
        self.inputs: list[ExtractionAgentInput] = []

    async def run(self, input_data: ExtractionAgentInput) -> ExtractionAgentOutput:
        self.inputs.append(input_data)
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
        evidence = SourceEvidence(
            source_id=source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.SOURCE_METADATA,
                source_id=source_id,
            ),
            evidence_type=EvidenceType.OTHER,
            claim="Collection also names TV 3 without an item link.",
            confidence=Confidence(
                score=0.8,
                level=ConfidenceLevel.HIGH,
                rationale="Named in collection fixture.",
            ),
            source_quality=SourceQuality(level=SourceQualityLevel.MIXED),
        )
        return ExtractionAgentOutput(
            products=products,
            listings=listings,
            source_evidence=(evidence,),
            product_mentions=(
                ExtractedProductMention(
                    source_id=source_id,
                    name="TV 3",
                    evidence_ids=(evidence.evidence_id,),
                ),
            ),
        )


class _CaptureLeadDiscoveryAgent:
    def __init__(self) -> None:
        self.inputs: list[DiscoveryAgentInput] = []

    async def run(self, input_data: DiscoveryAgentInput) -> DiscoveryAgentOutput:
        self.inputs.append(input_data)
        return DiscoveryAgentOutput(
            outcome=DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES
        )


class _KeepSeedDiscoveryAgent(_CaptureLeadDiscoveryAgent):
    async def run(self, input_data: DiscoveryAgentInput) -> DiscoveryAgentOutput:
        self.inputs.append(input_data)
        return DiscoveryAgentOutput(
            search_results=input_data.seed_results,
            outcome=DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES,
        )


class _CollectionProvider:
    async def extract(self, url: object, options: object) -> SourceSnapshot:
        del options
        return SourceSnapshot(
            url=url,
            source_type=SourceType.SEARCH_RESULT,
            provider=ProviderMetadata(provider_name="fixture"),
            extraction_status=ExtractionStatus.SUCCEEDED,
            extracted_content=ExtractedPageContent(
                text="TV 1 https://shop.example/tv-1 TV 2 https://shop.example/tv-2 TV 3 needs a direct link",
                extractor="fixture",
                word_count=12,
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
            source_repository = SearchSourceRepository(session)
            plan = SearchPlan(queries=(result.query,))
            plan_id = await source_repository.create_search_plan(run.run_id, plan)
            await source_repository.add_search_result(
                run.run_id, result, plan_id=plan_id
            )
            await session.commit()
            extraction_agent = _MultiProductExtractionAgent()
            discovery_agent = _CaptureLeadDiscoveryAgent()
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(session),
                    result_repository=ResultRepository(session),
                    search_source_repository=SearchSourceRepository(session),
                    product_repository=ProductRepository(session),
                ),
                agent_workflow_mode=AgentWorkflowMode.LIVE,
                discovery_agent=discovery_agent,
                extraction_agent=extraction_agent,
                extraction_provider=_CollectionProvider(),
            )
            context = ShoppingRunContext(
                run_id=run.run_id,
                session_id=shopping_session.session_id,
                trace_id="test-trace",
                active_brief=brief,
                search_plan=plan,
                search_plan_id=plan_id,
                search_results=(result,),
                selected_source_ids=(result.source_id,),
                collection_result_ids=(result.source_id,),
            )
            stage = await orchestrator._extract_sources(context)
            assert stage.agent_name == "ExtractionAgent"
            assert extraction_agent.inputs[0].collection_snapshot_ids
            assert len(discovery_agent.inputs) == 1
            assert discovery_agent.inputs[0].product_leads[0].name == "TV 3"
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


class _ReviewAndOfferProvider:
    def __init__(self) -> None:
        self.snapshots: dict[SourceId, SourceSnapshot] = {}

    async def extract(self, url: object, options: object) -> SourceSnapshot:
        del options
        snapshot = SourceSnapshot(
            url=url,
            source_type=SourceType.SEARCH_RESULT,
            provider=ProviderMetadata(provider_name="fixture"),
            extraction_status=ExtractionStatus.SUCCEEDED,
            extracted_content=ExtractedPageContent(
                text="Aurora A55, Northstar N65, and Cedar C75 are distinct TVs.",
                extractor="fixture",
                word_count=10,
            ),
        )
        self.snapshots[snapshot.source_id] = snapshot
        return snapshot


class _ReviewToOfferExtractionAgent:
    def __init__(self, provider: _ReviewAndOfferProvider) -> None:
        self.provider = provider
        self.inputs: list[ExtractionAgentInput] = []

    async def run(self, input_data: ExtractionAgentInput) -> ExtractionAgentOutput:
        self.inputs.append(input_data)
        source_id = input_data.snapshot_ids[0]
        snapshot = self.provider.snapshots[source_id]
        if input_data.editorial_snapshot_ids:
            evidence = tuple(
                _review_evidence(source_id, f"Review recommends {name}.")
                for name in ("Aurora A55", "Northstar N65", "Cedar C75")
            )
            return ExtractionAgentOutput(
                source_evidence=evidence,
                product_mentions=tuple(
                    ExtractedProductMention(
                        source_id=source_id,
                        name=name,
                        model=name.split()[-1],
                        evidence_ids=(record.evidence_id,),
                    )
                    for name, record in zip(
                        ("Aurora A55", "Northstar N65", "Cedar C75"), evidence
                    )
                ),
            )
        name = "Aurora A55" if "aurora" in str(snapshot.url) else "Northstar N65"
        product = CanonicalProduct(
            name=name, model=name.split()[-1], source_ids=(source_id,)
        )
        listing = ProductListing(
            product_id=product.product_id,
            title=name,
            url=snapshot.url,
            seller=SellerProfile(seller_name="TV Store", source_ids=(source_id,)),
            source_ids=(source_id,),
        )
        matching_lead = next(
            lead for lead in input_data.research_leads if lead.mention.name == name
        )
        return ExtractionAgentOutput(
            products=(product,),
            listings=(listing,),
            source_evidence=(
                SourceEvidence(
                    source_id=source_id,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.LISTING,
                        listing_id=listing.listing_id,
                    ),
                    evidence_type=EvidenceType.LISTING_IDENTITY,
                    claim=f"TV Store offers {name}.",
                    confidence=Confidence(
                        score=0.8,
                        level=ConfidenceLevel.HIGH,
                        rationale="Named in offer fixture.",
                    ),
                    source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE),
                ),
            ),
            lead_matches=(
                ExtractionLeadMatch(
                    product_id=product.product_id,
                    lead_evidence_ids=matching_lead.mention.evidence_ids,
                ),
            ),
        )


class _LeadDiscoveryAgent:
    def __init__(self) -> None:
        self.inputs: list[DiscoveryAgentInput] = []

    async def run(self, input_data: DiscoveryAgentInput) -> DiscoveryAgentOutput:
        self.inputs.append(input_data)
        if not input_data.product_leads:
            return DiscoveryAgentOutput(
                outcome=DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES,
                notes=("No further direct offers were found.",),
            )
        assert len(input_data.product_leads) == 3
        results = tuple(
            SearchResult(
                query=SearchQuery(query=lead.name, intent=SearchIntent.DISCOVERY),
                url=f"https://tv-store.example/{lead.name.split()[-1].lower()}-{lead.name.split()[0].lower()}",
                title=f"{lead.name} at TV Store",
                provider=ProviderMetadata(provider_name="fixture"),
            )
            for lead in input_data.product_leads[:2]
        )
        return DiscoveryAgentOutput(
            search_results=results,
            source_decisions=tuple(
                DiscoverySourceDecision(
                    source_id=result.source_id,
                    classification=DiscoverySourceKind.RETAILER_LISTING,
                    confidence=0.9,
                    reasons=("Named retail offer.",),
                    intended_treatment="Fetch offer",
                    next_action=DiscoveryNextAction.FETCH,
                )
                for result in results
            ),
            selected_source_ids=tuple(result.source_id for result in results),
            outcome=DiscoveryAgentOutcome.SELECTED,
        )


class _TwoRoundLeadDiscoveryAgent:
    def __init__(self) -> None:
        self.inputs: list[DiscoveryAgentInput] = []

    async def run(self, input_data: DiscoveryAgentInput) -> DiscoveryAgentOutput:
        self.inputs.append(input_data)
        name = "Aurora A55" if len(self.inputs) == 1 else "Northstar N65"
        result = SearchResult(
            query=SearchQuery(query=name, intent=SearchIntent.DISCOVERY),
            url=f"https://tv-store.example/{name.split()[-1].lower()}-{name.split()[0].lower()}",
            title=f"{name} at TV Store",
            source_type=SourceType.SEARCH_RESULT,
            provider=ProviderMetadata(provider_name="fixture"),
        )
        return DiscoveryAgentOutput(
            search_results=(result,),
            source_decisions=(
                DiscoverySourceDecision(
                    source_id=result.source_id,
                    classification=DiscoverySourceKind.RETAILER_LISTING,
                    confidence=0.9,
                    reasons=("Named retail offer despite generic provider type.",),
                    intended_treatment="Fetch offer",
                    next_action=DiscoveryNextAction.FETCH,
                ),
            ),
            selected_source_ids=(result.source_id,),
            outcome=DiscoveryAgentOutcome.SELECTED,
        )


@pytest.mark.asyncio
async def test_review_mentions_drive_bounded_offer_lookup_before_shortlist() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            brief = ShoppingBrief(
                original_query="Best TVs",
                category="tv",
                category_source=FieldSource.INFERRED,
            )
            shopping_session = await SessionRepository(session).create(
                original_input=CreateSessionRequest(query=brief.original_query),
                current_brief=brief,
            )
            run = await RunRepository(session).create(shopping_session.session_id)
            plan = SearchPlan(
                queries=(SearchQuery(query="best TVs", intent=SearchIntent.REVIEW),)
            )
            repository = SearchSourceRepository(session)
            plan_id = await repository.create_search_plan(run.run_id, plan)
            review = SearchResult(
                query=plan.queries[0],
                url="https://reviews.example/best-tvs",
                title="Best TVs",
                provider=ProviderMetadata(provider_name="fixture"),
            )
            await repository.add_search_result(run.run_id, review, plan_id=plan_id)
            await session.commit()
            provider = _ReviewAndOfferProvider()
            extraction_agent = _ReviewToOfferExtractionAgent(provider)
            discovery_agent = _LeadDiscoveryAgent()
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(session),
                    result_repository=ResultRepository(session),
                    search_source_repository=repository,
                    product_repository=ProductRepository(session),
                ),
                agent_workflow_mode=AgentWorkflowMode.LIVE,
                discovery_agent=discovery_agent,
                extraction_agent=extraction_agent,
                extraction_provider=provider,
            )
            context = ShoppingRunContext(
                run_id=run.run_id,
                session_id=shopping_session.session_id,
                trace_id="review-followup",
                active_brief=brief,
                search_plan=plan,
                search_plan_id=plan_id,
                search_results=(review,),
                selected_source_ids=(review.source_id,),
                editorial_result_ids=(review.source_id,),
            )
            await orchestrator._extract_sources(context)
            assert len(discovery_agent.inputs) == 2
            assert len(context.extraction_mentions) == 3
            assert (
                len(
                    [
                        item
                        for item in context.source_extractions
                        if item.listing_extraction
                    ]
                )
                == 2
            )
            assert all(
                item.search_result.source_id != review.source_id
                for item in context.source_extractions
                if item.listing_extraction
            )
            product_ids = {
                item.listing_extraction.product.product_id
                for item in context.source_extractions
                if item.listing_extraction
            }
            assert {
                evidence.target.product_id
                for evidence in context.extraction_evidence
                if evidence.evidence_type == EvidenceType.REVIEW_CLAIM
                and evidence.target.target_type == EvidenceTargetType.PRODUCT
            } == product_ids
            assert all(
                evidence.target.target_type == EvidenceTargetType.PRODUCT
                for evidence in context.extraction_evidence
                if evidence.evidence_type == EvidenceType.REVIEW_CLAIM
                and evidence.target.target_type == EvidenceTargetType.PRODUCT
            )
            assert all(
                evidence.target.target_type == EvidenceTargetType.LISTING
                for evidence in context.extraction_evidence
                if evidence.evidence_type == EvidenceType.LISTING_IDENTITY
            )
            assert (
                sum(
                    evidence.target.target_type == EvidenceTargetType.SOURCE_METADATA
                    for evidence in context.extraction_evidence
                    if evidence.evidence_type == EvidenceType.REVIEW_CLAIM
                )
                == 1
            )
            assert len(await repository.list_search_results(run.run_id)) == 3
            assert len(await repository.list_source_snapshots(run.run_id)) == 3
            await orchestrator._deduplicate_candidates(context)
            canonical_ids = {
                group.product.product_id
                for group in context.deduplication.result.groups
            }
            assert {
                record.target.product_id
                for record in await repository.list_source_evidence(run.run_id)
                if record.target.target_type == EvidenceTargetType.PRODUCT
            } == canonical_ids
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_research_loop_repeats_agent_follow_up_for_generic_offer_results() -> (
    None
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            brief = ShoppingBrief(
                original_query="Best TVs",
                category="tv",
                category_source=FieldSource.INFERRED,
            )
            shopping_session = await SessionRepository(session).create(
                original_input=CreateSessionRequest(query=brief.original_query),
                current_brief=brief,
            )
            run = await RunRepository(session).create(shopping_session.session_id)
            repository = SearchSourceRepository(session)
            plan = SearchPlan(
                queries=(SearchQuery(query="best TVs", intent=SearchIntent.REVIEW),)
            )
            plan_id = await repository.create_search_plan(run.run_id, plan)
            review = SearchResult(
                query=plan.queries[0],
                url="https://reviews.example/best-tvs",
                title="Best TVs",
                source_type=SourceType.SEARCH_RESULT,
                provider=ProviderMetadata(provider_name="fixture"),
            )
            await repository.add_search_result(run.run_id, review, plan_id=plan_id)
            await session.commit()
            provider = _ReviewAndOfferProvider()
            discovery = _TwoRoundLeadDiscoveryAgent()
            extraction = _ReviewToOfferExtractionAgent(provider)
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(session),
                    result_repository=ResultRepository(session),
                    search_source_repository=repository,
                    product_repository=ProductRepository(session),
                ),
                agent_workflow_mode=AgentWorkflowMode.LIVE,
                discovery_agent=discovery,
                extraction_agent=extraction,
                extraction_provider=provider,
            )
            context = ShoppingRunContext(
                run_id=run.run_id,
                session_id=shopping_session.session_id,
                trace_id="two-round-followup",
                active_brief=brief,
                search_plan=plan,
                search_plan_id=plan_id,
                search_results=(review,),
                selected_source_ids=(review.source_id,),
                editorial_result_ids=(review.source_id,),
            )
            stage = await orchestrator._extract_sources(context)
            assert len(discovery.inputs) == 2
            assert discovery.inputs[0].research_state is not None
            assert discovery.inputs[0].product_leads
            assert discovery.inputs[1].research_state is not None
            assert discovery.inputs[1].research_state.listing_count == 1
            assert discovery.inputs[1].research_state.candidates[0].name == "Aurora A55"
            assert discovery.inputs[1].research_state.evidence
            assert len(await repository.list_search_results(run.run_id)) == 3
            assert len(await repository.list_source_snapshots(run.run_id)) == 3
            assert (
                sum(
                    item.listing_extraction is not None
                    for item in context.source_extractions
                )
                == 2
            )
            journals = [
                item
                for item in stage.tool_activity
                if item["tool_name"].startswith("research_")
            ]
            assert (
                sum(
                    item["tool_name"] == "research_discovery_decision"
                    for item in journals
                )
                == 2
            )
            assert (
                sum(
                    item["tool_name"] == "research_extraction_decision"
                    for item in journals
                )
                == 3
            )
            assert any(
                item["output"]["lead_matches"]
                for item in journals
                if item["tool_name"] == "research_extraction_decision"
            )
            assert context.extraction_gaps
    finally:
        await engine.dispose()


class _PartlyFailingCollectionProvider(_CollectionProvider):
    async def extract(self, url: object, options: object) -> SourceSnapshot:
        if "unavailable" in str(url):
            raise RuntimeError("optional page provider unavailable")
        return await super().extract(url, options)


class _PartlyFailingSearchProvider:
    provider_name = "partly-failing-search"

    async def search(
        self, query: SearchQuery, options: object
    ) -> tuple[SearchResult, ...]:
        del options
        if query.query == "unavailable TVs":
            raise RuntimeError("optional search provider unavailable")
        return (
            SearchResult(
                query=query,
                url="https://shop.example/tvs",
                title="TV collection",
                source_type=SourceType.SEARCH_RESULT,
                provider=ProviderMetadata(provider_name=self.provider_name),
            ),
        )


class _GapExtractionAgent:
    async def run(self, input_data: ExtractionAgentInput) -> ExtractionAgentOutput:
        return ExtractionAgentOutput(
            evidence_gaps=(
                ExtractionEvidenceGap(
                    source_id=input_data.snapshot_ids[0],
                    summary="No specific offer on this page.",
                ),
            )
        )


@pytest.mark.asyncio
async def test_optional_planned_search_failure_keeps_other_generic_results() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            brief = ShoppingBrief(original_query="Find TVs")
            shopping_session = await SessionRepository(session).create(
                original_input=CreateSessionRequest(query=brief.original_query),
                current_brief=brief,
            )
            run = await RunRepository(session).create(shopping_session.session_id)
            repository = SearchSourceRepository(session)
            plan = SearchPlan(
                queries=(
                    SearchQuery(query="unavailable TVs", intent=SearchIntent.DISCOVERY),
                    SearchQuery(query="available TVs", intent=SearchIntent.DISCOVERY),
                )
            )
            plan_id = await repository.create_search_plan(run.run_id, plan)
            await session.commit()
            discovery = _KeepSeedDiscoveryAgent()
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(session),
                    result_repository=ResultRepository(session),
                    search_source_repository=repository,
                    product_repository=ProductRepository(session),
                ),
                agent_workflow_mode=AgentWorkflowMode.LIVE,
                discovery_agent=discovery,
                extraction_agent=_GapExtractionAgent(),
                search_provider=_PartlyFailingSearchProvider(),
            )
            context = ShoppingRunContext(
                run_id=run.run_id,
                session_id=shopping_session.session_id,
                trace_id="partial-search-failure",
                active_brief=brief,
                search_plan=plan,
                search_plan_id=plan_id,
            )
            stage = await orchestrator._discover_sources(context)
            assert len(await repository.list_search_results(run.run_id)) == 1
            assert len(discovery.inputs[0].seed_results) == 1
            assert (
                discovery.inputs[0].seed_results[0].source_type
                == SourceType.SEARCH_RESULT
            )
            assert any(
                item["tool_name"] == "provider_search_gap"
                for item in stage.tool_activity
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_loop_reuses_discovery_tool_snapshot_by_source_id() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            brief = ShoppingBrief(original_query="Find TVs")
            shopping_session = await SessionRepository(session).create(
                original_input=CreateSessionRequest(query=brief.original_query),
                current_brief=brief,
            )
            run = await RunRepository(session).create(shopping_session.session_id)
            repository = SearchSourceRepository(session)
            query = SearchQuery(query="TVs", intent=SearchIntent.DISCOVERY)
            plan = SearchPlan(queries=(query,))
            plan_id = await repository.create_search_plan(run.run_id, plan)
            result = SearchResult(
                query=query,
                url="https://shop.example/unavailable",
                title="TV collection",
                source_type=SourceType.SEARCH_RESULT,
                provider=ProviderMetadata(provider_name="fixture"),
            )
            await repository.add_search_result(run.run_id, result, plan_id=plan_id)
            cached = SourceSnapshot(
                url=result.url,
                source_type=SourceType.SEARCH_RESULT,
                provider=ProviderMetadata(provider_name="fixture"),
                extraction_status=ExtractionStatus.SUCCEEDED,
                extracted_content=ExtractedPageContent(
                    text="TV 1 and TV 2 are listed here.",
                    extractor="fixture",
                    word_count=7,
                ),
            )
            await repository.add_source_snapshot(
                run.run_id, cached, search_result_id=result.source_id
            )
            await session.commit()
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(session),
                    result_repository=ResultRepository(session),
                    search_source_repository=repository,
                    product_repository=ProductRepository(session),
                ),
                agent_workflow_mode=AgentWorkflowMode.LIVE,
                discovery_agent=_CaptureLeadDiscoveryAgent(),
                extraction_agent=_MultiProductExtractionAgent(),
                extraction_provider=_PartlyFailingCollectionProvider(),
            )
            context = ShoppingRunContext(
                run_id=run.run_id,
                session_id=shopping_session.session_id,
                trace_id="cached-discovery-fetch",
                active_brief=brief,
                search_plan=plan,
                search_plan_id=plan_id,
                search_results=(result,),
                selected_source_ids=(result.source_id,),
                collection_result_ids=(result.source_id,),
            )
            await orchestrator._extract_sources(context)
            assert len(await repository.list_source_snapshots(run.run_id)) == 1
            assert (
                len(
                    [
                        item
                        for item in context.source_extractions
                        if item.listing_extraction
                    ]
                )
                == 2
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_generic_selected_page_survives_optional_fetch_failure() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            brief = ShoppingBrief(
                original_query="Find TVs",
                category="tv",
                category_source=FieldSource.INFERRED,
            )
            shopping_session = await SessionRepository(session).create(
                original_input=CreateSessionRequest(query=brief.original_query),
                current_brief=brief,
            )
            run = await RunRepository(session).create(shopping_session.session_id)
            repository = SearchSourceRepository(session)
            query = SearchQuery(query="TVs", intent=SearchIntent.DISCOVERY)
            plan = SearchPlan(queries=(query,))
            plan_id = await repository.create_search_plan(run.run_id, plan)
            results = tuple(
                SearchResult(
                    query=query,
                    url=f"https://shop.example/{path}",
                    title=path,
                    source_type=SourceType.SEARCH_RESULT,
                    provider=ProviderMetadata(provider_name="fixture"),
                )
                for path in ("unavailable", "tvs")
            )
            for result in results:
                await repository.add_search_result(run.run_id, result, plan_id=plan_id)
            await session.commit()
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(session),
                    result_repository=ResultRepository(session),
                    search_source_repository=repository,
                    product_repository=ProductRepository(session),
                ),
                agent_workflow_mode=AgentWorkflowMode.LIVE,
                discovery_agent=_CaptureLeadDiscoveryAgent(),
                extraction_agent=_MultiProductExtractionAgent(),
                extraction_provider=_PartlyFailingCollectionProvider(),
            )
            context = ShoppingRunContext(
                run_id=run.run_id,
                session_id=shopping_session.session_id,
                trace_id="partial-page-failure",
                active_brief=brief,
                search_plan=plan,
                search_plan_id=plan_id,
                search_results=results,
                selected_source_ids=tuple(result.source_id for result in results),
                collection_result_ids=(results[1].source_id,),
            )
            await orchestrator._extract_sources(context)
            assert len(context.source_extractions) == 3
            assert (
                sum(
                    item.listing_extraction is not None
                    for item in context.source_extractions
                )
                == 2
            )
            assert any(
                "could not be retrieved" in gap.summary
                for gap in context.extraction_gaps
            )
            assert len(await repository.list_source_snapshots(run.run_id)) == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_research_page_budget_bounds_large_generic_selection() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            brief = ShoppingBrief(original_query="Find TVs")
            shopping_session = await SessionRepository(session).create(
                original_input=CreateSessionRequest(query=brief.original_query),
                current_brief=brief,
            )
            run = await RunRepository(session).create(shopping_session.session_id)
            repository = SearchSourceRepository(session)
            query = SearchQuery(query="TVs", intent=SearchIntent.DISCOVERY)
            plan = SearchPlan(queries=(query,))
            plan_id = await repository.create_search_plan(run.run_id, plan)
            results = tuple(
                SearchResult(
                    query=query,
                    url=f"https://shop.example/tv-{index}",
                    title=f"TV page {index}",
                    source_type=SourceType.SEARCH_RESULT,
                    provider=ProviderMetadata(provider_name="fixture"),
                )
                for index in range(15)
            )
            for result in results:
                await repository.add_search_result(run.run_id, result, plan_id=plan_id)
            await session.commit()
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(session),
                    result_repository=ResultRepository(session),
                    search_source_repository=repository,
                    product_repository=ProductRepository(session),
                ),
                agent_workflow_mode=AgentWorkflowMode.LIVE,
                discovery_agent=_CaptureLeadDiscoveryAgent(),
                extraction_agent=_GapExtractionAgent(),
                extraction_provider=_CollectionProvider(),
            )
            context = ShoppingRunContext(
                run_id=run.run_id,
                session_id=shopping_session.session_id,
                trace_id="bounded-generic-selection",
                active_brief=brief,
                search_plan=plan,
                search_plan_id=plan_id,
                search_results=results,
                selected_source_ids=tuple(result.source_id for result in results),
            )
            stage = await orchestrator._extract_sources(context)
            assert len(await repository.list_search_results(run.run_id)) == 15
            assert len(await repository.list_source_snapshots(run.run_id)) == 12
            assert len(context.extraction_gaps) == 12
            assert stage.payload["snapshot_count"] == "12"
    finally:
        await engine.dispose()


def test_editorial_snapshot_cannot_become_retailer_listing() -> None:
    from types import SimpleNamespace

    source_id = new_id()
    product = CanonicalProduct(name="Aurora A55", source_ids=(source_id,))
    listing = ProductListing(
        product_id=product.product_id,
        title=product.name,
        url="https://reviews.example/best-tvs",
        seller=SellerProfile(seller_name="Reviews", source_ids=(source_id,)),
        source_ids=(source_id,),
    )
    output = ExtractionAgentOutput(products=(product,), listings=(listing,))
    with pytest.raises(ValueError, match="editorial source"):
        _validate_extraction(
            output,
            {
                source_id: SimpleNamespace(
                    url="https://reviews.example/best-tvs",
                    text="Aurora A55",
                )
            },
            ExtractionAgentInput(
                run_id=new_id(),
                snapshot_ids=(source_id,),
                editorial_snapshot_ids=(source_id,),
            ),
        )


def test_collection_url_cannot_be_reused_as_item_offer_url() -> None:
    from types import SimpleNamespace

    source_id = new_id()
    product = CanonicalProduct(name="Aurora A55", source_ids=(source_id,))
    listing = ProductListing(
        product_id=product.product_id,
        title=product.name,
        url="https://shop.example/tvs",
        seller=SellerProfile(seller_name="TV Store", source_ids=(source_id,)),
        source_ids=(source_id,),
    )
    with pytest.raises(ValueError, match="collection URL"):
        _validate_extraction(
            ExtractionAgentOutput(products=(product,), listings=(listing,)),
            {
                source_id: SimpleNamespace(
                    url="https://shop.example/tvs",
                    text="Aurora A55 and Northstar N65 TVs",
                )
            },
            ExtractionAgentInput(
                run_id=new_id(),
                snapshot_ids=(source_id,),
                collection_snapshot_ids=(source_id,),
            ),
        )


def test_user_added_match_must_reference_a_supplied_hint() -> None:
    from types import SimpleNamespace

    source_id = new_id()
    product = CanonicalProduct(name="Aurora A55", source_ids=(source_id,))
    listing = ProductListing(
        product_id=product.product_id,
        title=product.name,
        url="https://shop.example/aurora-a55",
        seller=SellerProfile(seller_name="TV Store", source_ids=(source_id,)),
        source_ids=(source_id,),
    )
    output = ExtractionAgentOutput(
        products=(product,),
        listings=(listing,),
        user_added_matches=(
            ExtractionUserAddedMatch(
                candidate_id=new_id(),
                product_id=product.product_id,
                listing_id=listing.listing_id,
                source_id=source_id,
                confidence="confirmed",
                rationale="Named in the page.",
            ),
        ),
    )
    with pytest.raises(ValueError, match="unknown shopper hint"):
        _validate_extraction(
            output,
            {source_id: SimpleNamespace(url=str(listing.url), text="Aurora A55")},
            ExtractionAgentInput(
                run_id=new_id(),
                snapshot_ids=(source_id,),
                user_added_products=(UserAddedProduct(input_text="Aurora A55"),),
            ),
        )
