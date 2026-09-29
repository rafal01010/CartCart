from pathlib import Path

import pytest
from pydantic import AnyHttpUrl

import app.db.models  # noqa: F401
from app.agents import (
    ComparisonDecisionAgentInput,
    DiscoveryAgentInput,
    DiscoveryAgentOutcome,
    DiscoveryAgentOutput,
    ExtractionAgentInput,
    ExtractionAgentOutput,
    ExtractionUserAddedMatch,
    GeneralShoppingAgentInput,
    GeneralShoppingDecisionDraft,
    GeneralShoppingOutcome,
    IntakeAgentInput,
    ProductAnalysisAgentInput,
    QueryPlannerAgentInput,
    SellerListingTrustAgentInput,
    VerificationAgentInput,
    VerificationReport,
)
from app.agents.catalog import ProductAnalysisRoute
from app.agents.openai_config import build_openai_agent_run_configuration
from app.core.settings import AgentWorkflowMode, Settings
from app.db.base import Base
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.repositories.source_intelligence import SourceIntelligenceRepository
from app.db.repositories.video_sources import VideoReviewRepository
from app.db.session import create_database_engine, create_session_factory
from app.orchestration import (
    RepositoryShoppingRunPersistenceHooks,
    ShoppingRunOrchestrator,
)
from app.orchestration.shopping_runs import (
    DiscoveredSourceExtraction,
    _deduplicated_user_added_products,
    _listing_from_extracted_source,
    _selected_extraction_results,
    _source_extractions_from_agent,
)
from app.providers import (
    ExtractionProviderOptions,
    ProviderCapabilityFlags,
    ProviderRunStatus,
    SearchProviderOptions,
    TranscriptAccessStrategy,
    TranscriptProviderOptions,
    TranscriptProviderResult,
)
from app.schemas.analysis import (
    CategoryAnalysis,
    ComparisonCriterion,
    ComparisonMatrix,
    ComparisonRow,
    ListingTrustAssessment,
    RecommendationBundle,
    RecommendationMode,
    RecommendationModeResult,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.intake import CreateSessionRequest, FieldSource, ShoppingBrief
from app.schemas.runs import RunStage, RunStatus
from app.schemas.search_sources import (
    ExtractedPageContent,
    ExtractionStatus,
    ProviderMetadata,
    SearchIntent,
    SearchPlan,
    SearchQuery,
    SearchResult,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
    TranscriptAvailability,
    VideoSource,
    VideoTranscriptSegment,
)
from app.schemas.products import (
    CanonicalProduct,
    ProductListing,
    SellerProfile,
    UserAddedProduct,
)
from app.services.product_listing_extraction import ProductListingExtractor


def test_agent_selected_generic_source_reaches_page_inspection() -> None:
    query = SearchQuery(
        query="Aurora A55 official retailer",
        intent=SearchIntent.DISCOVERY,
        required_source_types=(SourceType.RETAILER_LISTING,),
    )
    result = SearchResult(
        query=query,
        url="https://retailer.example.com/aurora-a55",
        title="Aurora A55 at retailer",
        source_type=SourceType.SEARCH_RESULT,
        provider=ProviderMetadata(provider_name="fixture-search"),
    )

    assert _selected_extraction_results(
        (result,), selected_source_ids=(result.source_id,)
    ) == (result,)
    assert result.source_type == SourceType.SEARCH_RESULT


class RecordingSearchProvider:
    provider_name = "recording-search"

    def __init__(self) -> None:
        self.calls: list[tuple[SearchQuery, SearchProviderOptions | None]] = []

    async def search(
        self,
        query: SearchQuery,
        options: SearchProviderOptions | None = None,
    ) -> tuple[SearchResult, ...]:
        self.calls.append((query, options))
        return (
            SearchResult(
                query=query,
                url=AnyHttpUrl(
                    "https://www.rtings.com/monitor/reviews/example?utm_source=fixture"
                ),
                title="Measured monitor review",
                snippet="Instrumented review results.",
                provider=ProviderMetadata(provider_name=self.provider_name),
                quality=SourceQuality(level=SourceQualityLevel.UNKNOWN),
            ),
            SearchResult(
                query=query,
                url=AnyHttpUrl("https://www.aliexpress.com/item/fixture.html"),
                title="Excluded reseller result",
                provider=ProviderMetadata(provider_name=self.provider_name),
            ),
        )


class ListingSearchProvider:
    provider_name = "fixture-listing-search"

    async def search(
        self,
        query: SearchQuery,
        options: SearchProviderOptions | None = None,
    ) -> tuple[SearchResult, ...]:
        del options
        return (
            SearchResult(
                query=query,
                url=AnyHttpUrl("https://shop.example/northstar-arc-27"),
                title="Northstar Arc 27 USB-C Monitor",
                snippet="Fixture retailer result.",
                source_type=SourceType.RETAILER_LISTING,
                provider=ProviderMetadata(provider_name=self.provider_name),
            ),
        )


class DuplicateListingSearchProvider:
    provider_name = "fixture-duplicate-listing-search"

    async def search(
        self,
        query: SearchQuery,
        options: SearchProviderOptions | None = None,
    ) -> tuple[SearchResult, ...]:
        del options
        return (
            SearchResult(
                query=query,
                url=AnyHttpUrl("https://shop.example/northstar-arc-27?utm_source=one"),
                title="Northstar Arc 27 USB-C Monitor",
                snippet="Fixture retailer result.",
                source_type=SourceType.RETAILER_LISTING,
                provider=ProviderMetadata(provider_name=self.provider_name),
            ),
            SearchResult(
                query=query,
                url=AnyHttpUrl(
                    "https://www.shop.example/northstar-arc-27?utm_campaign=two"
                ),
                title="Northstar Arc 27 USB-C Monitor",
                snippet="Duplicate fixture retailer result.",
                source_type=SourceType.RETAILER_LISTING,
                provider=ProviderMetadata(provider_name=self.provider_name),
            ),
        )


class MixedListingSearchProvider:
    provider_name = "fixture-mixed-listing-search"

    async def search(
        self,
        query: SearchQuery,
        options: SearchProviderOptions | None = None,
    ) -> tuple[SearchResult, ...]:
        del options
        return tuple(
            SearchResult(
                query=query,
                url=AnyHttpUrl(f"https://shop.example/product-{index}"),
                title=f"Fixture Product {index}",
                snippet="Fixture retailer result.",
                source_type=SourceType.RETAILER_LISTING,
                provider=ProviderMetadata(provider_name=self.provider_name),
            )
            for index in (1, 2)
        )


class FailingSearchProvider:
    provider_name = "fixture-failing-search"

    async def search(
        self,
        query: SearchQuery,
        options: SearchProviderOptions | None = None,
    ) -> tuple[SearchResult, ...]:
        del query, options
        raise RuntimeError("Fixture discovery failed.")


class UserAddedNameSearchProvider:
    provider_name = "fixture-user-added-name-search"

    def __init__(self) -> None:
        self.calls: list[tuple[SearchQuery, SearchProviderOptions | None]] = []

    async def search(
        self,
        query: SearchQuery,
        options: SearchProviderOptions | None = None,
    ) -> tuple[SearchResult, ...]:
        self.calls.append((query, options))
        if "northstar arc 27" in query.query.casefold():
            return (
                SearchResult(
                    query=query,
                    url=AnyHttpUrl("https://shop.example/northstar-arc-27-user"),
                    title="Northstar Arc 27 USB-C Monitor",
                    snippet="Retail listing matching the user's named product.",
                    source_type=SourceType.RETAILER_LISTING,
                    provider=ProviderMetadata(provider_name=self.provider_name),
                ),
            )
        return (
            SearchResult(
                query=query,
                url=AnyHttpUrl("https://shop.example/northstar-arc-27"),
                title="Northstar Arc 27 USB-C Monitor",
                snippet="Generated retailer candidate.",
                source_type=SourceType.RETAILER_LISTING,
                provider=ProviderMetadata(provider_name=self.provider_name),
            ),
        )


class RecordingExtractionProvider:
    provider_name = "recording-extraction"

    def __init__(self) -> None:
        self.calls: list[tuple[AnyHttpUrl, ExtractionProviderOptions | None]] = []
        self.snapshots: dict[object, SourceSnapshot] = {}

    async def extract(
        self,
        url: AnyHttpUrl,
        options: ExtractionProviderOptions | None = None,
    ) -> SourceSnapshot:
        self.calls.append((url, options))
        seller = (
            "FlashDealz Outlet"
            if "northstar-arc-27-user" in str(url)
            else "Metro Office"
        )
        text = (
            f"Brand: Northstar\nPrice: USD 329.99\nSeller: {seller}\n"
            "Region: US\nA 27 inch USB-C monitor for office work."
        )
        snapshot = SourceSnapshot(
            url=url,
            source_type=SourceType.RETAILER_LISTING,
            provider=ProviderMetadata(provider_name=self.provider_name),
            title="Northstar Arc 27 USB-C Monitor",
            extraction_status=ExtractionStatus.SUCCEEDED,
            extracted_content=ExtractedPageContent(
                text=text,
                extractor="fixture-static",
                site_name="Metro Office",
                word_count=len(text.split()),
            ),
        )
        self.snapshots[snapshot.source_id] = snapshot
        return snapshot


class RecordingExtractionAgent:
    """Mocked model output for legacy integration fixtures, not runtime logic."""

    def __init__(self, provider: RecordingExtractionProvider) -> None:
        self.provider = provider

    async def run(self, input_data: ExtractionAgentInput) -> ExtractionAgentOutput:
        snapshot = self.provider.snapshots[input_data.snapshot_ids[0]]
        extraction = ProductListingExtractor().extract_source_snapshot(snapshot)
        matches = tuple(
            ExtractionUserAddedMatch(
                candidate_id=item.candidate_id,
                product_id=extraction.product.product_id,
                listing_id=extraction.listing.listing_id,
                source_id=snapshot.source_id,
                confidence="confirmed",
                rationale="Fixture page identifies the exact named model.",
            )
            for item in input_data.user_added_products
            if item.url is None
            and item.input_text is not None
            and item.input_text.casefold() in extraction.product.name.casefold()
        )
        return ExtractionAgentOutput(
            products=(
                extraction.product.model_copy(update={"category": input_data.category}),
            ),
            listings=(extraction.listing,),
            user_added_matches=matches,
        )


class PartiallyFailingExtractionProvider(RecordingExtractionProvider):
    async def extract(
        self,
        url: AnyHttpUrl,
        options: ExtractionProviderOptions | None = None,
    ) -> SourceSnapshot:
        if str(url).endswith("product-2"):
            raise RuntimeError("Fixture source blocked.")
        return await super().extract(url, options)


class RecordingTranscriptProvider:
    provider_name = "recording-transcript"

    def __init__(self) -> None:
        self.calls: list[tuple[VideoSource, TranscriptProviderOptions | None]] = []

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            enabled=True,
            supports_transcripts=True,
            permits_transcript_text=True,
            transcript_access_strategy=TranscriptAccessStrategy.APPROVED_THIRD_PARTY,
            compliance_notes=("Records transcript requests for orchestrator tests.",),
        )

    async def fetch_transcript(
        self,
        video: VideoSource,
        options: TranscriptProviderOptions | None = None,
    ) -> TranscriptProviderResult:
        self.calls.append((video, options))
        segment = VideoTranscriptSegment(
            video_id=video.video_id,
            start_seconds=5.0,
            end_seconds=12.0,
            language="en",
            text="Fixture transcript segment from the configured transcript provider.",
        )
        return TranscriptProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            video=video.model_copy(
                update={"transcript_availability": TranscriptAvailability.AVAILABLE}
            ),
            availability=TranscriptAvailability.AVAILABLE,
            segments=(segment,),
        )


class RecordingSellerListingTrustAgent:
    def __init__(self) -> None:
        self.calls: list[SellerListingTrustAgentInput] = []

    async def run(
        self,
        input_data: SellerListingTrustAgentInput,
    ) -> ListingTrustAssessment:
        self.calls.append(input_data)
        assert input_data.rule_based_assessment is not None
        return input_data.rule_based_assessment.model_copy(
            update={
                "summary": (
                    f"Trust agent reviewed listing {input_data.listing.listing_id}."
                )
            }
        )


class RecordingIntakeAgent:
    workbench_activity = (
        {
            "tool_name": "openai_agents_structured_output",
            "status": "model_intake_completed",
            "input": {"allowed_tools": []},
        },
    )

    async def run(self, input_data: IntakeAgentInput) -> ShoppingBrief:
        return ShoppingBrief(
            original_query=input_data.request.query,
            category="monitor",
            category_source=FieldSource.INFERRED,
            region=input_data.request.region,
        )


class RecordingGeneralShoppingAgent:
    def __init__(self) -> None:
        self.calls: list[GeneralShoppingAgentInput] = []
        self.workbench_activity: tuple[dict[str, object], ...] = ()

    async def run(
        self, input_data: GeneralShoppingAgentInput
    ) -> GeneralShoppingDecisionDraft:
        self.calls.append(input_data)
        return GeneralShoppingDecisionDraft(
            category=input_data.brief.category or "general shopping",
            outcome=GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE,
            evidence_gaps=("Offline test has no checked research.",),
            rationale="There is not enough checked evidence to choose a product yet.",
        )


class RecordingQueryPlannerAgent:
    workbench_activity = (
        {
            "tool_name": "openai_agents_structured_output",
            "status": "model_query_plan_completed",
            "input": {"allowed_tools": []},
        },
    )

    async def run(self, input_data: QueryPlannerAgentInput):
        return SearchPlan(
            queries=(
                SearchQuery(
                    query=f"{input_data.brief.original_query} official listing",
                    intent=SearchIntent.DISCOVERY,
                    required_source_types=(SourceType.RETAILER_LISTING,),
                ),
            ),
            rationale="Recording live workflow query plan.",
        )


class SelectingDiscoveryAgent:
    workbench_activity = (
        {
            "tool_name": "openai_agents_structured_output",
            "status": "model_discovery_completed",
            "input": {"allowed_tools": []},
        },
    )

    async def run(self, input_data: DiscoveryAgentInput) -> DiscoveryAgentOutput:
        if not input_data.seed_results:
            return DiscoveryAgentOutput(
                outcome=DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES
            )
        selected = input_data.seed_results[:1]
        return DiscoveryAgentOutput(
            search_results=input_data.seed_results,
            selected_source_ids=tuple(result.source_id for result in selected),
            outcome=DiscoveryAgentOutcome.SELECTED,
        )


class SelectingGeneratedAndUserAddedDiscoveryAgent(SelectingDiscoveryAgent):
    async def run(self, input_data: DiscoveryAgentInput) -> DiscoveryAgentOutput:
        if not input_data.seed_results:
            return DiscoveryAgentOutput(
                outcome=DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES
            )
        selected = [
            result
            for index, result in enumerate(input_data.seed_results)
            if index == 0 or "user_added_candidate_id" in result.provider.raw
        ]
        return DiscoveryAgentOutput(
            search_results=input_data.seed_results,
            selected_source_ids=tuple(result.source_id for result in selected),
            outcome=DiscoveryAgentOutcome.SELECTED,
        )


class RecordingCategoryRouterAgent:
    workbench_activity = (
        {
            "tool_name": "openai_agents_structured_output",
            "status": "model_category_route_completed",
            "input": {"allowed_tools": []},
        },
    )

    async def run(self, input_data) -> ProductAnalysisRoute:
        del input_data
        return ProductAnalysisRoute(
            category="monitor",
            agent_path=("GenericProductAnalystAgent",),
        )


class RecordingGenericAnalystAgent:
    def __init__(self) -> None:
        self.calls: list[ProductAnalysisAgentInput] = []
        self.workbench_activity = ()

    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        self.calls.append(input_data)
        evidence_ids = tuple(item.evidence_id for item in input_data.evidence)
        if not evidence_ids:
            evidence_ids = input_data.product.source_ids
        source_ids = input_data.product.source_ids or evidence_ids
        self.workbench_activity = (
            {
                "tool_name": "openai_agents_structured_output",
                "status": "model_generic_analysis_completed",
                "input": {"allowed_tools": []},
            },
        )
        return CategoryAnalysis(
            product_id=input_data.product.product_id,
            listing_ids=tuple(listing.listing_id for listing in input_data.listings),
            category=input_data.product.category or "monitor",
            fit_summary="Recording live analysis says this candidate fits.",
            strengths=("It has enough supplied listing evidence to compare.",),
            weaknesses=("Long-term ownership evidence still needs checking.",),
            confidence=Confidence(
                level=ConfidenceLevel.MEDIUM,
                score=0.66,
                rationale="Recording local agent output.",
            ),
            evidence_ids=evidence_ids,
            source_ids=source_ids,
        )


class RecordingComparisonDecisionAgent:
    def __init__(self) -> None:
        self.workbench_activity = ()
        self.calls: list[ComparisonDecisionAgentInput] = []

    async def run(
        self,
        input_data: ComparisonDecisionAgentInput,
    ) -> RecommendationBundle:
        self.calls.append(input_data)
        product = input_data.products[0]
        listing = next(
            item
            for item in input_data.listings
            if item.product_id == product.product_id
        )
        evidence_ids = input_data.category_analyses[0].evidence_ids
        source_ids = input_data.category_analyses[0].source_ids
        matrix = ComparisonMatrix(
            criteria=(ComparisonCriterion(name="Fit", weight=0.7),),
            rows=(
                ComparisonRow(
                    product_id=product.product_id,
                    listing_id=listing.listing_id,
                    scores={"Fit": 0.7},
                    evidence_ids=evidence_ids,
                    summary="Recording comparison row.",
                ),
            ),
        )
        self.workbench_activity = (
            {
                "tool_name": "openai_agents_structured_output",
                "status": "model_comparison_decision_completed",
                "input": {"allowed_tools": []},
            },
        )
        return RecommendationBundle(
            final_product_id=product.product_id,
            final_listing_id=listing.listing_id,
            final_rationale="Recording comparison selected the supplied listing.",
            mode_results=(
                RecommendationModeResult(
                    mode=RecommendationMode.BEST_OVERALL,
                    product_id=product.product_id,
                    listing_id=listing.listing_id,
                    title=product.name,
                    rationale="Best supplied candidate in the recording test.",
                    confidence=Confidence(
                        level=ConfidenceLevel.MEDIUM,
                        score=0.66,
                        rationale="Recording local agent output.",
                    ),
                    evidence_ids=evidence_ids,
                    source_ids=source_ids,
                ),
            ),
            comparison_matrix=matrix,
            evidence_ids=evidence_ids,
            source_ids=source_ids,
        )


class RecordingVerifierCriticAgent:
    workbench_activity = (
        {
            "tool_name": "openai_agents_structured_output",
            "status": "model_verifier_critic_completed",
            "input": {"allowed_tools": []},
        },
    )

    async def run(self, input_data: VerificationAgentInput) -> VerificationReport:
        return VerificationReport(
            approved=True,
            recommendation_bundle=input_data.recommendation_bundle,
            notes=("Recording verifier approved the bundle.",),
        )


def test_professional_review_snapshot_is_not_normalized_as_store_listing() -> None:
    query = SearchQuery(
        query="monitor reviews",
        intent=SearchIntent.REVIEW,
        required_source_types=(SourceType.PROFESSIONAL_REVIEW,),
    )
    result = SearchResult(
        query=query,
        url=AnyHttpUrl("https://reviews.example/best-monitors"),
        title="The best monitors",
        snippet="A roundup of tested monitors.",
        source_type=SourceType.PROFESSIONAL_REVIEW,
        provider=ProviderMetadata(provider_name="fixture-search"),
    )
    snapshot = SourceSnapshot(
        url=result.url,
        source_type=SourceType.PROFESSIONAL_REVIEW,
        provider=ProviderMetadata(provider_name="fixture-extraction"),
        title=result.title,
        extraction_status=ExtractionStatus.SUCCEEDED,
        extracted_content=ExtractedPageContent(
            text="Review evidence about several products.",
            extractor="fixture",
            word_count=5,
        ),
    )

    assert (
        _listing_from_extracted_source(
            ProductListingExtractor(),
            result=result,
            snapshot=snapshot,
            category="monitor",
        )
        is None
    )


@pytest.mark.asyncio
async def test_shopping_run_orchestrator_records_all_expected_fixture_stages(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a 27 inch monitor"),
                current_brief=ShoppingBrief(original_query="Need a 27 inch monitor"),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            run_repository = RunRepository(db_session)
            result_repository = ResultRepository(db_session)
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=run_repository,
                    result_repository=result_repository,
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                )
            )

            context = await orchestrator.run(run.run_id, shopping_session.current_brief)
            await db_session.commit()

        async with session_factory() as db_session:
            run_repository = RunRepository(db_session)
            result_repository = ResultRepository(db_session)
            loaded_run = await run_repository.get(run.run_id)
            events = await run_repository.list_events(run.run_id)
            agent_records = await result_repository.list_agent_records(run.run_id)

        expected_stages = ShoppingRunOrchestrator.stage_order()
        executable_stages = ShoppingRunOrchestrator.executable_stage_order()

        assert loaded_run is not None
        assert loaded_run.status == RunStatus.SUCCEEDED
        assert loaded_run.current_stage == RunStage.COMPLETE
        assert context.session_id == shopping_session.session_id
        assert context.trace_id == f"fixture-run-{run.run_id}"
        assert tuple(event.stage for event in events) == expected_stages
        assert tuple(event.sequence for event in events) == tuple(
            range(len(expected_stages))
        )
        expected_statuses = (RunStatus.RUNNING,) * len(executable_stages) + (
            RunStatus.SUCCEEDED,
        )
        assert tuple(event.status for event in events) == expected_statuses
        assert tuple(context.stage_outputs) == executable_stages
        assert context.search_plan is not None
        assert context.search_plan.queries[0].query == "Need a 27 inch monitor reviews"
        assert context.search_plan.queries[0].region_code == "US"
        assert context.search_results
        assert {result.provider.provider_name for result in context.search_results} == {
            "fixture-search"
        }
        assert {record.stage for record in agent_records} == set(executable_stages)
        assert {record.trace_id for record in agent_records} == {
            f"{context.trace_id}:{stage.value}" for stage in executable_stages
        }

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_shopping_run_orchestrator_persists_monitor_fixture_output(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-fixture.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a 27 inch monitor"),
                current_brief=ShoppingBrief(original_query="Need a 27 inch monitor"),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                )
            )

            context = await orchestrator.run(run.run_id, shopping_session.current_brief)
            await db_session.commit()

        assert context.fixture_output is not None

        async with session_factory() as db_session:
            search_repository = SearchSourceRepository(db_session)
            product_repository = ProductRepository(db_session)
            result_repository = ResultRepository(db_session)
            source_intelligence_repository = SourceIntelligenceRepository(db_session)
            video_repository = VideoReviewRepository(db_session)
            search_results = await search_repository.list_search_results(run.run_id)
            source_snapshots = await search_repository.list_source_snapshots(run.run_id)
            source_evidence = await search_repository.list_source_evidence(run.run_id)
            video_sources = await video_repository.list_video_sources(run.run_id)
            community_evidence = (
                await source_intelligence_repository.list_community_evidence(run.run_id)
            )
            amazon_evidence = await source_intelligence_repository.list_amazon_evidence(
                run.run_id
            )
            shortlist = await product_repository.list_shortlist_memberships(run.run_id)
            user_added = await product_repository.list_user_added_products(
                shopping_session.session_id
            )
            result = await result_repository.load_latest_result_bundle(run.run_id)
            listing_count_items: list[int] = []
            for product in context.fixture_output.products:
                product_listings = await product_repository.list_listings_for_product(
                    product.product_id
                )
                listing_count_items.append(len(product_listings))
            listing_counts = tuple(listing_count_items)

        fixture = context.fixture_output
        assert context.source_intelligence is not None
        source_intelligence_source_count = _source_intelligence_source_reference_count(
            context.source_intelligence
        )
        assert len(search_results) == len(context.search_results)
        assert all(
            result.provider.provider_name == "fixture-search"
            for result in search_results
        )
        assert len(source_snapshots) == (
            len(fixture.source_snapshots) + source_intelligence_source_count
        )
        assert len(source_evidence) == len(fixture.source_evidence)
        assert video_sources
        assert community_evidence
        assert amazon_evidence
        assert len(shortlist) == len(fixture.shortlist_items)
        assert sum(
            item.listing_extraction is not None for item in context.source_extractions
        ) == len(fixture.listings)
        assert len(user_added) == 1
        assert user_added[0].listing is not None
        assert user_added[0].listing.seller.seller_name == "FlashDealz Outlet"
        assert result is not None
        assert result.result_version.version == 1
        assert result.recommendation_bundle.final_rationale is not None
        assert result.recommendation_bundle.final_product_id == (
            fixture.recommendation_bundle.final_product_id
        )
        assert {mode.mode for mode in result.recommendation_bundle.mode_results} >= {
            RecommendationMode.BEST_OVERALL,
            RecommendationMode.BEST_VALUE,
            RecommendationMode.WITHIN_BUDGET,
            RecommendationMode.STRETCH_PICK,
        }
        assert len(result.recommendation_bundle.runner_up_product_ids) == 2
        assert result.recommendation_bundle.rejected_items[0].listing_id == (
            user_added[0].listing.listing_id
        )
        blocked_listing_ids = {
            item.listing_id
            for item in result.recommendation_bundle.rejected_items
            if item.severity.value == "blocking"
        }
        assert fixture.listings[1].listing_id in blocked_listing_ids
        assert fixture.listings[0].listing_id not in blocked_listing_ids
        assert any(
            "product may still be worth considering" in item.reason
            for item in result.recommendation_bundle.rejected_items
        )
        assert any(
            assessment.level.value == "suspicious"
            for assessment in result.trust_assessments
        )
        assert any(count > 1 for count in listing_counts)

    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "category", "expected_subject"),
    [
        ("Which TV should I buy?", None, "tv"),
        ("Which TV should I buy?", "tv", "tv"),
        ("Need a durable office chair", "office chair", "office chair"),
    ],
)
async def test_fixture_research_never_injects_monitor_products_for_other_categories(
    tmp_path: Path, query: str, category: str | None, expected_subject: str
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "category-safe-fixture.sqlite3",
    )
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query=query),
                current_brief=ShoppingBrief(
                    original_query=query,
                    category=category,
                    category_source=FieldSource.USER_PROVIDED if category else None,
                ),
            )
            run = await RunRepository(db_session).create(session.session_id)
            await db_session.commit()
        async with session_factory() as db_session:
            context = await ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                )
            ).run(run.run_id, session.current_brief)
            await db_session.commit()
        async with session_factory() as db_session:
            products = await ProductRepository(
                db_session
            ).list_canonical_products_for_run(run.run_id)
            result = await ResultRepository(db_session).load_latest_result_bundle(
                run.run_id
            )
        assert context.fixture_output is None
        assert context.stage_outputs[RunStage.DISCOVERY].agent_name == "DiscoveryAgent"
        assert (
            context.stage_outputs[RunStage.EXTRACTION].agent_name == "ExtractionAgent"
        )
        assert products == ()
        assert result is not None
        assert result.recommendation_bundle.no_strong_buy
        assert result.recommendation_bundle.final_product_id is None
        assert expected_subject in result.recommendation_bundle.no_strong_buy_reason
        assert result.comparison_matrix.rows == ()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_mock_discovery_with_no_products_cannot_activate_monitor_replay(
    tmp_path: Path,
) -> None:
    class NoSelectionsDiscoveryAgent:
        async def run(self, input_data: DiscoveryAgentInput) -> DiscoveryAgentOutput:
            return DiscoveryAgentOutput(search_results=input_data.seed_results)

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "empty-mock-discovery.sqlite3",
    )
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a monitor"),
                current_brief=ShoppingBrief(original_query="Need a monitor"),
            )
            run = await RunRepository(db_session).create(session.session_id)
            await db_session.commit()
        async with session_factory() as db_session:
            context = await ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                ),
                discovery_agent=NoSelectionsDiscoveryAgent(),
            ).run(run.run_id, session.current_brief)
            await db_session.commit()
        async with session_factory() as db_session:
            products = await ProductRepository(
                db_session
            ).list_canonical_products_for_run(run.run_id)
            result = await ResultRepository(db_session).load_latest_result_bundle(
                run.run_id
            )
        assert context.fixture_output is None
        assert products == ()
        assert result is not None
        assert result.recommendation_bundle.no_strong_buy
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_listing_trust_stage_uses_agent_contract_and_persists_output(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-trust-agent.sqlite3",
    )
    engine = create_database_engine(settings)
    trust_agent = RecordingSellerListingTrustAgent()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a 27 inch monitor"),
                current_brief=ShoppingBrief(original_query="Need a 27 inch monitor"),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                ),
                seller_listing_trust_agent=trust_agent,
            )

            context = await orchestrator.run(run.run_id, shopping_session.current_brief)
            await db_session.commit()

        async with session_factory() as db_session:
            result = await ResultRepository(db_session).load_latest_result_bundle(
                run.run_id
            )
            agent_records = await ResultRepository(db_session).list_agent_records(
                run.run_id
            )

        assert result is not None
        trust_stage = context.stage_outputs[RunStage.LISTING_TRUST]
        assert trust_stage.payload["assessment_count"] == str(len(trust_agent.calls))
        assert len(result.trust_assessments) == len(trust_agent.calls)
        assert {assessment.listing_id for assessment in result.trust_assessments} == {
            call.listing.listing_id for call in trust_agent.calls
        }
        assert all(
            assessment.summary.startswith("Trust agent reviewed listing ")
            for assessment in result.trust_assessments
        )
        assert any(
            assessment.level.value == "suspicious"
            for assessment in result.trust_assessments
        )
        assert any(
            record.stage == RunStage.LISTING_TRUST
            and record.agent_name == "SellerListingTrustAgent"
            for record in agent_records
        )

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_query_planning_calls_provider_and_persists_scored_results_only(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-search.sqlite3",
    )
    engine = create_database_engine(settings)
    provider = RecordingSearchProvider()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a 27 inch monitor"),
                current_brief=ShoppingBrief(original_query="Need a 27 inch monitor"),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                ),
                search_provider=provider,
                default_region_code="US",
            )
            context = await orchestrator.run(
                run.run_id,
                shopping_session.current_brief,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            repository = SearchSourceRepository(db_session)
            persisted_results = await repository.list_search_results(run.run_id)
            snapshots = await repository.list_source_snapshots(run.run_id)

        assert len(provider.calls) == 1
        called_query, called_options = provider.calls[0]
        assert called_query.query == "Need a 27 inch monitor reviews"
        assert called_query.region_code == "US"
        assert called_options is not None
        assert called_options.region_code == "US"
        assert len(context.search_results) == 1
        assert len(persisted_results) == 1
        assert str(persisted_results[0].url).startswith("https://rtings.com/")
        assert "utm_source" not in str(persisted_results[0].url)
        assert persisted_results[0].quality.level == SourceQualityLevel.ADEQUATE
        assert persisted_results[0].provider.raw["source_class"] == "review_testing"
        extracted_snapshot = next(
            snapshot
            for snapshot in snapshots
            if snapshot.provider.provider_name == "fixture-extraction"
        )
        assert extracted_snapshot.url == persisted_results[0].url
        assert extracted_snapshot.provider.raw["search_result_source_id"] == str(
            persisted_results[0].source_id
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_extraction_provider_creates_persisted_generated_shortlist(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-extraction.sqlite3",
    )
    engine = create_database_engine(settings)
    extraction_provider = RecordingExtractionProvider()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a USB-C monitor"),
                current_brief=ShoppingBrief(
                    original_query="Need a USB-C monitor",
                    category="monitor",
                    category_source=FieldSource.USER_PROVIDED,
                ),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                ),
                search_provider=ListingSearchProvider(),
                extraction_provider=extraction_provider,
                extraction_agent=RecordingExtractionAgent(extraction_provider),
                default_region_code="US",
            )
            context = await orchestrator.run(
                run.run_id,
                shopping_session.current_brief,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            search_repository = SearchSourceRepository(db_session)
            product_repository = ProductRepository(db_session)
            snapshots = await search_repository.list_source_snapshots(run.run_id)
            shortlist = await product_repository.list_shortlist_memberships(run.run_id)
            events = await RunRepository(db_session).list_events(run.run_id)

            assert len(extraction_provider.calls) == 1
            called_url, called_options = extraction_provider.calls[0]
            assert str(called_url) == "https://shop.example/northstar-arc-27"
            assert called_options is not None
            assert called_options.source_type == SourceType.RETAILER_LISTING

            assert len(context.source_extractions) == 1
            generated = context.source_extractions[0]
            assert generated.listing_extraction is not None
            assert generated.listing_extraction.product.brand == "Northstar"
            assert generated.listing_extraction.product.category == "monitor"
            assert generated.listing_extraction.listing.price is not None
            assert generated.listing_extraction.listing.price.currency == "USD"

            extracted_snapshot = next(
                snapshot
                for snapshot in snapshots
                if snapshot.provider.provider_name == "recording-extraction"
            )
            assert extracted_snapshot.provider.raw["search_result_source_id"] == str(
                generated.search_result.source_id
            )
            assert len(shortlist) == 1
            assert (
                shortlist[0].product_id
                == generated.listing_extraction.product.product_id
            )
            assert (
                shortlist[0].listing_id
                == generated.listing_extraction.listing.listing_id
            )

            extraction_event = next(
                event for event in events if event.stage == RunStage.EXTRACTION
            )
            assert extraction_event.message == (
                "Checked 1 shopping source and added 1 product to compare."
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_extraction_continues_and_persists_failed_source_snapshot(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-partial-extraction.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a USB-C monitor"),
                current_brief=ShoppingBrief(
                    original_query="Need a USB-C monitor",
                    category="monitor",
                    category_source=FieldSource.USER_PROVIDED,
                ),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        extraction_provider = PartiallyFailingExtractionProvider()
        async with session_factory() as db_session:
            context = await ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                ),
                search_provider=MixedListingSearchProvider(),
                extraction_provider=extraction_provider,
                extraction_agent=RecordingExtractionAgent(extraction_provider),
            ).run(run.run_id, shopping_session.current_brief)

        async with session_factory() as db_session:
            snapshots = await SearchSourceRepository(db_session).list_source_snapshots(
                run.run_id
            )
            loaded_run = await RunRepository(db_session).get(run.run_id)

        assert loaded_run is not None
        assert loaded_run.status == RunStatus.SUCCEEDED
        assert len(context.source_extractions) == 2
        assert len(snapshots) >= 2
        failed = next(
            snapshot
            for snapshot in snapshots
            if snapshot.extraction_status == ExtractionStatus.FAILED
        )
        assert str(failed.url).endswith("product-2")
        assert failed.provider.raw["extraction_failure_code"] == "provider_exception"
        assert context.stage_outputs[RunStage.EXTRACTION].payload["failed_count"] == "1"
        assert context.deduplication is not None
        assert context.deduplication.pre_dedupe_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_run_state_is_checkpointed_before_exception_escapes(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-durable-failure.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a USB-C monitor"),
                current_brief=ShoppingBrief(original_query="Need a USB-C monitor"),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                ),
                search_provider=FailingSearchProvider(),
            )
            with pytest.raises(RuntimeError, match="Fixture discovery failed"):
                await orchestrator.run(run.run_id, shopping_session.current_brief)

        async with session_factory() as db_session:
            run_repository = RunRepository(db_session)
            loaded_run = await run_repository.get(run.run_id)
            events = await run_repository.list_events(run.run_id)

        assert loaded_run is not None
        assert loaded_run.status == RunStatus.FAILED
        assert loaded_run.current_stage == RunStage.DISCOVERY
        assert events[-1].status == RunStatus.FAILED
        assert events[-1].error is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_extraction_deduplicates_urls_before_candidate_grouping(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-deduplication.sqlite3",
    )
    engine = create_database_engine(settings)
    extraction_provider = RecordingExtractionProvider()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a USB-C monitor"),
                current_brief=ShoppingBrief(
                    original_query="Need a USB-C monitor",
                    category="monitor",
                    category_source=FieldSource.USER_PROVIDED,
                ),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                ),
                search_provider=DuplicateListingSearchProvider(),
                extraction_provider=extraction_provider,
                extraction_agent=RecordingExtractionAgent(extraction_provider),
                default_region_code="US",
            )
            context = await orchestrator.run(
                run.run_id,
                shopping_session.current_brief,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            product_repository = ProductRepository(db_session)
            events = await RunRepository(db_session).list_events(run.run_id)
            shortlist = await product_repository.list_shortlist_memberships(run.run_id)
            listings = await product_repository.list_listings_for_product(
                shortlist[0].product_id
            )

        assert len(extraction_provider.calls) == 1
        assert context.deduplication is not None
        assert context.deduplication.pre_dedupe_count == 1
        assert context.deduplication.post_dedupe_count == 1
        assert context.deduplication.collapsed_count == 0
        assert context.stage_outputs[RunStage.DEDUPLICATION].payload == {
            "pre_dedupe_count": "1",
            "post_dedupe_count": "1",
            "listing_count": "1",
            "collapsed_count": "0",
        }

        event_stages = [event.stage for event in events]
        assert event_stages.index(RunStage.EXTRACTION) < event_stages.index(
            RunStage.DEDUPLICATION
        )
        assert event_stages.index(RunStage.DEDUPLICATION) < event_stages.index(
            RunStage.SOURCE_INTELLIGENCE
        )
        deduplication_event = next(
            event for event in events if event.stage == RunStage.DEDUPLICATION
        )
        assert deduplication_event.message == (
            "Grouped 1 extracted product into 1 product group and kept "
            "1 listing; 0 duplicates collapsed."
        )

        assert len(shortlist) == 1
        assert len(listings) == 1
        assert {listing.product_id for listing in listings} == {shortlist[0].product_id}
        assert context.source_intelligence is not None
        assert context.source_intelligence.request.product_ids == (
            shortlist[0].product_id,
        )
        assert set(context.source_intelligence.request.listing_ids) == {
            listing.listing_id for listing in listings
        }

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_user_added_url_product_enters_deduplication_and_live_analysis(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-user-added-url.sqlite3",
    )
    engine = create_database_engine(settings)
    extraction_provider = RecordingExtractionProvider()
    analyst = RecordingGenericAnalystAgent()
    general = RecordingGeneralShoppingAgent()
    comparison_agent = RecordingComparisonDecisionAgent()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            create_request = CreateSessionRequest(query="Need a USB-C monitor")
            shopping_session = await SessionRepository(db_session).create(
                original_input=create_request,
                current_brief=ShoppingBrief(
                    original_query=create_request.query,
                    category="monitor",
                    category_source=FieldSource.USER_PROVIDED,
                ),
            )
            user_added = await ProductRepository(db_session).add_user_added_product(
                shopping_session.session_id,
                UserAddedProduct(
                    url=AnyHttpUrl(
                        "https://shop.example/northstar-arc-27?utm_source=user"
                    ),
                    notes="User pasted this listing.",
                ),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                ),
                agent_workflow_mode=AgentWorkflowMode.LIVE,
                agent_model_name="gpt-recording",
                intake_agent=RecordingIntakeAgent(),
                general_shopping_agent=general,
                query_planner=RecordingQueryPlannerAgent(),
                discovery_agent=SelectingDiscoveryAgent(),
                extraction_agent=RecordingExtractionAgent(extraction_provider),
                category_router_agent=RecordingCategoryRouterAgent(),
                generic_product_analyst_agent=analyst,
                seller_listing_trust_agent=RecordingSellerListingTrustAgent(),
                comparison_decision_agent=comparison_agent,
                verifier_critic_agent=RecordingVerifierCriticAgent(),
                search_provider=ListingSearchProvider(),
                extraction_provider=extraction_provider,
                default_region_code="US",
            )

            context = await orchestrator.run(
                run.run_id,
                shopping_session.current_brief,
                original_input=shopping_session.original_input,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            product_repository = ProductRepository(db_session)
            search_repository = SearchSourceRepository(db_session)
            saved_user_added = await product_repository.list_user_added_products(
                shopping_session.session_id
            )
            shortlist = await product_repository.list_shortlist_memberships(run.run_id)
            snapshots = await search_repository.list_source_snapshots(run.run_id)

        assert len(extraction_provider.calls) == 2
        assert len(general.calls) == 1
        assert general.calls[0].user_added_products[0].candidate_id == (
            user_added.candidate_id
        )
        assert context.deduplication is not None
        assert context.deduplication.pre_dedupe_count == 2
        assert context.deduplication.post_dedupe_count == 1
        assert len(context.user_added_products) == 1
        assert context.user_added_products[0].listing is not None
        assert saved_user_added[0].listing is not None
        assert saved_user_added[0].product is not None
        assert saved_user_added[0].product.product_id == (
            context.deduplication.result.groups[0].product.product_id
        )
        assert shortlist[0].candidate_id == user_added.candidate_id

        user_added_snapshot = next(
            snapshot
            for snapshot in snapshots
            if snapshot.provider.raw.get("user_added_candidate_id")
            == str(user_added.candidate_id)
        )
        assert user_added_snapshot.provider.raw["user_supplied_url"] == str(
            user_added.url
        )
        assert len(analyst.calls) == 1
        assert user_added_snapshot.source_id in analyst.calls[0].product.source_ids
        assert comparison_agent.calls == []
        assert context.general_owner_draft is not None
        assert context.recommendation_bundle is not None
        assert context.recommendation_bundle.no_strong_buy is True

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_user_added_name_product_is_retrieved_and_marked_user_supplied(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-user-added-name.sqlite3",
    )
    engine = create_database_engine(settings)
    search_provider = UserAddedNameSearchProvider()
    extraction_provider = RecordingExtractionProvider()
    analyst = RecordingGenericAnalystAgent()
    trust_agent = RecordingSellerListingTrustAgent()
    comparison_agent = RecordingComparisonDecisionAgent()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            create_request = CreateSessionRequest(query="Need a USB-C monitor")
            shopping_session = await SessionRepository(db_session).create(
                original_input=create_request,
                current_brief=ShoppingBrief(
                    original_query=create_request.query,
                    category="monitor",
                    category_source=FieldSource.USER_PROVIDED,
                ),
            )
            user_added = await ProductRepository(db_session).add_user_added_product(
                shopping_session.session_id,
                UserAddedProduct(input_text="Northstar Arc 27"),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                ),
                agent_workflow_mode=AgentWorkflowMode.LIVE,
                agent_model_name="gpt-recording",
                intake_agent=RecordingIntakeAgent(),
                general_shopping_agent=RecordingGeneralShoppingAgent(),
                query_planner=RecordingQueryPlannerAgent(),
                discovery_agent=SelectingGeneratedAndUserAddedDiscoveryAgent(),
                extraction_agent=RecordingExtractionAgent(extraction_provider),
                category_router_agent=RecordingCategoryRouterAgent(),
                generic_product_analyst_agent=analyst,
                seller_listing_trust_agent=trust_agent,
                comparison_decision_agent=comparison_agent,
                verifier_critic_agent=RecordingVerifierCriticAgent(),
                search_provider=search_provider,
                extraction_provider=extraction_provider,
                default_region_code="US",
            )

            context = await orchestrator.run(
                run.run_id,
                shopping_session.current_brief,
                original_input=shopping_session.original_input,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            product_repository = ProductRepository(db_session)
            search_repository = SearchSourceRepository(db_session)
            saved_user_added = await product_repository.list_user_added_products(
                shopping_session.session_id
            )
            shortlist = await product_repository.list_shortlist_memberships(run.run_id)
            listings = await product_repository.list_listings_for_product(
                shortlist[0].product_id
            )
            snapshots = await search_repository.list_source_snapshots(run.run_id)

        assert [call[0].query for call in search_provider.calls] == [
            "Need a USB-C monitor official listing",
            "Northstar Arc 27 official retailer listing",
        ]
        assert len(extraction_provider.calls) == 2
        assert context.deduplication is not None
        assert context.deduplication.pre_dedupe_count == 2
        assert context.deduplication.post_dedupe_count == 1
        assert context.deduplication.collapsed_count == 1
        assert shortlist[0].candidate_id == user_added.candidate_id
        assert len(listings) == 2
        assert {listing.seller.seller_name for listing in listings} == {
            "Metro Office",
            "FlashDealz Outlet",
        }
        assert all(
            any(
                match.candidate_id == user_added.candidate_id
                and match.source_id in listing.source_ids
                for match in listing.user_added_matches
            )
            for listing in listings
        )
        assert {
            call.listing.seller.seller_name
            for call in trust_agent.calls
            if call.listing.url.host == "shop.example"
        } == {"Metro Office", "FlashDealz Outlet"}

        assert saved_user_added[0].url is None
        assert saved_user_added[0].listing is not None
        assert saved_user_added[0].listing.seller.seller_name == "FlashDealz Outlet"
        assert saved_user_added[0].product is not None
        assert saved_user_added[0].product.product_id == shortlist[0].product_id

        user_added_snapshot = next(
            snapshot
            for snapshot in snapshots
            if snapshot.provider.raw.get("user_added_candidate_id")
            == str(user_added.candidate_id)
        )
        assert user_added_snapshot.provider.raw["user_supplied_query"] == (
            "Northstar Arc 27"
        )
        assert user_added_snapshot.provider.raw["user_added_match_source_id"]
        assert user_added_snapshot.source_id in analyst.calls[0].product.source_ids
        assert comparison_agent.calls == []
        assert context.general_owner_draft is not None
        assert context.recommendation_bundle is not None
        assert context.recommendation_bundle.no_strong_buy is True

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_name_lookup_keeps_multiple_possible_products_and_listing_risk_separate(
    tmp_path: Path,
) -> None:
    user_added = UserAddedProduct(input_text="Northstar Arc monitor")
    query = SearchQuery(
        query="Northstar Arc monitor official retailer listing",
        intent=SearchIntent.DISCOVERY,
    )
    result = SearchResult(
        query=query,
        url="https://shop.example/arc-monitors",
        title="Northstar Arc monitors",
        source_type=SourceType.SEARCH_RESULT,
        provider=ProviderMetadata(
            provider_name="fixture-search",
            raw={"user_added_candidate_id": str(user_added.candidate_id)},
        ),
    )
    snapshot = SourceSnapshot(
        url=result.url,
        source_type=SourceType.RETAILER_LISTING,
        provider=ProviderMetadata(provider_name="fixture-extraction"),
        extraction_status=ExtractionStatus.SUCCEEDED,
    )
    products = tuple(
        CanonicalProduct(
            name=f"Northstar Arc {size}",
            model=f"ARC-{size}",
            source_ids=(snapshot.source_id,),
        )
        for size in (27, 32)
    )
    listings = tuple(
        ProductListing(
            product_id=product.product_id,
            title=product.name,
            url=f"https://shop.example/arc-{size}",
            seller=SellerProfile(
                seller_name=seller,
                source_ids=(snapshot.source_id,),
            ),
            source_ids=(snapshot.source_id,),
        )
        for product, size, seller in zip(
            products, (27, 32), ("Metro Office", "FlashDealz Outlet"), strict=True
        )
    )
    output = ExtractionAgentOutput(
        products=products,
        listings=listings,
        user_added_matches=tuple(
            ExtractionUserAddedMatch(
                candidate_id=user_added.candidate_id,
                product_id=listing.product_id,
                listing_id=listing.listing_id,
                source_id=snapshot.source_id,
                confidence="possible",
                rationale="The name does not specify a size.",
            )
            for listing in listings
        ),
    )
    source = DiscoveredSourceExtraction(search_result=result, snapshot=snapshot)
    extracted = _source_extractions_from_agent(source, output)
    updated = _deduplicated_user_added_products((user_added,), extracted)[0]

    assert updated.product is None
    assert updated.listing is None
    assert set(updated.possible_product_ids) == {item.product_id for item in products}
    assert {
        item.listing_extraction.listing.seller.seller_name for item in extracted
    } == {"Metro Office", "FlashDealz Outlet"}
    assert all(
        item.listing_extraction.listing.user_added_matches[0].candidate_id
        == user_added.candidate_id
        for item in extracted
    )

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "ambiguous-user-added.sqlite3",
    )
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a monitor"),
                current_brief=ShoppingBrief(original_query="Need a monitor"),
            )
            await ProductRepository(db_session).add_user_added_product(
                session.session_id, user_added
            )
            run = await RunRepository(db_session).create(session.session_id)
            repository = ProductRepository(db_session)
            for item in extracted:
                await repository.add_canonical_product(
                    run.run_id, item.listing_extraction.product
                )
                await repository.add_product_listing(
                    run.run_id, item.listing_extraction.listing
                )
            await repository.update_user_added_product_for_run(
                session.session_id, updated, run_id=run.run_id
            )
            await db_session.commit()

        async with session_factory() as db_session:
            loaded = (
                await ProductRepository(db_session).list_user_added_products(
                    session.session_id
                )
            )[0]
            assert set(loaded.possible_product_ids) == set(updated.possible_product_ids)
            assert loaded.product is None and loaded.listing is None
    finally:
        await engine.dispose()


def test_name_lookup_result_is_not_a_match_without_extraction_decision() -> None:
    user_added = UserAddedProduct(input_text="Northstar Arc 27")
    result = SearchResult(
        query=SearchQuery(
            query="Northstar Arc 27 official retailer listing",
            intent=SearchIntent.DISCOVERY,
        ),
        url="https://shop.example/unrelated-monitor",
        title="Unrelated monitor",
        source_type=SourceType.RETAILER_LISTING,
        provider=ProviderMetadata(
            provider_name="fixture-search",
            raw={"user_added_candidate_id": str(user_added.candidate_id)},
        ),
    )
    snapshot = SourceSnapshot(
        url=result.url,
        source_type=SourceType.RETAILER_LISTING,
        provider=ProviderMetadata(provider_name="fixture-extraction"),
        extraction_status=ExtractionStatus.SUCCEEDED,
    )
    product = CanonicalProduct(
        name="Unrelated monitor", source_ids=(snapshot.source_id,)
    )
    listing = ProductListing(
        product_id=product.product_id,
        title=product.name,
        url=result.url,
        seller=SellerProfile(
            seller_name="Example Shop", source_ids=(snapshot.source_id,)
        ),
        source_ids=(snapshot.source_id,),
    )
    extracted = _source_extractions_from_agent(
        DiscoveredSourceExtraction(search_result=result, snapshot=snapshot),
        ExtractionAgentOutput(products=(product,), listings=(listing,)),
    )

    assert extracted[0].listing_extraction.listing.user_added_matches == ()
    assert _deduplicated_user_added_products((user_added,), extracted) == (user_added,)


@pytest.mark.asyncio
async def test_source_intelligence_stage_does_not_inject_unrelated_fixture_products(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-source-intelligence.sqlite3",
    )
    engine = create_database_engine(settings)
    transcript_provider = RecordingTranscriptProvider()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(
                    query="Need a durable office chair"
                ),
                current_brief=ShoppingBrief(
                    original_query="Need a durable office chair",
                    category="office chair",
                    category_source=FieldSource.USER_PROVIDED,
                ),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                ),
                search_provider=ListingSearchProvider(),
                extraction_provider=RecordingExtractionProvider(),
                transcript_provider=transcript_provider,
                default_region_code="US",
            )
            context = await orchestrator.run(
                run.run_id,
                shopping_session.current_brief,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            run_repository = RunRepository(db_session)
            video_repository = VideoReviewRepository(db_session)
            source_intelligence_repository = SourceIntelligenceRepository(db_session)
            events = await run_repository.list_events(run.run_id)
            video_sources = await video_repository.list_video_sources(run.run_id)
            transcript_segments = await video_repository.list_transcript_segments(
                run.run_id
            )
            community_evidence = (
                await source_intelligence_repository.list_community_evidence(run.run_id)
            )
            amazon_evidence = await source_intelligence_repository.list_amazon_evidence(
                run.run_id
            )
            ikea_evidence = await source_intelligence_repository.list_ikea_evidence(
                run.run_id
            )
            reusable_gaps = (
                await source_intelligence_repository.list_reusable_source_evidence_gaps(
                    run.run_id
                )
            )

        assert context.source_intelligence is not None
        assert len(transcript_provider.calls) == 1
        assert transcript_provider.calls[0][1] is not None
        assert len(context.source_intelligence.video_bundles) == 1
        assert len(context.source_intelligence.community_bundles) == 1
        assert context.source_intelligence.amazon_bundles == ()
        assert context.source_intelligence.ikea_bundles == ()
        assert (
            video_sources[0].transcript_availability == TranscriptAvailability.AVAILABLE
        )
        assert transcript_segments[0].text is not None
        assert community_evidence
        assert not amazon_evidence
        assert not ikea_evidence
        assert reusable_gaps

        source_intelligence_event = next(
            event for event in events if event.stage == RunStage.SOURCE_INTELLIGENCE
        )
        assert source_intelligence_event.message.startswith("Checked review videos")

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_agent_workflow_records_stage_metadata_without_live_calls(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-live-agents.sqlite3",
        openai_run_profiles={
            "fast": {"model": "small-model"},
            "strong": {"model": "large-model"},
        },
    )
    engine = create_database_engine(settings)
    analyst = RecordingGenericAnalystAgent()
    general = RecordingGeneralShoppingAgent()
    extraction_provider = RecordingExtractionProvider()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            create_request = CreateSessionRequest(query="Need a USB-C monitor")
            shopping_session = await SessionRepository(db_session).create(
                original_input=create_request,
                current_brief=ShoppingBrief(original_query=create_request.query),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                ),
                agent_workflow_mode=AgentWorkflowMode.LIVE,
                agent_model_name="gpt-recording",
                agent_model_resolver=lambda name: (
                    build_openai_agent_run_configuration(
                        settings, agent_name=name
                    ).model
                ),
                intake_agent=RecordingIntakeAgent(),
                general_shopping_agent=general,
                query_planner=RecordingQueryPlannerAgent(),
                discovery_agent=SelectingDiscoveryAgent(),
                extraction_agent=RecordingExtractionAgent(extraction_provider),
                category_router_agent=RecordingCategoryRouterAgent(),
                generic_product_analyst_agent=analyst,
                seller_listing_trust_agent=RecordingSellerListingTrustAgent(),
                comparison_decision_agent=RecordingComparisonDecisionAgent(),
                verifier_critic_agent=RecordingVerifierCriticAgent(),
                search_provider=ListingSearchProvider(),
                extraction_provider=extraction_provider,
                default_region_code="US",
            )

            context = await orchestrator.run(
                run.run_id,
                shopping_session.current_brief,
                original_input=shopping_session.original_input,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            result_repository = ResultRepository(db_session)
            agent_records = await result_repository.list_agent_records(run.run_id)
            result = await result_repository.load_latest_result_bundle(run.run_id)
            stored_products = await ProductRepository(
                db_session
            ).list_canonical_products_for_run(run.run_id)

        assert context.trace_id == f"live-agent-run-{run.run_id}"
        assert context.fixture_output is None
        assert len(stored_products) == 1
        assert stored_products[0].name == "Northstar Arc 27 USB-C Monitor"
        assert context.active_brief.category == "monitor"
        assert len(general.calls) == 1
        assert general.calls[0].brief.category == "monitor"
        assert context.general_owner_draft is not None
        assert (
            context.stage_outputs[RunStage.GENERAL_OWNER].payload["result_author"]
            == "GeneralShoppingAgent"
        )
        assert len(context.selected_source_ids) == 1
        assert len(analyst.calls) == 1
        assert context.category_analyses
        assert context.recommendation_bundle is not None
        assert context.verification_report is not None
        assert context.verification_report.approved is True
        assert result is not None
        assert result.recommendation_bundle.no_strong_buy is True
        assert result.recommendation_bundle.result_author == "GeneralShoppingAgent"
        assert result.recommendation_bundle.verification_action == "approved"
        assert result.recommendation_bundle.final_product_id == (
            context.recommendation_bundle.final_product_id
        )

        records_by_stage = {record.stage: record for record in agent_records}
        assert records_by_stage[RunStage.INTAKE].runtime_mode == "live"
        assert records_by_stage[RunStage.GENERAL_OWNER].agent_name == (
            "GeneralShoppingAgent"
        )
        assert records_by_stage[RunStage.GENERAL_OWNER].model_name == "large-model"
        assert records_by_stage[RunStage.INTAKE].model_name == "small-model"
        assert records_by_stage[RunStage.QUERY_PLANNING].model_name == "small-model"
        assert (
            records_by_stage[RunStage.QUERY_PLANNING].tool_activity[0]["status"]
            == "model_query_plan_completed"
        )
        assert records_by_stage[RunStage.DISCOVERY].agent_name == "DiscoveryAgent"
        assert (
            records_by_stage[RunStage.SOURCE_INTELLIGENCE].agent_name
            == "ProviderSourceIntelligenceServices"
        )
        assert (
            records_by_stage[RunStage.SOURCE_INTELLIGENCE].runtime_mode
            == "provider_service"
        )
        assert records_by_stage[RunStage.SOURCE_INTELLIGENCE].model_name is None
        assert records_by_stage[RunStage.EXTRACTION].model_name == "small-model"
        assert any(
            item["tool_name"] == "research_discovery_decision"
            for item in records_by_stage[RunStage.DISCOVERY].tool_activity
        )
        assert any(
            item["tool_name"] == "research_extraction_decision"
            and item["output"]["products"]
            for item in records_by_stage[RunStage.EXTRACTION].tool_activity
        )
        assert (
            records_by_stage[RunStage.DISCOVERY].tool_activity[0]["input"][
                "allowed_tools"
            ]
            == []
        )
        assert records_by_stage[RunStage.CATEGORY_ANALYSIS].agent_name == (
            "CategoryRouterAgent+ProductAnalysisAgents"
        )
        assert records_by_stage[RunStage.CATEGORY_ANALYSIS].duration_ms is not None
        assert records_by_stage[RunStage.CATEGORY_ANALYSIS].model_name == "large-model"
        assert records_by_stage[RunStage.COMPARISON_DECISION].model_name is None
        assert records_by_stage[RunStage.VERIFICATION].model_name == "large-model"
        assert (
            records_by_stage[RunStage.VERIFICATION].tool_activity[0]["status"]
            == "model_verifier_critic_completed"
        )

    finally:
        await engine.dispose()


def _source_intelligence_source_reference_count(output) -> int:
    return sum(
        len(bundle.source_references)
        for bundles in (
            output.video_bundles,
            output.community_bundles,
            output.amazon_bundles,
            output.ikea_bundles,
        )
        for bundle in bundles
    )
