from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from app.agents import (
    FakeQueryPlannerAgent,
    FakeSellerListingTrustAgent,
    QueryPlannerAgent,
    QueryPlannerAgentInput,
    SellerListingTrustAgent,
    SellerListingTrustAgentInput,
)
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.source_intelligence import SourceIntelligenceRepository
from app.db.repositories.video_sources import VideoReviewRepository
from app.orchestration.fixtures import (
    MonitorFixtureRunOutput,
    build_monitor_fixture_run_output,
)
from app.providers import (
    AmazonProductIntelligenceProvider,
    AmazonProductIntelligenceProviderOptions,
    CommunityDiscussionProvider,
    CommunityDiscussionProviderOptions,
    ExtractionProvider,
    ExtractionProviderOptions,
    FakeAmazonProductIntelligenceProvider,
    FakeCommunityDiscussionProvider,
    FakeExtractionProvider,
    FakeIKEAStoreIntelligenceProvider,
    FakeSearchProvider,
    FakeTranscriptProvider,
    FakeVideoSearchProvider,
    IKEAStoreIntelligenceProvider,
    IKEAStoreIntelligenceProviderOptions,
    ProviderCapabilityFlags,
    ProviderRunStatus,
    SearchProvider,
    SearchProviderOptions,
    SourceQualityMetadata,
    TranscriptProvider,
    TranscriptProviderOptions,
    VideoSearchProvider,
    VideoSearchProviderOptions,
    score_source_quality,
)
from app.schemas.analysis import ListingTrustAssessment
from app.schemas.errors import ErrorBody, ErrorEnvelope
from app.schemas.ids import ListingId, ProductId, RunId, SessionId, SourceId
from app.schemas.intake import ShoppingBrief
from app.schemas.products import (
    CanonicalProduct,
    ProductListing,
    ProductListingExtraction,
)
from app.schemas.regions import RegionCode
from app.schemas.runs import (
    AgentRunRecord,
    RunEvent,
    RunStage,
    RunStatus,
    ShoppingRunRecord,
)
from app.schemas.search_sources import (
    AmazonProductEvidenceBundle,
    CommunityDiscussionEvidenceBundle,
    ExtractionStatus,
    IKEAStoreEvidenceBundle,
    ProviderMetadata,
    ReusableSourceIntelligenceRequest,
    SearchPlan,
    SearchQuery,
    SearchResult,
    SourceEvidence,
    SourceIntelligenceCapability,
    SourceIntelligenceCapabilityDescriptor,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
    VideoReviewEvidenceBundle,
    VideoSource,
)
from app.schemas.source_references import SourceReference
from app.schemas.timestamps import Timestamp, utc_now
from app.services.product_deduplication import (
    DeterministicDeduplicationResult,
    DeterministicProductDeduplicator,
)
from app.services.product_listing_extraction import ProductListingExtractor
from app.services.listing_trust import assess_listing_trust, price_plausibility_contexts
from app.services.video_evidence_creation import (
    VideoEvidenceCreator,
    YouTubeTranscriptIngestor,
)
from app.services.recommendation_trust import (
    integrate_trust_analysis_into_recommendation,
)


_MAX_SOURCE_INTELLIGENCE_PRODUCTS = 3
_MAX_REVIEW_VIDEOS = 3
_IKEA_RELEVANCE_TERMS = (
    "armchair",
    "bed",
    "cabinet",
    "chair",
    "couch",
    "curtain",
    "desk",
    "dresser",
    "furniture",
    "home office",
    "kitchen",
    "lamp",
    "lighting",
    "mattress",
    "rug",
    "shelf",
    "shelving",
    "sofa",
    "storage",
    "table",
    "wardrobe",
)


@dataclass(frozen=True)
class FixtureStageOutput:
    stage: RunStage
    trace_id: str
    summary: str
    payload: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveredSourceExtraction:
    search_result: SearchResult
    snapshot: SourceSnapshot
    listing_extraction: ProductListingExtraction | None = None


@dataclass(frozen=True)
class SourceIntelligenceCandidates:
    products: tuple[CanonicalProduct, ...] = ()
    listings: tuple[ProductListing, ...] = ()
    source_ids: tuple[SourceId, ...] = ()


@dataclass(frozen=True)
class SourceIntelligenceRunOutput:
    request: ReusableSourceIntelligenceRequest
    video_bundles: tuple[VideoReviewEvidenceBundle, ...] = ()
    community_bundles: tuple[CommunityDiscussionEvidenceBundle, ...] = ()
    amazon_bundles: tuple[AmazonProductEvidenceBundle, ...] = ()
    ikea_bundles: tuple[IKEAStoreEvidenceBundle, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def bundle_count(self) -> int:
        return (
            len(self.video_bundles)
            + len(self.community_bundles)
            + len(self.amazon_bundles)
            + len(self.ikea_bundles)
        )

    @property
    def evidence_count(self) -> int:
        return (
            sum(len(bundle.evidence) for bundle in self.video_bundles)
            + sum(len(bundle.evidence) for bundle in self.community_bundles)
            + sum(len(bundle.evidence) for bundle in self.amazon_bundles)
            + sum(len(bundle.evidence) for bundle in self.ikea_bundles)
        )

    @property
    def gap_count(self) -> int:
        return (
            sum(len(bundle.transcript_gap_notes) for bundle in self.video_bundles)
            + sum(len(bundle.evidence_gaps) for bundle in self.community_bundles)
            + sum(len(bundle.evidence_gaps) for bundle in self.amazon_bundles)
            + sum(len(bundle.evidence_gaps) for bundle in self.ikea_bundles)
        )


@dataclass(frozen=True)
class CandidateDeduplicationRunOutput:
    result: DeterministicDeduplicationResult
    pre_dedupe_count: int
    post_dedupe_count: int

    @property
    def listing_count(self) -> int:
        return len(self.result.listings)

    @property
    def collapsed_count(self) -> int:
        return self.result.collapsed_count


@dataclass
class ShoppingRunContext:
    run_id: RunId
    session_id: SessionId
    trace_id: str
    stage_outputs: dict[RunStage, FixtureStageOutput] = field(default_factory=dict)
    events: list[RunEvent] = field(default_factory=list)
    agent_records: list[AgentRunRecord] = field(default_factory=list)
    search_plan: SearchPlan | None = None
    search_plan_id: UUID | None = None
    search_results: tuple[SearchResult, ...] = ()
    source_extractions: tuple[DiscoveredSourceExtraction, ...] = ()
    deduplication: CandidateDeduplicationRunOutput | None = None
    source_intelligence: SourceIntelligenceRunOutput | None = None
    trust_assessments: tuple[ListingTrustAssessment, ...] = ()
    fixture_output: MonitorFixtureRunOutput | None = None


class ShoppingRunPersistenceHooks(Protocol):
    async def load_run(self, run_id: RunId) -> ShoppingRunRecord | None:
        """Load the persisted run before orchestration starts."""

    async def emit_event(
        self,
        run_id: RunId,
        *,
        stage: RunStage,
        status: RunStatus,
        message: str,
        error: ErrorEnvelope | None = None,
    ) -> RunEvent:
        """Persist and return one run event."""

    async def record_stage_trace(
        self,
        *,
        run_id: RunId,
        stage: RunStage,
        agent_name: str,
        status: RunStatus,
        trace_id: str,
        started_at: Timestamp,
        ended_at: Timestamp,
    ) -> AgentRunRecord:
        """Persist and return the trace record for a deterministic fixture stage."""

    async def persist_fixture_output(
        self,
        context: ShoppingRunContext,
        output: MonitorFixtureRunOutput,
    ) -> None:
        """Persist the fixture shopping-run output."""

    async def persist_search_plan(
        self,
        context: ShoppingRunContext,
        plan: SearchPlan,
    ) -> UUID:
        """Persist the query plan before provider discovery starts."""

    async def persist_search_results(
        self,
        context: ShoppingRunContext,
        results: tuple[SearchResult, ...],
        *,
        plan_id: UUID,
    ) -> None:
        """Persist provider discovery results without extracting them."""

    async def persist_source_extractions(
        self,
        context: ShoppingRunContext,
        extractions: tuple[DiscoveredSourceExtraction, ...],
    ) -> None:
        """Persist extracted snapshots before candidate grouping."""

    async def persist_candidate_deduplication(
        self,
        context: ShoppingRunContext,
        output: CandidateDeduplicationRunOutput,
    ) -> None:
        """Persist grouped canonical products, listings, and shortlist candidates."""

    async def persist_source_intelligence(
        self,
        context: ShoppingRunContext,
        output: SourceIntelligenceRunOutput,
    ) -> None:
        """Persist reusable source-intelligence snapshots and evidence bundles."""


class RepositoryShoppingRunPersistenceHooks:
    def __init__(
        self,
        *,
        run_repository: RunRepository,
        result_repository: ResultRepository,
        search_source_repository: SearchSourceRepository | None = None,
        product_repository: ProductRepository | None = None,
        source_intelligence_repository: SourceIntelligenceRepository | None = None,
        video_review_repository: VideoReviewRepository | None = None,
    ) -> None:
        self._run_repository = run_repository
        self._result_repository = result_repository
        self._search_source_repository = search_source_repository
        self._product_repository = product_repository
        self._source_intelligence_repository = source_intelligence_repository
        self._video_review_repository = video_review_repository

    async def load_run(self, run_id: RunId) -> ShoppingRunRecord | None:
        return await self._run_repository.get(run_id)

    async def emit_event(
        self,
        run_id: RunId,
        *,
        stage: RunStage,
        status: RunStatus,
        message: str,
        error: ErrorEnvelope | None = None,
    ) -> RunEvent:
        event = await self._run_repository.append_event(
            run_id,
            stage=stage,
            status=status,
            message=message,
            error=error,
        )
        if event is None:
            raise ValueError(f"Run not found: {run_id}")
        return event

    async def record_stage_trace(
        self,
        *,
        run_id: RunId,
        stage: RunStage,
        agent_name: str,
        status: RunStatus,
        trace_id: str,
        started_at: Timestamp,
        ended_at: Timestamp,
    ) -> AgentRunRecord:
        return await self._result_repository.add_agent_record(
            AgentRunRecord(
                run_id=run_id,
                stage=stage,
                agent_name=agent_name,
                status=status,
                started_at=started_at,
                ended_at=ended_at,
                trace_id=trace_id,
            )
        )

    async def persist_fixture_output(
        self,
        context: ShoppingRunContext,
        output: MonitorFixtureRunOutput,
    ) -> None:
        if self._search_source_repository is None or self._product_repository is None:
            raise ValueError("fixture output persistence requires all repositories.")

        for snapshot in output.source_snapshots:
            await self._search_source_repository.add_source_snapshot(
                context.run_id,
                snapshot,
            )
        for evidence in output.source_evidence:
            await self._search_source_repository.add_source_evidence(
                context.run_id,
                evidence,
            )

        for product in output.products:
            await self._product_repository.add_canonical_product(
                context.run_id,
                product,
            )
        for listing in output.listings:
            await self._product_repository.add_product_listing(context.run_id, listing)
        if not any(
            item.listing_extraction is not None for item in context.source_extractions
        ):
            for item in output.shortlist_items:
                await self._product_repository.add_shortlist_membership(
                    context.run_id,
                    product_id=item.product_id,
                    listing_id=item.listing_id,
                    candidate_id=item.candidate_id,
                    position=item.position,
                )
        for user_added in output.user_added_products:
            await self._product_repository.add_user_added_product(
                context.session_id,
                user_added,
                run_id=context.run_id,
            )

        trust_assessments = context.trust_assessments or output.trust_assessments
        recommendation_bundle = integrate_trust_analysis_into_recommendation(
            output.recommendation_bundle,
            trust_assessments,
        )

        await self._result_repository.save_result_bundle(
            context.run_id,
            trust_assessments=trust_assessments,
            category_analyses=output.category_analyses,
            agent_records=(),
            recommendation_bundle=recommendation_bundle,
        )

    async def persist_search_plan(
        self,
        context: ShoppingRunContext,
        plan: SearchPlan,
    ) -> UUID:
        if self._search_source_repository is None:
            raise ValueError("search plan persistence requires a repository.")
        return await self._search_source_repository.create_search_plan(
            context.run_id,
            plan,
        )

    async def persist_search_results(
        self,
        context: ShoppingRunContext,
        results: tuple[SearchResult, ...],
        *,
        plan_id: UUID,
    ) -> None:
        if self._search_source_repository is None:
            raise ValueError("search result persistence requires a repository.")
        for result in results:
            await self._search_source_repository.add_search_result(
                context.run_id,
                result,
                plan_id=plan_id,
            )

    async def persist_source_extractions(
        self,
        context: ShoppingRunContext,
        extractions: tuple[DiscoveredSourceExtraction, ...],
    ) -> None:
        if self._search_source_repository is None:
            raise ValueError("source extraction persistence requires a repository.")

        for item in extractions:
            await self._search_source_repository.add_source_snapshot(
                context.run_id,
                item.snapshot,
                search_result_id=item.search_result.source_id,
            )

    async def persist_candidate_deduplication(
        self,
        context: ShoppingRunContext,
        output: CandidateDeduplicationRunOutput,
    ) -> None:
        if self._product_repository is None:
            raise ValueError(
                "candidate deduplication persistence requires a repository."
            )

        shortlist_position = 1
        for group in output.result.groups:
            await self._product_repository.add_canonical_product(
                context.run_id,
                group.product,
            )
            for listing in group.listings:
                await self._product_repository.add_product_listing(
                    context.run_id,
                    listing,
                )
            primary_listing_id = (
                group.listings[0].listing_id if group.listings else None
            )
            await self._product_repository.add_shortlist_membership(
                context.run_id,
                product_id=group.product.product_id,
                listing_id=primary_listing_id,
                position=shortlist_position,
            )
            shortlist_position += 1

    async def persist_source_intelligence(
        self,
        context: ShoppingRunContext,
        output: SourceIntelligenceRunOutput,
    ) -> None:
        if output.bundle_count == 0:
            return
        if (
            self._search_source_repository is None
            or self._source_intelligence_repository is None
            or self._video_review_repository is None
        ):
            raise ValueError(
                "source intelligence persistence requires all source repositories."
            )

        for bundle in output.video_bundles:
            await self._persist_bundle_source_snapshots(
                context,
                output,
                SourceIntelligenceCapability.VIDEO_REVIEW,
                bundle.source_references,
                source_type=SourceType.VIDEO,
                videos=bundle.videos,
            )
            await self._video_review_repository.add_video_review_bundle(
                context.run_id,
                bundle,
            )
        for bundle in output.community_bundles:
            await self._persist_bundle_source_snapshots(
                context,
                output,
                SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
                bundle.source_references,
                source_type=SourceType.COMMUNITY_DISCUSSION,
            )
            await self._source_intelligence_repository.add_community_discussion_bundle(
                context.run_id,
                bundle,
            )
        for bundle in output.amazon_bundles:
            await self._persist_bundle_source_snapshots(
                context,
                output,
                SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
                bundle.source_references,
                source_type=SourceType.RETAILER_LISTING,
            )
            await self._source_intelligence_repository.add_amazon_product_bundle(
                context.run_id,
                bundle,
            )
        for bundle in output.ikea_bundles:
            await self._persist_bundle_source_snapshots(
                context,
                output,
                SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
                bundle.source_references,
                source_type=SourceType.OFFICIAL_BRAND_PAGE,
            )
            await self._source_intelligence_repository.add_ikea_store_bundle(
                context.run_id,
                bundle,
            )

    async def _persist_bundle_source_snapshots(
        self,
        context: ShoppingRunContext,
        output: SourceIntelligenceRunOutput,
        capability: SourceIntelligenceCapability,
        source_references: tuple[SourceReference, ...],
        *,
        source_type: SourceType,
        videos: tuple[VideoSource, ...] = (),
    ) -> None:
        if self._search_source_repository is None:
            raise ValueError("source snapshot persistence requires a repository.")

        video_by_url = {str(video.url): video for video in videos}
        provider_name = _provider_name_for(output.request, capability)
        for reference in source_references:
            existing = await self._search_source_repository.get_source_snapshot(
                reference.source_id,
            )
            if existing is not None:
                continue
            await self._search_source_repository.add_source_snapshot(
                context.run_id,
                SourceSnapshot(
                    source_id=reference.source_id,
                    url=reference.url,
                    source_type=source_type,
                    provider=ProviderMetadata(
                        provider_name=provider_name,
                        raw={
                            "capability": capability.value,
                            "source_intelligence_request_id": str(
                                output.request.request_id
                            ),
                        },
                    ),
                    title=reference.title,
                    extraction_status=ExtractionStatus.NOT_ATTEMPTED,
                    quality=SourceQuality(level=SourceQualityLevel.UNKNOWN),
                    video=video_by_url.get(str(reference.url)),
                ),
            )


@dataclass(frozen=True)
class _StageDefinition:
    stage: RunStage
    agent_name: str
    message: str


class ShoppingRunOrchestrator:
    _STAGES: tuple[_StageDefinition, ...] = (
        _StageDefinition(
            RunStage.INTAKE,
            "FixtureIntakeStage",
            "Fixture intake stage recorded.",
        ),
        _StageDefinition(
            RunStage.QUERY_PLANNING,
            "QueryPlanningStage",
            "Search queries planned.",
        ),
        _StageDefinition(
            RunStage.DISCOVERY,
            "SearchProviderDiscoveryStage",
            "Search provider discovery completed.",
        ),
        _StageDefinition(
            RunStage.EXTRACTION,
            "SourceExtractionStage",
            "Shopping sources checked.",
        ),
        _StageDefinition(
            RunStage.DEDUPLICATION,
            "DeterministicProductDeduplicationStage",
            "Product candidates grouped.",
        ),
        _StageDefinition(
            RunStage.SOURCE_INTELLIGENCE,
            "ReusableSourceIntelligenceStage",
            "Reusable source evidence checked.",
        ),
        _StageDefinition(
            RunStage.LISTING_TRUST,
            "SellerListingTrustAgent",
            "Seller and listing trust checked.",
        ),
        _StageDefinition(
            RunStage.CATEGORY_ANALYSIS,
            "FixtureCategoryAnalysisStage",
            "Fixture category analysis stage recorded.",
        ),
        _StageDefinition(
            RunStage.COMPARISON_DECISION,
            "FixtureComparisonDecisionStage",
            "Fixture comparison decision stage recorded.",
        ),
        _StageDefinition(
            RunStage.VERIFICATION,
            "FixtureVerificationStage",
            "Fixture verification stage recorded.",
        ),
    )

    def __init__(
        self,
        persistence_hooks: ShoppingRunPersistenceHooks,
        *,
        query_planner: QueryPlannerAgent | None = None,
        search_provider: SearchProvider | None = None,
        extraction_provider: ExtractionProvider | None = None,
        video_search_provider: VideoSearchProvider | None = None,
        transcript_provider: TranscriptProvider | None = None,
        community_discussion_provider: CommunityDiscussionProvider | None = None,
        amazon_product_intelligence_provider: (
            AmazonProductIntelligenceProvider | None
        ) = None,
        ikea_store_intelligence_provider: IKEAStoreIntelligenceProvider | None = None,
        product_deduplicator: DeterministicProductDeduplicator | None = None,
        seller_listing_trust_agent: SellerListingTrustAgent | None = None,
        default_region_code: RegionCode = "US",
    ) -> None:
        self._persistence_hooks = persistence_hooks
        self._query_planner = query_planner or FakeQueryPlannerAgent()
        self._search_provider = search_provider or FakeSearchProvider()
        self._extraction_provider = extraction_provider or FakeExtractionProvider()
        self._video_search_provider = video_search_provider or FakeVideoSearchProvider()
        self._transcript_provider = transcript_provider or FakeTranscriptProvider()
        self._community_discussion_provider = (
            community_discussion_provider or FakeCommunityDiscussionProvider()
        )
        self._amazon_product_intelligence_provider = (
            amazon_product_intelligence_provider
            or FakeAmazonProductIntelligenceProvider()
        )
        self._ikea_store_intelligence_provider = (
            ikea_store_intelligence_provider or FakeIKEAStoreIntelligenceProvider()
        )
        self._listing_extractor = ProductListingExtractor()
        self._product_deduplicator = (
            product_deduplicator or DeterministicProductDeduplicator()
        )
        self._seller_listing_trust_agent = (
            seller_listing_trust_agent or FakeSellerListingTrustAgent()
        )
        self._transcript_ingestor = YouTubeTranscriptIngestor()
        self._video_evidence_creator = VideoEvidenceCreator()
        self._default_region_code = default_region_code

    @classmethod
    def stage_order(cls) -> tuple[RunStage, ...]:
        return tuple(stage.stage for stage in cls._STAGES) + (RunStage.COMPLETE,)

    @classmethod
    def executable_stage_order(cls) -> tuple[RunStage, ...]:
        return tuple(stage.stage for stage in cls._STAGES)

    async def run(
        self,
        run_id: RunId,
        brief: ShoppingBrief | None = None,
    ) -> ShoppingRunContext:
        run = await self._persistence_hooks.load_run(run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")

        context = ShoppingRunContext(
            run_id=run_id,
            session_id=run.session_id,
            trace_id=self._run_trace_id(run_id),
        )
        fixture_output = build_monitor_fixture_run_output(
            run_id=context.run_id,
            session_id=context.session_id,
        )
        context.fixture_output = fixture_output
        active_brief = brief or ShoppingBrief(
            original_query=fixture_output.search_plan.queries[0].query
        )

        try:
            for definition in self._STAGES:
                await self._run_stage(context, definition, active_brief)

            await self._persistence_hooks.persist_fixture_output(
                context,
                fixture_output,
            )

            complete_event = await self._persistence_hooks.emit_event(
                run_id,
                stage=RunStage.COMPLETE,
                status=RunStatus.SUCCEEDED,
                message="Fixture shopping run completed.",
            )
            context.events.append(complete_event)
        except Exception as exc:
            failed_stage = self._current_or_initial_stage(context)
            failed_event = await self._persistence_hooks.emit_event(
                run_id,
                stage=failed_stage,
                status=RunStatus.FAILED,
                message="Fixture shopping run failed.",
                error=_orchestrator_error(context.trace_id, failed_stage, exc),
            )
            context.events.append(failed_event)
            raise

        return context

    async def _run_stage(
        self,
        context: ShoppingRunContext,
        definition: _StageDefinition,
        brief: ShoppingBrief,
    ) -> None:
        started_at = utc_now()
        if definition.stage == RunStage.QUERY_PLANNING:
            stage_output = await self._plan_queries(context, brief)
        elif definition.stage == RunStage.DISCOVERY:
            stage_output = await self._discover_sources(context, brief)
        elif definition.stage == RunStage.EXTRACTION:
            stage_output = await self._extract_sources(context, brief)
        elif definition.stage == RunStage.DEDUPLICATION:
            stage_output = await self._deduplicate_candidates(context)
        elif definition.stage == RunStage.SOURCE_INTELLIGENCE:
            stage_output = await self._run_source_intelligence(context, brief)
        elif definition.stage == RunStage.LISTING_TRUST:
            stage_output = await self._run_listing_trust(context)
        else:
            stage_output = self._fixture_stage_output(context, definition.stage)
        ended_at = utc_now()

        context.stage_outputs[definition.stage] = stage_output
        agent_record = await self._persistence_hooks.record_stage_trace(
            run_id=context.run_id,
            stage=definition.stage,
            agent_name=definition.agent_name,
            status=RunStatus.SUCCEEDED,
            trace_id=stage_output.trace_id,
            started_at=started_at,
            ended_at=ended_at,
        )
        context.agent_records.append(agent_record)

        event = await self._persistence_hooks.emit_event(
            context.run_id,
            stage=definition.stage,
            status=RunStatus.RUNNING,
            message=(
                stage_output.summary
                if definition.stage
                in {
                    RunStage.EXTRACTION,
                    RunStage.DEDUPLICATION,
                    RunStage.SOURCE_INTELLIGENCE,
                    RunStage.LISTING_TRUST,
                }
                else definition.message
            ),
        )
        context.events.append(event)

    async def _plan_queries(
        self,
        context: ShoppingRunContext,
        brief: ShoppingBrief,
    ) -> FixtureStageOutput:
        plan = await self._query_planner.run(
            QueryPlannerAgentInput(run_id=context.run_id, brief=brief)
        )
        region_code = _effective_region_code(brief, self._default_region_code)
        plan = plan.model_copy(
            update={
                "queries": tuple(
                    query
                    if query.region_code is not None
                    else query.model_copy(update={"region_code": region_code})
                    for query in plan.queries
                )
            }
        )
        plan_id = await self._persistence_hooks.persist_search_plan(context, plan)
        context.search_plan = plan
        context.search_plan_id = plan_id
        return FixtureStageOutput(
            stage=RunStage.QUERY_PLANNING,
            trace_id=self._stage_trace_id(context.trace_id, RunStage.QUERY_PLANNING),
            summary="Search queries planned.",
            payload={"query_count": str(len(plan.queries))},
        )

    async def _discover_sources(
        self,
        context: ShoppingRunContext,
        brief: ShoppingBrief,
    ) -> FixtureStageOutput:
        if context.search_plan is None or context.search_plan_id is None:
            raise ValueError("search discovery requires a persisted query plan.")

        region_code = _effective_region_code(brief, self._default_region_code)
        options = SearchProviderOptions(
            region_code=region_code,
            category=brief.category,
        )
        discovered: list[SearchResult] = []
        for query in context.search_plan.queries:
            provider_results = await self._search_provider.search(query, options)
            discovered.extend(
                _score_search_results(
                    tuple(
                        _apply_planned_source_type(result, query)
                        for result in provider_results
                    ),
                    region_code=region_code,
                )
            )

        context.search_results = tuple(discovered)
        await self._persistence_hooks.persist_search_results(
            context,
            context.search_results,
            plan_id=context.search_plan_id,
        )
        provider_name = getattr(
            self._search_provider,
            "provider_name",
            self._search_provider.__class__.__name__,
        )
        return FixtureStageOutput(
            stage=RunStage.DISCOVERY,
            trace_id=self._stage_trace_id(context.trace_id, RunStage.DISCOVERY),
            summary="Search provider discovery completed.",
            payload={
                "provider": str(provider_name),
                "result_count": str(len(context.search_results)),
            },
        )

    async def _extract_sources(
        self,
        context: ShoppingRunContext,
        brief: ShoppingBrief,
    ) -> FixtureStageOutput:
        region_code = _effective_region_code(brief, self._default_region_code)
        extracted_sources: list[DiscoveredSourceExtraction] = []
        for result in _selected_extraction_results(context.search_results):
            snapshot = await self._extraction_provider.extract(
                result.url,
                ExtractionProviderOptions(source_type=result.source_type),
            )
            snapshot = _link_snapshot_to_search_result(
                snapshot,
                result,
                region_code=region_code,
            )
            listing_extraction = _listing_from_extracted_source(
                self._listing_extractor,
                result=result,
                snapshot=snapshot,
                category=brief.category,
            )
            extracted_sources.append(
                DiscoveredSourceExtraction(
                    search_result=result,
                    snapshot=snapshot,
                    listing_extraction=listing_extraction,
                )
            )

        context.source_extractions = tuple(extracted_sources)
        await self._persistence_hooks.persist_source_extractions(
            context,
            context.source_extractions,
        )
        listing_count = sum(
            item.listing_extraction is not None for item in context.source_extractions
        )
        provider_name = getattr(
            self._extraction_provider,
            "provider_name",
            self._extraction_provider.__class__.__name__,
        )
        return FixtureStageOutput(
            stage=RunStage.EXTRACTION,
            trace_id=self._stage_trace_id(context.trace_id, RunStage.EXTRACTION),
            summary=(
                f"Checked {_counted(len(context.source_extractions), 'shopping source')} "
                f"and added {_counted(listing_count, 'product')} to compare."
            ),
            payload={
                "provider": str(provider_name),
                "snapshot_count": str(len(context.source_extractions)),
                "listing_count": str(listing_count),
            },
        )

    async def _deduplicate_candidates(
        self,
        context: ShoppingRunContext,
    ) -> FixtureStageOutput:
        candidate_extractions = tuple(
            item.listing_extraction
            for item in context.source_extractions
            if item.listing_extraction is not None
        )
        result = self._product_deduplicator.group(candidate_extractions)
        output = CandidateDeduplicationRunOutput(
            result=result,
            pre_dedupe_count=len(candidate_extractions),
            post_dedupe_count=len(result.groups),
        )
        context.source_extractions = _deduplicated_source_extractions(
            context.source_extractions,
            result,
        )
        context.deduplication = output
        await self._persistence_hooks.persist_candidate_deduplication(context, output)

        return FixtureStageOutput(
            stage=RunStage.DEDUPLICATION,
            trace_id=self._stage_trace_id(context.trace_id, RunStage.DEDUPLICATION),
            summary=_deduplication_summary(output),
            payload={
                "pre_dedupe_count": str(output.pre_dedupe_count),
                "post_dedupe_count": str(output.post_dedupe_count),
                "listing_count": str(output.listing_count),
                "collapsed_count": str(output.collapsed_count),
            },
        )

    async def _run_source_intelligence(
        self,
        context: ShoppingRunContext,
        brief: ShoppingBrief,
    ) -> FixtureStageOutput:
        region_code = _effective_region_code(brief, self._default_region_code)
        candidates = _source_intelligence_candidates(
            context.source_extractions,
            limit=_MAX_SOURCE_INTELLIGENCE_PRODUCTS,
        )
        request = _source_intelligence_request(
            brief,
            region_code,
            candidates,
            video_capabilities=self._video_search_provider.capabilities,
            transcript_capabilities=self._transcript_provider.capabilities,
            community_capabilities=self._community_discussion_provider.capabilities,
            amazon_capabilities=(
                self._amazon_product_intelligence_provider.capabilities
            ),
            ikea_capabilities=self._ikea_store_intelligence_provider.capabilities,
        )

        video_bundles: list[VideoReviewEvidenceBundle] = []
        community_bundles: list[CommunityDiscussionEvidenceBundle] = []
        amazon_bundles: list[AmazonProductEvidenceBundle] = []
        ikea_bundles: list[IKEAStoreEvidenceBundle] = []
        notes: list[str] = []

        if _capability_allowed(
            request,
            SourceIntelligenceCapability.VIDEO_REVIEW,
        ):
            video_result = await self._video_search_provider.search_videos(
                _video_review_query(brief, candidates.products),
                VideoSearchProviderOptions(
                    region_code=region_code,
                    max_results=_MAX_REVIEW_VIDEOS,
                ),
            )
            notes.extend(video_result.notes)
            if (
                video_result.status == ProviderRunStatus.SUCCEEDED
                and video_result.bundle is not None
            ):
                video_bundle = _limited_video_bundle(
                    video_result.bundle,
                    limit=_MAX_REVIEW_VIDEOS,
                )
                video_bundle = await self._transcript_ingestor.ingest(
                    video_bundle,
                    self._transcript_provider,
                    TranscriptProviderOptions(),
                )
                video_bundles.append(self._video_evidence_creator.create(video_bundle))

        if _capability_allowed(
            request,
            SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
        ):
            community_result = (
                await self._community_discussion_provider.search_discussions(
                    _community_discussion_query(brief, candidates.products),
                    products=candidates.products,
                    options=CommunityDiscussionProviderOptions(
                        region_code=region_code,
                        max_results=_MAX_SOURCE_INTELLIGENCE_PRODUCTS,
                    ),
                )
            )
            notes.extend(community_result.notes)
            if (
                community_result.status == ProviderRunStatus.SUCCEEDED
                and community_result.bundle is not None
            ):
                community_bundles.append(community_result.bundle)

        if _capability_allowed(
            request,
            SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
        ):
            listings_by_product_id = _listings_by_product_id(candidates.listings)
            for product in candidates.products:
                amazon_result = await self._amazon_product_intelligence_provider.fetch_product_evidence(
                    product,
                    listings=listings_by_product_id.get(product.product_id, ()),
                    options=AmazonProductIntelligenceProviderOptions(
                        region_code=region_code,
                    ),
                )
                notes.extend(amazon_result.notes)
                if (
                    amazon_result.status == ProviderRunStatus.SUCCEEDED
                    and amazon_result.bundle is not None
                ):
                    amazon_bundles.append(amazon_result.bundle)

        if _capability_allowed(
            request,
            SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
        ) and _ikea_source_relevant(brief, candidates.products, context.search_results):
            for product in candidates.products:
                ikea_result = (
                    await self._ikea_store_intelligence_provider.fetch_store_evidence(
                        product,
                        options=IKEAStoreIntelligenceProviderOptions(
                            region_code=region_code,
                        ),
                    )
                )
                notes.extend(ikea_result.notes)
                if (
                    ikea_result.status == ProviderRunStatus.SUCCEEDED
                    and ikea_result.bundle is not None
                ):
                    ikea_bundles.append(ikea_result.bundle)

        output = SourceIntelligenceRunOutput(
            request=request,
            video_bundles=tuple(video_bundles),
            community_bundles=tuple(community_bundles),
            amazon_bundles=tuple(amazon_bundles),
            ikea_bundles=tuple(ikea_bundles),
            notes=tuple(dict.fromkeys(notes)),
        )
        context.source_intelligence = output
        await self._persistence_hooks.persist_source_intelligence(context, output)

        return FixtureStageOutput(
            stage=RunStage.SOURCE_INTELLIGENCE,
            trace_id=self._stage_trace_id(
                context.trace_id,
                RunStage.SOURCE_INTELLIGENCE,
            ),
            summary=_source_intelligence_summary(output),
            payload={
                "bundle_count": str(output.bundle_count),
                "evidence_count": str(output.evidence_count),
                "gap_count": str(output.gap_count),
            },
        )

    async def _run_listing_trust(
        self,
        context: ShoppingRunContext,
    ) -> FixtureStageOutput:
        listings = _listing_trust_targets(context)
        contexts = price_plausibility_contexts(_listing_groups_by_product(listings))
        evidence_by_listing_id = _evidence_by_listing_id(
            context.fixture_output.source_evidence if context.fixture_output else ()
        )
        assessments: list[ListingTrustAssessment] = []
        for listing in listings:
            evidence = evidence_by_listing_id.get(listing.listing_id, ())
            rule_based_assessment = assess_listing_trust(
                listing,
                contexts.get(listing.listing_id),
            )
            assessments.append(
                await self._seller_listing_trust_agent.run(
                    SellerListingTrustAgentInput(
                        run_id=context.run_id,
                        listing=listing,
                        evidence=evidence,
                        rule_based_assessment=rule_based_assessment,
                    )
                )
            )

        context.trust_assessments = tuple(assessments)
        suspicious_count = sum(
            assessment.level.value == "suspicious" for assessment in assessments
        )
        return FixtureStageOutput(
            stage=RunStage.LISTING_TRUST,
            trace_id=self._stage_trace_id(context.trace_id, RunStage.LISTING_TRUST),
            summary=(
                f"Checked seller and listing trust for "
                f"{_counted(len(assessments), 'listing')}."
            ),
            payload={
                "assessment_count": str(len(assessments)),
                "suspicious_count": str(suspicious_count),
            },
        )

    def _fixture_stage_output(
        self,
        context: ShoppingRunContext,
        stage: RunStage,
    ) -> FixtureStageOutput:
        return FixtureStageOutput(
            stage=stage,
            trace_id=self._stage_trace_id(context.trace_id, stage),
            summary=f"Fixture output for {stage.value}.",
            payload={
                "mode": "fixture",
                "stage": stage.value,
            },
        )

    def _current_or_initial_stage(self, context: ShoppingRunContext) -> RunStage:
        if context.events:
            return context.events[-1].stage
        return RunStage.INTAKE

    @staticmethod
    def _run_trace_id(run_id: RunId) -> str:
        return f"fixture-run-{run_id}"

    @staticmethod
    def _stage_trace_id(run_trace_id: str, stage: RunStage) -> str:
        return f"{run_trace_id}:{stage.value}"


def _listing_trust_targets(
    context: ShoppingRunContext,
) -> tuple[ProductListing, ...]:
    listings: list[ProductListing] = []
    if context.deduplication is not None:
        listings.extend(context.deduplication.result.listings)
    if context.fixture_output is not None:
        listings.extend(context.fixture_output.listings)
        listings.extend(
            user_added.listing
            for user_added in context.fixture_output.user_added_products
            if user_added.listing is not None
        )
    return _unique_listings(listings)


def _unique_listings(
    listings: list[ProductListing],
) -> tuple[ProductListing, ...]:
    unique: dict[ListingId, ProductListing] = {}
    for listing in listings:
        unique.setdefault(listing.listing_id, listing)
    return tuple(unique.values())


def _listing_groups_by_product(
    listings: tuple[ProductListing, ...],
) -> tuple[tuple[ProductListing, ...], ...]:
    groups: dict[ProductId, list[ProductListing]] = {}
    for listing in listings:
        groups.setdefault(listing.product_id, []).append(listing)
    return tuple(tuple(group) for group in groups.values())


def _evidence_by_listing_id(
    evidence: tuple[SourceEvidence, ...],
) -> dict[ListingId, tuple[SourceEvidence, ...]]:
    grouped: dict[ListingId, list[SourceEvidence]] = {}
    for item in evidence:
        listing_id = item.target.listing_id
        if listing_id is not None:
            grouped.setdefault(listing_id, []).append(item)
    return {listing_id: tuple(items) for listing_id, items in grouped.items()}


def _orchestrator_error(
    trace_id: str,
    stage: RunStage,
    error: Exception,
) -> ErrorEnvelope:
    return ErrorEnvelope(
        error=ErrorBody(
            code="orchestrator_stage_failed",
            message=str(error) or error.__class__.__name__,
            request_id=trace_id,
            details={"stage": stage.value},
        )
    )


def _score_search_results(
    results: tuple[SearchResult, ...],
    *,
    region_code: RegionCode,
) -> tuple[SearchResult, ...]:
    scored: list[SearchResult] = []
    for result in results:
        assessment = score_source_quality(
            str(result.url),
            SourceQualityMetadata(target_region_code=region_code),
        )
        if assessment.excluded:
            continue
        provider = result.provider.model_copy(
            update={
                "raw": {
                    **result.provider.raw,
                    "source_policy_version": assessment.policy_version,
                    "source_class": assessment.source_class.value,
                    "requires_trust_assessment": (assessment.requires_trust_assessment),
                    "region_relevance": assessment.region_relevance.value,
                    "region_relevance_score": assessment.region_relevance_score,
                }
            }
        )
        scored.append(
            result.model_copy(
                update={
                    "provider": provider,
                    "quality": assessment.quality,
                    "url": assessment.normalized_url,
                }
            )
        )
    return tuple(scored)


def _apply_planned_source_type(
    result: SearchResult,
    query: SearchQuery,
) -> SearchResult:
    if (
        result.source_type == SourceType.SEARCH_RESULT
        and len(query.required_source_types) == 1
    ):
        return result.model_copy(update={"source_type": query.required_source_types[0]})
    return result


def _selected_extraction_results(
    results: tuple[SearchResult, ...],
) -> tuple[SearchResult, ...]:
    return tuple(
        result
        for result in results
        if result.source_type not in {SourceType.SEARCH_RESULT, SourceType.VIDEO}
    )


def _link_snapshot_to_search_result(
    snapshot: SourceSnapshot,
    result: SearchResult,
    *,
    region_code: RegionCode,
) -> SourceSnapshot:
    provider = snapshot.provider.model_copy(
        update={
            "raw": {
                **snapshot.provider.raw,
                "search_result_source_id": str(result.source_id),
                "search_provider": result.provider.provider_name,
                "search_provider_result_id": result.provider.provider_result_id,
                "target_region_code": region_code,
            }
        }
    )
    return snapshot.model_copy(
        update={
            "source_type": result.source_type,
            "title": snapshot.title or result.title,
            "provider": provider,
            "quality": result.quality,
        }
    )


def _listing_from_extracted_source(
    extractor: ProductListingExtractor,
    *,
    result: SearchResult,
    snapshot: SourceSnapshot,
    category: str | None,
) -> ProductListingExtraction | None:
    if snapshot.extraction_status not in {
        ExtractionStatus.SUCCEEDED,
        ExtractionStatus.PARTIAL,
    }:
        return None

    if (
        snapshot.source_type
        in {
            SourceType.PRODUCT_PAGE,
            SourceType.RETAILER_LISTING,
            SourceType.OFFICIAL_BRAND_PAGE,
        }
        and snapshot.extracted_content is not None
    ):
        extracted = extractor.extract_source_snapshot(snapshot)
    else:
        extracted = extractor.extract_search_result(result)

    if category is None or extracted.product.category is not None:
        return extracted
    return extracted.model_copy(
        update={"product": extracted.product.model_copy(update={"category": category})}
    )


def _deduplicated_source_extractions(
    extractions: tuple[DiscoveredSourceExtraction, ...],
    result: DeterministicDeduplicationResult,
) -> tuple[DiscoveredSourceExtraction, ...]:
    grouped_by_listing_id = {
        listing.listing_id: (group.product, listing)
        for group in result.groups
        for listing in group.listings
    }
    grouped_extractions: list[DiscoveredSourceExtraction] = []
    for item in extractions:
        if item.listing_extraction is None:
            grouped_extractions.append(item)
            continue
        grouped = grouped_by_listing_id.get(item.listing_extraction.listing.listing_id)
        if grouped is None:
            grouped_extractions.append(item)
            continue
        product, listing = grouped
        grouped_extractions.append(
            DiscoveredSourceExtraction(
                search_result=item.search_result,
                snapshot=item.snapshot,
                listing_extraction=item.listing_extraction.model_copy(
                    update={
                        "product": product,
                        "listing": listing,
                    }
                ),
            )
        )
    return tuple(grouped_extractions)


def _source_intelligence_candidates(
    extractions: tuple[DiscoveredSourceExtraction, ...],
    *,
    limit: int,
) -> SourceIntelligenceCandidates:
    products_by_id: dict[ProductId, CanonicalProduct] = {}
    listings_by_id: dict[ListingId, ProductListing] = {}
    source_ids: list[SourceId] = []

    for item in extractions:
        source_ids.extend((item.search_result.source_id, item.snapshot.source_id))
        if item.listing_extraction is None:
            continue
        product = item.listing_extraction.product
        listing = item.listing_extraction.listing
        if product.product_id not in products_by_id and len(products_by_id) < limit:
            products_by_id[product.product_id] = product
        if product.product_id in products_by_id:
            listings_by_id.setdefault(listing.listing_id, listing)

    return SourceIntelligenceCandidates(
        products=tuple(products_by_id.values()),
        listings=tuple(listings_by_id.values()),
        source_ids=tuple(dict.fromkeys(source_ids)),
    )


def _source_intelligence_request(
    brief: ShoppingBrief,
    region_code: RegionCode,
    candidates: SourceIntelligenceCandidates,
    *,
    video_capabilities: ProviderCapabilityFlags,
    transcript_capabilities: ProviderCapabilityFlags,
    community_capabilities: ProviderCapabilityFlags,
    amazon_capabilities: ProviderCapabilityFlags,
    ikea_capabilities: ProviderCapabilityFlags,
) -> ReusableSourceIntelligenceRequest:
    return ReusableSourceIntelligenceRequest(
        brief=brief,
        target_region_code=region_code,
        product_ids=tuple(product.product_id for product in candidates.products),
        listing_ids=tuple(listing.listing_id for listing in candidates.listings),
        source_ids=candidates.source_ids,
        query_hints=_source_query_hints(brief, candidates.products),
        requested_capabilities=(
            SourceIntelligenceCapability.VIDEO_REVIEW,
            SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
            SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
            SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
        ),
        allowed_capabilities=(
            _video_descriptor(video_capabilities, transcript_capabilities),
            _community_descriptor(community_capabilities),
            _amazon_descriptor(amazon_capabilities),
            _ikea_descriptor(ikea_capabilities),
        ),
    )


def _video_descriptor(
    video: ProviderCapabilityFlags,
    transcript: ProviderCapabilityFlags,
) -> SourceIntelligenceCapabilityDescriptor:
    return SourceIntelligenceCapabilityDescriptor(
        capability=SourceIntelligenceCapability.VIDEO_REVIEW,
        provider_name=video.provider_name,
        enabled=video.enabled and video.supports_video_search,
        official_access=video.uses_official_api,
        user_authorized_access=(
            transcript.requires_user_authorization
            if transcript.supports_transcripts
            else None
        ),
        compliance_notes=tuple(
            dict.fromkeys((*video.compliance_notes, *transcript.compliance_notes))
        ),
    )


def _community_descriptor(
    capabilities: ProviderCapabilityFlags,
) -> SourceIntelligenceCapabilityDescriptor:
    return SourceIntelligenceCapabilityDescriptor(
        capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
        provider_name=capabilities.provider_name,
        enabled=(
            capabilities.enabled
            and capabilities.supports_community_discussion_retrieval
            and capabilities.supports_domain_scoped_search
        ),
        domain_scoped_search=capabilities.supports_domain_scoped_search,
        compliance_notes=capabilities.compliance_notes,
    )


def _amazon_descriptor(
    capabilities: ProviderCapabilityFlags,
) -> SourceIntelligenceCapabilityDescriptor:
    return SourceIntelligenceCapabilityDescriptor(
        capability=SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
        provider_name=capabilities.provider_name,
        enabled=(
            capabilities.enabled
            and capabilities.supports_amazon_product_intelligence
            and capabilities.supports_amazon_listing_identity
        ),
        marketplace_product_support=capabilities.supports_amazon_product_intelligence,
        marketplace_review_support=capabilities.supports_amazon_review_signals,
        compliance_notes=capabilities.compliance_notes,
    )


def _ikea_descriptor(
    capabilities: ProviderCapabilityFlags,
) -> SourceIntelligenceCapabilityDescriptor:
    return SourceIntelligenceCapabilityDescriptor(
        capability=SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
        provider_name=capabilities.provider_name,
        enabled=capabilities.enabled
        and capabilities.supports_ikea_regional_store_lookup,
        official_access=capabilities.uses_official_api,
        regional_official_store_support=capabilities.supports_ikea_regional_store_lookup,
        compliance_notes=capabilities.compliance_notes,
    )


def _capability_allowed(
    request: ReusableSourceIntelligenceRequest,
    capability: SourceIntelligenceCapability,
) -> bool:
    if capability not in request.requested_capabilities:
        return False
    return any(
        descriptor.capability == capability and descriptor.enabled
        for descriptor in request.allowed_capabilities
    )


def _provider_name_for(
    request: ReusableSourceIntelligenceRequest,
    capability: SourceIntelligenceCapability,
) -> str:
    for descriptor in request.allowed_capabilities:
        if descriptor.capability == capability and descriptor.provider_name:
            return descriptor.provider_name
    return "source-intelligence"


def _source_query_hints(
    brief: ShoppingBrief,
    products: tuple[CanonicalProduct, ...],
) -> tuple[str, ...]:
    hints = [
        brief.original_query,
        *(product.name for product in products[:_MAX_SOURCE_INTELLIGENCE_PRODUCTS]),
    ]
    if brief.category is not None:
        hints.append(brief.category)
    return tuple(value for value in dict.fromkeys(hints) if value)


def _video_review_query(
    brief: ShoppingBrief,
    products: tuple[CanonicalProduct, ...],
) -> str:
    return f"{_source_query_base(brief, products)} review video"[:500].strip()


def _community_discussion_query(
    brief: ShoppingBrief,
    products: tuple[CanonicalProduct, ...],
) -> str:
    return f"{_source_query_base(brief, products)} reddit owner complaints"[
        :500
    ].strip()


def _source_query_base(
    brief: ShoppingBrief,
    products: tuple[CanonicalProduct, ...],
) -> str:
    terms = [product.name for product in products[:2]]
    if brief.category is not None:
        terms.append(brief.category)
    terms.append(brief.original_query)
    return " ".join(dict.fromkeys(term for term in terms if term))[:360].strip()


def _limited_video_bundle(
    bundle: VideoReviewEvidenceBundle,
    *,
    limit: int,
) -> VideoReviewEvidenceBundle:
    selected_videos = bundle.videos[:limit]
    selected_video_ids = {video.video_id for video in selected_videos}
    selected_video_urls = {str(video.url) for video in selected_videos}
    selected_source_references = tuple(
        reference
        for reference in bundle.source_references
        if str(reference.url) in selected_video_urls
    )
    selected_source_ids = {
        reference.source_id for reference in selected_source_references
    }
    selected_segment_ids = {
        segment.segment_id
        for segment in bundle.transcript_segments
        if segment.video_id in selected_video_ids
    }
    selected_segments = tuple(
        segment
        for segment in bundle.transcript_segments
        if segment.segment_id in selected_segment_ids
    )
    selected_evidence = tuple(
        item
        for item in bundle.evidence
        if item.video_id in selected_video_ids
        and item.source_id in selected_source_ids
        and all(
            segment_id in selected_segment_ids
            for segment_id in item.transcript_segment_ids
        )
    )
    return bundle.model_copy(
        update={
            "videos": selected_videos,
            "source_references": selected_source_references,
            "transcript_segments": selected_segments,
            "evidence": selected_evidence,
        }
    )


def _listings_by_product_id(
    listings: tuple[ProductListing, ...],
) -> dict[ProductId, tuple[ProductListing, ...]]:
    grouped: dict[ProductId, list[ProductListing]] = {}
    for listing in listings:
        grouped.setdefault(listing.product_id, []).append(listing)
    return {product_id: tuple(items) for product_id, items in grouped.items()}


def _ikea_source_relevant(
    brief: ShoppingBrief,
    products: tuple[CanonicalProduct, ...],
    search_results: tuple[SearchResult, ...],
) -> bool:
    if any("ikea." in str(result.url).casefold() for result in search_results):
        return True
    haystack = " ".join(
        value
        for value in (
            brief.original_query,
            brief.category,
            *(product.name for product in products),
            *(product.brand or "" for product in products),
        )
        if value
    ).casefold()
    return any(term in haystack for term in _IKEA_RELEVANCE_TERMS)


def _source_intelligence_summary(output: SourceIntelligenceRunOutput) -> str:
    if output.bundle_count == 0:
        return (
            "Checked review videos, community discussions, Amazon listings, "
            "and regional store sources; no additional source evidence was added."
        )
    return (
        "Checked review videos, community discussions, Amazon listings, "
        "and regional store sources; added "
        f"{_counted(output.bundle_count, 'source evidence set')} with "
        f"{_counted(output.evidence_count, 'evidence item')} and preserved "
        f"{_counted(output.gap_count, 'gap')}."
    )


def _deduplication_summary(output: CandidateDeduplicationRunOutput) -> str:
    return (
        f"Grouped {_counted(output.pre_dedupe_count, 'extracted product')} "
        f"into {_counted(output.post_dedupe_count, 'product group')} and kept "
        f"{_counted(output.listing_count, 'listing')}; "
        f"{_counted(output.collapsed_count, 'duplicate')} collapsed."
    )


def _effective_region_code(
    brief: ShoppingBrief,
    default_region_code: RegionCode,
) -> RegionCode:
    if brief.region is not None:
        return brief.region.region.code
    return default_region_code


def _counted(count: int, noun: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"
