from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from pydantic import AnyHttpUrl

from app.agents import (
    AmazonProductIntelligenceAgent,
    AmazonProductIntelligenceAgentInput,
    CategoryRouterAgent,
    CategoryRouterAgentInput,
    ComparisonDecisionAgent,
    ComparisonDecisionAgentInput,
    DiscoveryAgent,
    DiscoveryAgentInput,
    DiscoveryCandidateSummary,
    DiscoveryEvidenceSummary,
    DiscoveryResearchState,
    DiscoverySourceKind,
    ExtractionAgent,
    ExtractionAgentInput,
    ExtractionAgentOutput,
    ExtractionResearchLead,
    ExtractedProductMention,
    ExtractionEvidenceGap,
    FakeQueryPlannerAgent,
    FakeSellerListingTrustAgent,
    GenericProductAnalystAgent,
    IKEAStoreIntelligenceAgent,
    IKEAStoreIntelligenceAgentInput,
    IntakeAgent,
    IntakeAgentInput,
    LaptopSpecialistAgent,
    MonitorSpecialistAgent,
    ProductAnalysisAgentInput,
    QueryPlannerAgent,
    QueryPlannerAgentInput,
    RedditCommunityIntelligenceAgent,
    RedditCommunityIntelligenceAgentInput,
    SellerListingTrustAgent,
    SellerListingTrustAgentInput,
    SmartphoneSpecialistAgent,
    SmartwatchSpecialistAgent,
    TVSpecialistAgent,
    TechnologyDomainAnalystAgent,
    VerificationAgentInput,
    VerificationReport,
    VerifierCriticAgent,
    YouTubeReviewIntelligenceAgent,
    YouTubeReviewIntelligenceAgentInput,
    EarphonesHeadphonesSpecialistAgent,
)
from app.agents.catalog import ProductAnalysisRoute, build_default_agent_catalog
from app.core.settings import AgentWorkflowMode
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
from app.schemas.analysis import (
    CategoryAnalysis,
    ListingTrustAssessment,
    RecommendationBundle,
)
from app.schemas.errors import ErrorBody, ErrorEnvelope
from app.schemas.ids import (
    CandidateId,
    ListingId,
    ProductId,
    RunId,
    SessionId,
    SourceId,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.products import (
    CanonicalProduct,
    ProductListing,
    ProductListingExtraction,
    UserAddedProduct,
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
    EvidenceTarget,
    EvidenceTargetType,
    ExtractionStatus,
    IKEAStoreEvidenceBundle,
    ProviderMetadata,
    ReusableSourceIntelligenceRequest,
    SearchPlan,
    SearchIntent,
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
_MAX_EXTRACTION_SOURCES = 12
_RESEARCH_PAGES_PER_CYCLE = 4
_MAX_RESEARCH_CYCLES = 4
_MAX_FOLLOW_UP_DISCOVERY_CALLS = 2
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
    agent_name: str | None = None
    runtime_mode: str = AgentWorkflowMode.FIXTURE.value
    model_name: str | None = None
    tool_activity: tuple[dict[str, Any], ...] = ()
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_usd: str | None = None
    fallback_outcome: str | None = None


@dataclass(frozen=True)
class DiscoveredSourceExtraction:
    search_result: SearchResult
    snapshot: SourceSnapshot
    listing_extraction: ProductListingExtraction | None = None
    user_added_candidate_id: CandidateId | None = None


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
    active_brief: ShoppingBrief
    original_input: CreateSessionRequest | None = None
    stage_outputs: dict[RunStage, FixtureStageOutput] = field(default_factory=dict)
    events: list[RunEvent] = field(default_factory=list)
    agent_records: list[AgentRunRecord] = field(default_factory=list)
    search_plan: SearchPlan | None = None
    search_plan_id: UUID | None = None
    search_results: tuple[SearchResult, ...] = ()
    selected_source_ids: tuple[SourceId, ...] = ()
    editorial_result_ids: tuple[SourceId, ...] = ()
    collection_result_ids: tuple[SourceId, ...] = ()
    source_extractions: tuple[DiscoveredSourceExtraction, ...] = ()
    extraction_evidence: tuple[SourceEvidence, ...] = ()
    extraction_mentions: tuple[ExtractedProductMention, ...] = ()
    extraction_gaps: tuple[ExtractionEvidenceGap, ...] = ()
    research_activity: list[dict[str, Any]] = field(default_factory=list)
    user_added_products: tuple[UserAddedProduct, ...] = ()
    deduplication: CandidateDeduplicationRunOutput | None = None
    source_intelligence: SourceIntelligenceRunOutput | None = None
    trust_assessments: tuple[ListingTrustAssessment, ...] = ()
    category_analyses: tuple[CategoryAnalysis, ...] = ()
    recommendation_bundle: RecommendationBundle | None = None
    verification_report: VerificationReport | None = None
    fixture_output: MonitorFixtureRunOutput | None = None
    active_stage: RunStage | None = None


class ShoppingRunPersistenceHooks(Protocol):
    async def load_run(self, run_id: RunId) -> ShoppingRunRecord | None:
        """Load the persisted run before orchestration starts."""

    async def checkpoint(self) -> None:
        """Commit durable run progress at a workflow boundary."""

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
        runtime_mode: str | None = None,
        model_name: str | None = None,
        duration_ms: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        estimated_cost_usd: str | None = None,
        tool_activity: tuple[dict[str, Any], ...] = (),
        fallback_outcome: str | None = None,
        error: ErrorEnvelope | None = None,
    ) -> AgentRunRecord:
        """Persist and return the trace record for a workflow stage."""

    async def persist_fixture_output(
        self,
        context: ShoppingRunContext,
        output: MonitorFixtureRunOutput,
    ) -> None:
        """Persist the fixture shopping-run output."""

    async def persist_live_output(self, context: ShoppingRunContext) -> None:
        """Persist a recommendation only from the live research shortlist."""

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

    async def load_snapshot_for_search_result(
        self, context: ShoppingRunContext, source_id: SourceId
    ) -> SourceSnapshot | None:
        """Reuse an approved snapshot already saved by the discovery fetch tool."""

    async def persist_extraction_evidence(
        self, context: ShoppingRunContext, evidence: tuple[SourceEvidence, ...]
    ) -> None:
        """Persist evidence returned by the primary extraction agent."""

    async def load_user_added_products(
        self,
        session_id: SessionId,
    ) -> tuple[UserAddedProduct, ...]:
        """Load products the user added to the session before this run."""

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

    async def checkpoint(self) -> None:
        await self._run_repository.checkpoint()

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
        runtime_mode: str | None = None,
        model_name: str | None = None,
        duration_ms: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        estimated_cost_usd: str | None = None,
        tool_activity: tuple[dict[str, Any], ...] = (),
        fallback_outcome: str | None = None,
        error: ErrorEnvelope | None = None,
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
                runtime_mode=runtime_mode,
                model_name=model_name,
                duration_ms=duration_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=estimated_cost_usd,
                tool_activity=tool_activity,
                fallback_outcome=fallback_outcome,
                error=error,
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
        category_analyses = context.category_analyses or output.category_analyses
        recommendation_bundle = integrate_trust_analysis_into_recommendation(
            context.recommendation_bundle or output.recommendation_bundle,
            trust_assessments,
        )

        await self._result_repository.save_result_bundle(
            context.run_id,
            trust_assessments=trust_assessments,
            category_analyses=category_analyses,
            agent_records=(),
            recommendation_bundle=recommendation_bundle,
        )

    async def persist_live_output(self, context: ShoppingRunContext) -> None:
        if context.recommendation_bundle is None:
            return
        recommendation_bundle = integrate_trust_analysis_into_recommendation(
            context.recommendation_bundle,
            context.trust_assessments,
        )
        await self._result_repository.save_result_bundle(
            context.run_id,
            trust_assessments=context.trust_assessments,
            category_analyses=context.category_analyses,
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
            if (
                await self._search_source_repository.get_search_result_for_run(
                    context.run_id, result.source_id
                )
                is None
            ):
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
            await self._search_source_repository.save_source_snapshot(
                context.run_id,
                item.snapshot,
                search_result_id=(
                    None
                    if _is_direct_user_added_url_extraction(item)
                    else item.search_result.source_id
                ),
            )

    async def load_snapshot_for_search_result(
        self, context: ShoppingRunContext, source_id: SourceId
    ) -> SourceSnapshot | None:
        if self._search_source_repository is None:
            return None
        return await self._search_source_repository.get_snapshot_for_search_result(
            context.run_id, source_id
        )

    async def persist_extraction_evidence(
        self, context: ShoppingRunContext, evidence: tuple[SourceEvidence, ...]
    ) -> None:
        if self._search_source_repository is None:
            raise ValueError("extraction evidence persistence requires a repository")
        for item in evidence:
            await self._search_source_repository.save_source_evidence(
                context.run_id, item
            )

    async def load_user_added_products(
        self,
        session_id: SessionId,
    ) -> tuple[UserAddedProduct, ...]:
        if self._product_repository is None:
            return ()
        return await self._product_repository.list_user_added_products(session_id)

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
        user_added_candidate_by_listing_id = _user_added_candidate_ids_by_listing_id(
            context.user_added_products
        )
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
                candidate_id=_candidate_id_for_group(
                    group.listings,
                    user_added_candidate_by_listing_id,
                ),
                position=shortlist_position,
            )
            shortlist_position += 1

        for user_added in context.user_added_products:
            if user_added.product is None or user_added.listing is None:
                continue
            await self._product_repository.update_user_added_product_for_run(
                context.session_id,
                user_added,
                run_id=context.run_id,
            )

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
        agent_workflow_mode: AgentWorkflowMode = AgentWorkflowMode.FIXTURE,
        agent_model_name: str | None = None,
        agent_model_resolver: Callable[[str], str] | None = None,
        intake_agent: IntakeAgent | None = None,
        query_planner: QueryPlannerAgent | None = None,
        discovery_agent: DiscoveryAgent | None = None,
        extraction_agent: ExtractionAgent | None = None,
        category_router_agent: CategoryRouterAgent | None = None,
        generic_product_analyst_agent: GenericProductAnalystAgent | None = None,
        technology_domain_analyst_agent: TechnologyDomainAnalystAgent | None = None,
        monitor_specialist_agent: MonitorSpecialistAgent | None = None,
        smartphone_specialist_agent: SmartphoneSpecialistAgent | None = None,
        laptop_specialist_agent: LaptopSpecialistAgent | None = None,
        earphones_headphones_specialist_agent: (
            EarphonesHeadphonesSpecialistAgent | None
        ) = None,
        tv_specialist_agent: TVSpecialistAgent | None = None,
        smartwatch_specialist_agent: SmartwatchSpecialistAgent | None = None,
        search_provider: SearchProvider | None = None,
        extraction_provider: ExtractionProvider | None = None,
        video_search_provider: VideoSearchProvider | None = None,
        transcript_provider: TranscriptProvider | None = None,
        community_discussion_provider: CommunityDiscussionProvider | None = None,
        amazon_product_intelligence_provider: (
            AmazonProductIntelligenceProvider | None
        ) = None,
        ikea_store_intelligence_provider: IKEAStoreIntelligenceProvider | None = None,
        youtube_review_intelligence_agent: YouTubeReviewIntelligenceAgent | None = None,
        reddit_community_intelligence_agent: (
            RedditCommunityIntelligenceAgent | None
        ) = None,
        amazon_product_intelligence_agent: AmazonProductIntelligenceAgent | None = None,
        ikea_store_intelligence_agent: IKEAStoreIntelligenceAgent | None = None,
        product_deduplicator: DeterministicProductDeduplicator | None = None,
        seller_listing_trust_agent: SellerListingTrustAgent | None = None,
        comparison_decision_agent: ComparisonDecisionAgent | None = None,
        verifier_critic_agent: VerifierCriticAgent | None = None,
        default_region_code: RegionCode = "US",
    ) -> None:
        self._persistence_hooks = persistence_hooks
        self._agent_workflow_mode = agent_workflow_mode
        self._agent_model_name = agent_model_name
        self._agent_model_resolver = agent_model_resolver
        self._intake_agent = intake_agent
        self._query_planner = query_planner or FakeQueryPlannerAgent()
        self._discovery_agent = discovery_agent
        self._extraction_agent = extraction_agent
        self._category_router_agent = category_router_agent
        self._generic_product_analyst_agent = generic_product_analyst_agent
        self._technology_domain_analyst_agent = technology_domain_analyst_agent
        self._monitor_specialist_agent = monitor_specialist_agent
        self._smartphone_specialist_agent = smartphone_specialist_agent
        self._laptop_specialist_agent = laptop_specialist_agent
        self._earphones_headphones_specialist_agent = (
            earphones_headphones_specialist_agent
        )
        self._tv_specialist_agent = tv_specialist_agent
        self._smartwatch_specialist_agent = smartwatch_specialist_agent
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
        self._youtube_review_intelligence_agent = youtube_review_intelligence_agent
        self._reddit_community_intelligence_agent = reddit_community_intelligence_agent
        self._amazon_product_intelligence_agent = amazon_product_intelligence_agent
        self._ikea_store_intelligence_agent = ikea_store_intelligence_agent
        self._listing_extractor = ProductListingExtractor()
        self._product_deduplicator = (
            product_deduplicator or DeterministicProductDeduplicator()
        )
        self._seller_listing_trust_agent = (
            seller_listing_trust_agent or FakeSellerListingTrustAgent()
        )
        self._comparison_decision_agent = comparison_decision_agent
        self._verifier_critic_agent = verifier_critic_agent
        self._transcript_ingestor = YouTubeTranscriptIngestor()
        self._video_evidence_creator = VideoEvidenceCreator()
        self._default_region_code = default_region_code
        self._agent_catalog = build_default_agent_catalog()

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
        original_input: CreateSessionRequest | None = None,
    ) -> ShoppingRunContext:
        run = await self._persistence_hooks.load_run(run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")

        fixture_output = (
            build_monitor_fixture_run_output(run_id=run_id, session_id=run.session_id)
            if self._agent_workflow_mode != AgentWorkflowMode.LIVE
            else None
        )
        if brief is not None:
            active_brief = brief
        elif original_input is not None:
            active_brief = ShoppingBrief(original_query=original_input.query)
        elif fixture_output is not None:
            active_brief = ShoppingBrief(
                original_query=fixture_output.search_plan.queries[0].query
            )
        else:
            raise ValueError("Live shopping runs require a shopping brief or request.")
        context = ShoppingRunContext(
            run_id=run_id,
            session_id=run.session_id,
            trace_id=self._run_trace_id(run_id),
            active_brief=active_brief,
            original_input=original_input,
        )
        context.fixture_output = fixture_output
        await self._persistence_hooks.checkpoint()

        try:
            for definition in self._STAGES:
                context.active_stage = definition.stage
                await self._run_stage(context, definition)

            if fixture_output is not None:
                await self._persistence_hooks.persist_fixture_output(
                    context, fixture_output
                )
            else:
                await self._persistence_hooks.persist_live_output(context)

            complete_event = await self._persistence_hooks.emit_event(
                run_id,
                stage=RunStage.COMPLETE,
                status=RunStatus.SUCCEEDED,
                message=(
                    "Shopping run completed."
                    if self._agent_workflow_mode == AgentWorkflowMode.LIVE
                    else "Fixture shopping run completed."
                ),
            )
            context.events.append(complete_event)
            await self._persistence_hooks.checkpoint()
        except Exception as exc:
            failed_stage = self._current_or_initial_stage(context)
            failed_event = await self._persistence_hooks.emit_event(
                run_id,
                stage=failed_stage,
                status=RunStatus.FAILED,
                message="Shopping run failed.",
                error=_orchestrator_error(context.trace_id, failed_stage, exc),
            )
            context.events.append(failed_event)
            await self._persistence_hooks.checkpoint()
            raise

        return context

    async def _run_stage(
        self,
        context: ShoppingRunContext,
        definition: _StageDefinition,
    ) -> None:
        started_at = utc_now()
        try:
            if definition.stage == RunStage.INTAKE:
                stage_output = await self._run_intake(context)
            elif definition.stage == RunStage.QUERY_PLANNING:
                stage_output = await self._plan_queries(context)
            elif definition.stage == RunStage.DISCOVERY:
                stage_output = await self._discover_sources(context)
            elif definition.stage == RunStage.EXTRACTION:
                stage_output = await self._extract_sources(context)
            elif definition.stage == RunStage.DEDUPLICATION:
                stage_output = await self._deduplicate_candidates(context)
            elif definition.stage == RunStage.SOURCE_INTELLIGENCE:
                stage_output = await self._run_source_intelligence(context)
            elif definition.stage == RunStage.LISTING_TRUST:
                stage_output = await self._run_listing_trust(context)
            elif definition.stage == RunStage.CATEGORY_ANALYSIS:
                stage_output = await self._run_category_analysis(context)
            elif definition.stage == RunStage.COMPARISON_DECISION:
                stage_output = await self._run_comparison_decision(context)
            elif definition.stage == RunStage.VERIFICATION:
                stage_output = await self._run_verification(context)
            else:
                stage_output = self._fixture_stage_output(context, definition.stage)
        except Exception as exc:
            ended_at = utc_now()
            error = _orchestrator_error(
                self._stage_trace_id(context.trace_id, definition.stage),
                definition.stage,
                exc,
            )
            agent_record = await self._persistence_hooks.record_stage_trace(
                run_id=context.run_id,
                stage=definition.stage,
                agent_name=definition.agent_name,
                status=RunStatus.FAILED,
                trace_id=self._stage_trace_id(context.trace_id, definition.stage),
                started_at=started_at,
                ended_at=ended_at,
                runtime_mode=self._agent_workflow_mode.value,
                model_name=self._model_name_for_stage(definition.stage),
                duration_ms=_duration_ms(started_at, ended_at),
                tool_activity=tuple(context.research_activity)
                if definition.stage == RunStage.EXTRACTION
                else (),
                fallback_outcome="stage_error",
                error=error,
            )
            context.agent_records.append(agent_record)
            raise

        ended_at = utc_now()

        context.stage_outputs[definition.stage] = stage_output
        agent_name = stage_output.agent_name or definition.agent_name
        agent_record = await self._persistence_hooks.record_stage_trace(
            run_id=context.run_id,
            stage=definition.stage,
            agent_name=agent_name,
            status=RunStatus.SUCCEEDED,
            trace_id=stage_output.trace_id,
            started_at=started_at,
            ended_at=ended_at,
            runtime_mode=stage_output.runtime_mode,
            model_name=stage_output.model_name,
            duration_ms=_duration_ms(started_at, ended_at),
            input_tokens=stage_output.input_tokens,
            output_tokens=stage_output.output_tokens,
            total_tokens=stage_output.total_tokens,
            estimated_cost_usd=stage_output.estimated_cost_usd,
            tool_activity=stage_output.tool_activity,
            fallback_outcome=stage_output.fallback_outcome,
        )
        context.agent_records.append(agent_record)

        event = await self._persistence_hooks.emit_event(
            context.run_id,
            stage=definition.stage,
            status=RunStatus.RUNNING,
            message=(
                stage_output.summary
                if stage_output.runtime_mode == AgentWorkflowMode.LIVE.value
                or definition.stage
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
        await self._persistence_hooks.checkpoint()

    async def _run_intake(self, context: ShoppingRunContext) -> FixtureStageOutput:
        if self._agent_workflow_mode != AgentWorkflowMode.LIVE:
            return self._fixture_stage_output(context, RunStage.INTAKE)

        if self._intake_agent is None or context.original_input is None:
            return self._fixture_stage_output(
                context,
                RunStage.INTAKE,
                fallback_outcome="missing_live_intake_input_fallback",
            )

        brief = await self._intake_agent.run(
            IntakeAgentInput(run_id=context.run_id, request=context.original_input)
        )
        context.active_brief = _merge_live_intake_brief(context.active_brief, brief)
        activity = _agent_tool_activity(self._intake_agent)
        return FixtureStageOutput(
            stage=RunStage.INTAKE,
            trace_id=self._stage_trace_id(context.trace_id, RunStage.INTAKE),
            summary="Shopping details prepared.",
            payload={
                "category": context.active_brief.category or "",
                "has_region": str(context.active_brief.region is not None),
                "has_budget": str(context.active_brief.budget is not None),
            },
            agent_name="IntakeAgent",
            runtime_mode=self._agent_workflow_mode.value,
            model_name=self._model_name_for_stage(RunStage.INTAKE),
            tool_activity=activity,
            fallback_outcome=_fallback_outcome(activity),
        )

    async def _plan_queries(
        self,
        context: ShoppingRunContext,
    ) -> FixtureStageOutput:
        brief = context.active_brief
        context.user_added_products = (
            await self._persistence_hooks.load_user_added_products(context.session_id)
        )
        plan = await self._query_planner.run(
            QueryPlannerAgentInput(
                run_id=context.run_id,
                brief=brief,
                user_added_products=context.user_added_products,
            )
        )
        region_code = _effective_region_code(brief, self._default_region_code)
        plan = plan.model_copy(
            update={
                "queries": _dedupe_search_queries(
                    tuple(
                        query
                        if query.region_code is not None
                        else query.model_copy(update={"region_code": region_code})
                        for query in (
                            *plan.queries,
                            *_user_added_lookup_queries(
                                context.user_added_products,
                                region_code=region_code,
                            ),
                        )
                    )
                )
            }
        )
        plan_id = await self._persistence_hooks.persist_search_plan(context, plan)
        context.search_plan = plan
        context.search_plan_id = plan_id
        activity = _agent_tool_activity(self._query_planner)
        return FixtureStageOutput(
            stage=RunStage.QUERY_PLANNING,
            trace_id=self._stage_trace_id(context.trace_id, RunStage.QUERY_PLANNING),
            summary="Search queries planned.",
            payload={"query_count": str(len(plan.queries))},
            agent_name="QueryPlannerAgent",
            runtime_mode=self._agent_workflow_mode.value,
            model_name=self._model_name_for_stage(RunStage.QUERY_PLANNING),
            tool_activity=activity,
            fallback_outcome=_fallback_outcome(activity),
        )

    async def _discover_sources(
        self,
        context: ShoppingRunContext,
    ) -> FixtureStageOutput:
        if context.search_plan is None or context.search_plan_id is None:
            raise ValueError("search discovery requires a persisted query plan.")

        brief = context.active_brief
        region_code = _effective_region_code(brief, self._default_region_code)
        options = SearchProviderOptions(
            region_code=region_code,
            category=brief.category,
        )
        discovered: list[SearchResult] = []
        discovery_gaps: list[dict[str, Any]] = []
        for query in context.search_plan.queries:
            try:
                provider_results = await self._search_provider.search(query, options)
            except Exception as exc:
                if self._agent_workflow_mode != AgentWorkflowMode.LIVE:
                    raise
                discovery_gaps.append(
                    {
                        "tool_name": "provider_search_gap",
                        "status": "provider_unavailable",
                        "input": {"query": query.query},
                        "output": {"reason": exc.__class__.__name__},
                    }
                )
                continue
            user_added = _user_added_product_for_lookup_query(
                query,
                context.user_added_products,
            )
            discovered.extend(
                _score_search_results(
                    tuple(
                        _mark_user_added_lookup_result(
                            result,
                            user_added,
                        )
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
        activity: tuple[dict[str, Any], ...] = tuple(discovery_gaps)
        if (
            self._agent_workflow_mode == AgentWorkflowMode.LIVE
            and self._discovery_agent is not None
        ):
            discovery_output = await self._discovery_agent.run(
                DiscoveryAgentInput(
                    run_id=context.run_id,
                    brief=brief,
                    search_plan=context.search_plan,
                    seed_results=context.search_results,
                )
            )
            context.selected_source_ids = discovery_output.selected_source_ids
            context.editorial_result_ids = tuple(
                decision.source_id
                for decision in discovery_output.source_decisions
                if decision.classification == DiscoverySourceKind.PROFESSIONAL_REVIEW
            )
            context.collection_result_ids = tuple(
                decision.source_id
                for decision in discovery_output.source_decisions
                if decision.classification == DiscoverySourceKind.CATEGORY_COLLECTION
            )
            context.search_results = discovery_output.search_results
            activity = (
                *activity,
                *_agent_tool_activity(self._discovery_agent),
                _discovery_journal(discovery_output, cycle=0),
            )
            context.research_activity.extend(activity)
            await self._persistence_hooks.persist_search_results(
                context,
                discovery_output.search_results,
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
                "selected_source_count": str(len(context.selected_source_ids)),
            },
            agent_name="DiscoveryAgent"
            if self._agent_workflow_mode == AgentWorkflowMode.LIVE
            else "SearchProviderDiscoveryStage",
            runtime_mode=self._agent_workflow_mode.value,
            model_name=self._model_name_for_stage(RunStage.DISCOVERY),
            tool_activity=activity,
            fallback_outcome=_fallback_outcome(activity),
        )

    async def _extract_sources(
        self,
        context: ShoppingRunContext,
    ) -> FixtureStageOutput:
        if self._agent_workflow_mode == AgentWorkflowMode.LIVE and (
            self._discovery_agent is None or self._extraction_agent is None
        ):
            raise ValueError(
                "Live research requires DiscoveryAgent and ExtractionAgent."
            )
        brief = context.active_brief
        region_code = _effective_region_code(brief, self._default_region_code)
        context.user_added_products = (
            await self._persistence_hooks.load_user_added_products(context.session_id)
        )
        extracted_sources: list[DiscoveredSourceExtraction] = []
        initial_results = (
            ()
            if self._agent_workflow_mode == AgentWorkflowMode.LIVE
            and self._extraction_agent is not None
            else _selected_extraction_results(context.search_results)
        )
        for result in initial_results:
            snapshot = await self._extract_source_or_failure(
                result.url,
                source_type=result.source_type,
            )
            snapshot = _link_snapshot_to_search_result(
                snapshot,
                result,
                region_code=region_code,
            )
            user_added_candidate_id = _user_added_candidate_id_from_search_result(
                result
            )
            if user_added_candidate_id is not None:
                snapshot = _link_snapshot_to_user_added_lookup(
                    snapshot,
                    result,
                    user_added_candidate_id=user_added_candidate_id,
                )
            listing_extraction = (
                None
                if self._agent_workflow_mode == AgentWorkflowMode.LIVE
                else _listing_from_extracted_source(
                    self._listing_extractor,
                    result=result,
                    snapshot=snapshot,
                    category=brief.category,
                )
            )
            extracted_sources.append(
                DiscoveredSourceExtraction(
                    search_result=result,
                    snapshot=snapshot,
                    listing_extraction=listing_extraction,
                    user_added_candidate_id=user_added_candidate_id,
                )
            )

        extracted_sources.extend(
            await self._extract_user_added_url_products(
                context.user_added_products,
                brief=brief,
                region_code=region_code,
            )
        )

        context.source_extractions = tuple(extracted_sources)
        await self._persistence_hooks.persist_source_extractions(
            context,
            context.source_extractions,
        )
        activity: list[dict[str, Any]] = []
        if (
            self._agent_workflow_mode == AgentWorkflowMode.LIVE
            and self._extraction_agent is not None
        ):
            activity.extend(
                await self._run_agent_research_loop(
                    context, extracted_sources, region_code=region_code
                )
            )
            await self._persistence_hooks.persist_extraction_evidence(
                context, context.extraction_evidence
            )
        listing_count = sum(
            item.listing_extraction is not None for item in context.source_extractions
        )
        failed_count = sum(
            item.snapshot.extraction_status == ExtractionStatus.FAILED
            for item in context.source_extractions
        )
        excluded_count = sum(
            item.snapshot.extraction_status == ExtractionStatus.EXCLUDED
            for item in context.source_extractions
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
                + (
                    f" {_counted(failed_count + excluded_count, 'source')} "
                    "could not be read."
                    if failed_count or excluded_count
                    else ""
                )
            ),
            payload={
                "provider": str(provider_name),
                "snapshot_count": str(len(context.source_extractions)),
                "listing_count": str(listing_count),
                "failed_count": str(failed_count),
                "excluded_count": str(excluded_count),
                "evidence_gap_count": str(len(context.extraction_gaps)),
            },
            runtime_mode=self._agent_workflow_mode.value,
            agent_name=(
                "ExtractionAgent"
                if self._agent_workflow_mode == AgentWorkflowMode.LIVE
                and self._extraction_agent is not None
                else "ProductListingExtractor"
            ),
            model_name=self._model_name_for_agent("ExtractionAgent")
            if activity
            else None,
            tool_activity=tuple(activity),
            fallback_outcome=_fallback_outcome(tuple(activity)),
        )

    async def _run_agent_research_loop(
        self,
        context: ShoppingRunContext,
        direct_sources: list[DiscoveredSourceExtraction],
        *,
        region_code: RegionCode,
    ) -> list[dict[str, Any]]:
        """Bounded application-level cycles; agents own source and page meaning."""
        assert self._discovery_agent is not None
        assert self._extraction_agent is not None
        assert context.search_plan is not None
        assert context.search_plan_id is not None
        activity: list[dict[str, Any]] = []
        interpreted: list[DiscoveredSourceExtraction] = []
        evidence: list[SourceEvidence] = []
        mentions: list[ExtractedProductMention] = []
        gaps: list[ExtractionEvidenceGap] = []
        leads: list[ExtractionResearchLead] = []
        matched_evidence_ids: set[SourceId] = set()
        offered_lead_ids: set[SourceId] = set()
        known_urls = {
            _research_url_key(str(item.search_result.url)) for item in direct_sources
        }
        pending = list(
            _agent_selected_results(context.search_results, context.selected_source_ids)
        )
        inspected_source_ids: list[SourceId] = []
        pages_inspected = 0
        follow_up_calls = 0

        for cycle in range(1, _MAX_RESEARCH_CYCLES + 1):
            batch: list[DiscoveredSourceExtraction] = []
            if cycle == 1:
                batch.extend(direct_sources)
            while (
                pending
                and len(batch) < _RESEARCH_PAGES_PER_CYCLE
                and pages_inspected < _MAX_EXTRACTION_SOURCES
            ):
                result = pending.pop(0)
                url_key = _research_url_key(str(result.url))
                if url_key in known_urls:
                    continue
                known_urls.add(url_key)
                snapshot = (
                    await self._persistence_hooks.load_snapshot_for_search_result(
                        context, result.source_id
                    )
                )
                already_persisted = snapshot is not None
                if snapshot is None:
                    snapshot = await self._extract_source_or_failure(
                        result.url, source_type=result.source_type
                    )
                    snapshot = _link_snapshot_to_search_result(
                        snapshot, result, region_code=region_code
                    )
                user_added_candidate_id = _user_added_candidate_id_from_search_result(
                    result
                )
                if user_added_candidate_id is not None:
                    snapshot = _link_snapshot_to_user_added_lookup(
                        snapshot,
                        result,
                        user_added_candidate_id=user_added_candidate_id,
                    )
                item = DiscoveredSourceExtraction(
                    search_result=result,
                    snapshot=snapshot,
                    user_added_candidate_id=user_added_candidate_id,
                )
                if not already_persisted or user_added_candidate_id is not None:
                    await self._persistence_hooks.persist_source_extractions(
                        context, (item,)
                    )
                batch.append(item)
                pages_inspected += 1

            for item in batch:
                inspected_source_ids.append(item.search_result.source_id)
                if item.snapshot.extraction_status not in {
                    ExtractionStatus.SUCCEEDED,
                    ExtractionStatus.PARTIAL,
                }:
                    interpreted.append(item)
                    gap = ExtractionEvidenceGap(
                        source_id=item.snapshot.source_id,
                        summary="Selected page could not be retrieved or read.",
                    )
                    gaps.append(gap)
                    journal = {
                        "tool_name": "research_source_gap",
                        "status": item.snapshot.extraction_status.value,
                        "input": {
                            "cycle": cycle,
                            "search_result_id": str(item.search_result.source_id),
                        },
                        "output": {"gap": gap.model_dump(mode="json")},
                    }
                    activity.append(journal)
                    context.research_activity.append(journal)
                    continue
                available_leads = tuple(
                    lead
                    for lead in leads
                    if not set(lead.mention.evidence_ids) & matched_evidence_ids
                )[:12]
                output = await self._interpret_source(
                    context, item, research_leads=available_leads
                )
                activity.extend(_agent_tool_activity(self._extraction_agent))
                interpreted.extend(_source_extractions_from_agent(item, output))
                evidence.extend(_pending_product_evidence(output))
                mentions.extend(output.product_mentions)
                gaps.extend(output.evidence_gaps)
                for mention in output.product_mentions:
                    cited = tuple(
                        record
                        for record in output.source_evidence
                        if record.evidence_id in mention.evidence_ids
                    )
                    if cited:
                        leads.append(
                            ExtractionResearchLead(
                                mention=mention, source_evidence=cited
                            )
                        )
                matches = {
                    evidence_id: match.product_id
                    for match in output.lead_matches
                    for evidence_id in match.lead_evidence_ids
                }
                matched_evidence_ids.update(matches)
                evidence = [
                    record.model_copy(
                        update={
                            "target": EvidenceTarget(
                                target_type=EvidenceTargetType.PRODUCT,
                                product_id=matches[record.evidence_id],
                            )
                        }
                    )
                    if record.evidence_id in matches
                    else record
                    for record in evidence
                ]
                journal = _extraction_journal(item, output, cycle=cycle)
                activity.append(journal)
                context.research_activity.append(journal)

            context.source_extractions = tuple(interpreted)
            context.extraction_evidence = tuple(evidence)
            context.extraction_mentions = tuple(mentions)
            context.extraction_gaps = tuple(gaps)
            if evidence:
                await self._persistence_hooks.persist_extraction_evidence(
                    context, context.extraction_evidence
                )
            review = _research_review_journal(
                cycle=cycle,
                listings=sum(
                    item.listing_extraction is not None for item in interpreted
                ),
                evidence=len(evidence),
                gaps=len(gaps),
                remaining_pages=_MAX_EXTRACTION_SOURCES - pages_inspected,
            )
            activity.append(review)
            context.research_activity.append(review)
            if _research_sufficient(interpreted, evidence):
                break
            if (
                pages_inspected >= _MAX_EXTRACTION_SOURCES
                or cycle == _MAX_RESEARCH_CYCLES
            ):
                break
            unresolved = _unique_research_leads(
                leads,
                matched_evidence_ids=matched_evidence_ids,
                offered_lead_ids=offered_lead_ids,
            )
            if pending and not unresolved:
                continue
            if follow_up_calls >= _MAX_FOLLOW_UP_DISCOVERY_CALLS:
                if pending:
                    continue
                break
            for lead in unresolved:
                offered_lead_ids.update(lead.mention.evidence_ids)
            follow_up_calls += 1
            follow_up = await self._discovery_agent.run(
                DiscoveryAgentInput(
                    run_id=context.run_id,
                    brief=context.active_brief,
                    search_plan=context.search_plan,
                    product_leads=tuple(lead.mention for lead in unresolved),
                    research_state=DiscoveryResearchState(
                        cycle=cycle,
                        remaining_page_budget=_MAX_EXTRACTION_SOURCES - pages_inspected,
                        product_names=tuple(
                            item.listing_extraction.product.name
                            for item in interpreted
                            if item.listing_extraction is not None
                        )[:12],
                        candidates=tuple(
                            DiscoveryCandidateSummary(
                                product_id=item.listing_extraction.product.product_id,
                                name=item.listing_extraction.product.name,
                                listing_url=item.listing_extraction.listing.url,
                                seller_name=item.listing_extraction.listing.seller.seller_name,
                                source_ids=item.listing_extraction.listing.source_ids,
                            )
                            for item in interpreted
                            if item.listing_extraction is not None
                        )[:12],
                        evidence=tuple(
                            DiscoveryEvidenceSummary(
                                evidence_id=record.evidence_id,
                                source_id=record.source_id,
                                claim=record.claim[:1000],
                                target_type=record.target.target_type,
                            )
                            for record in evidence[-24:]
                        ),
                        listing_count=sum(
                            item.listing_extraction is not None for item in interpreted
                        ),
                        evidence_count=len(evidence),
                        evidence_gaps=tuple(gap.summary for gap in gaps[-12:]),
                        previously_inspected_source_ids=tuple(inspected_source_ids),
                    ),
                )
            )
            activity.extend(_agent_tool_activity(self._discovery_agent))
            journal = _discovery_journal(
                follow_up, cycle=cycle, offered_leads=unresolved
            )
            activity.append(journal)
            context.research_activity.append(journal)
            await self._persistence_hooks.persist_search_results(
                context, follow_up.search_results, plan_id=context.search_plan_id
            )
            context.search_results = _append_unique_search_results(
                context.search_results, follow_up.search_results
            )
            context.editorial_result_ids = (
                *context.editorial_result_ids,
                *(
                    decision.source_id
                    for decision in follow_up.source_decisions
                    if decision.classification
                    == DiscoverySourceKind.PROFESSIONAL_REVIEW
                ),
            )
            context.collection_result_ids = (
                *context.collection_result_ids,
                *(
                    decision.source_id
                    for decision in follow_up.source_decisions
                    if decision.classification
                    == DiscoverySourceKind.CATEGORY_COLLECTION
                ),
            )
            follow_up_pending = [
                result
                for result in _agent_selected_results(
                    follow_up.search_results, follow_up.selected_source_ids
                )
                if _research_url_key(str(result.url)) not in known_urls
            ]
            pending = [*follow_up_pending, *pending]
            if not pending:
                break

        for lead in leads:
            if not set(lead.mention.evidence_ids) & matched_evidence_ids:
                gap = ExtractionEvidenceGap(
                    source_id=lead.mention.source_id,
                    summary=f"No verified direct offer was found for {lead.mention.name} within the research budget.",
                )
                gaps.append(gap)
                journal = {
                    "tool_name": "research_unresolved_lead",
                    "status": "evidence_gap",
                    "input": {
                        "lead_evidence_ids": [
                            str(item) for item in lead.mention.evidence_ids
                        ]
                    },
                    "output": {"gap": gap.model_dump(mode="json")},
                }
                activity.append(journal)
                context.research_activity.append(journal)
        context.source_extractions = tuple(interpreted)
        context.extraction_evidence = tuple(evidence)
        context.extraction_mentions = tuple(mentions)
        context.extraction_gaps = tuple(gaps)
        return activity

    async def _interpret_source(
        self,
        context: ShoppingRunContext,
        item: DiscoveredSourceExtraction,
        *,
        research_leads: tuple[ExtractionResearchLead, ...],
    ) -> ExtractionAgentOutput:
        assert self._extraction_agent is not None
        editorial = item.search_result.source_id in context.editorial_result_ids
        collection = item.search_result.source_id in context.collection_result_ids
        return await self._extraction_agent.run(
            ExtractionAgentInput(
                run_id=context.run_id,
                snapshot_ids=(item.snapshot.source_id,),
                category=context.active_brief.category,
                editorial_snapshot_ids=(item.snapshot.source_id,) if editorial else (),
                collection_snapshot_ids=(item.snapshot.source_id,)
                if collection
                else (),
                research_leads=research_leads,
            )
        )

    async def _extract_user_added_url_products(
        self,
        user_added_products: tuple[UserAddedProduct, ...],
        *,
        brief: ShoppingBrief,
        region_code: RegionCode,
    ) -> tuple[DiscoveredSourceExtraction, ...]:
        extracted_sources: list[DiscoveredSourceExtraction] = []
        for user_added in user_added_products:
            if user_added.url is None:
                continue

            snapshot = await self._extract_source_or_failure(
                user_added.url,
                source_type=SourceType.RETAILER_LISTING,
            )
            snapshot = _link_snapshot_to_user_added_product(
                snapshot,
                user_added,
                region_code=region_code,
            )
            result = _user_added_search_result(
                user_added,
                snapshot=snapshot,
                region_code=region_code,
            )
            listing_extraction = (
                None
                if self._agent_workflow_mode == AgentWorkflowMode.LIVE
                else _listing_from_extracted_source(
                    self._listing_extractor,
                    result=result,
                    snapshot=snapshot,
                    category=brief.category,
                )
            )
            extracted_sources.append(
                DiscoveredSourceExtraction(
                    search_result=result,
                    snapshot=snapshot,
                    listing_extraction=listing_extraction,
                    user_added_candidate_id=user_added.candidate_id,
                )
            )

        return tuple(extracted_sources)

    async def _extract_source_or_failure(
        self,
        url: AnyHttpUrl,
        *,
        source_type: SourceType,
    ) -> SourceSnapshot:
        try:
            return await self._extraction_provider.extract(
                url,
                ExtractionProviderOptions(source_type=source_type),
            )
        except Exception as exc:
            return SourceSnapshot(
                url=url,
                source_type=source_type,
                provider=ProviderMetadata(
                    provider_name=getattr(
                        self._extraction_provider,
                        "provider_name",
                        self._extraction_provider.__class__.__name__,
                    ),
                    raw={
                        "requested_url": str(url),
                        "extraction_failure_code": "provider_exception",
                        "extraction_failure_message": (
                            str(exc) or exc.__class__.__name__
                        )[:500],
                        "extraction_failure_retryable": False,
                    },
                ),
                extraction_status=ExtractionStatus.FAILED,
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
        canonical_product_by_listing = {
            listing.listing_id: group.product.product_id
            for group in result.groups
            for listing in group.listings
        }
        canonical_product_by_original = {
            item.listing_extraction.product.product_id: canonical_product_by_listing[
                item.listing_extraction.listing.listing_id
            ]
            for item in context.source_extractions
            if item.listing_extraction is not None
        }
        if canonical_product_by_original:
            context.extraction_evidence = tuple(
                record.model_copy(
                    update={
                        "target": record.target.model_copy(
                            update={
                                "product_id": canonical_product_by_original[
                                    record.target.product_id
                                ]
                            }
                        )
                    }
                )
                if record.target.target_type == EvidenceTargetType.PRODUCT
                and record.target.product_id in canonical_product_by_original
                else record
                for record in context.extraction_evidence
            )
            await self._persistence_hooks.persist_extraction_evidence(
                context, context.extraction_evidence
            )
        output = CandidateDeduplicationRunOutput(
            result=result,
            pre_dedupe_count=len(candidate_extractions),
            post_dedupe_count=len(result.groups),
        )
        context.source_extractions = _deduplicated_source_extractions(
            context.source_extractions,
            result,
        )
        context.user_added_products = _deduplicated_user_added_products(
            context.user_added_products,
            context.source_extractions,
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
            runtime_mode=self._agent_workflow_mode.value,
        )

    async def _run_source_intelligence(
        self,
        context: ShoppingRunContext,
    ) -> FixtureStageOutput:
        brief = context.active_brief
        region_code = _effective_region_code(brief, self._default_region_code)
        candidates = _source_intelligence_candidates(
            context.source_extractions,
            limit=_MAX_SOURCE_INTELLIGENCE_PRODUCTS,
        )
        if (
            self._agent_workflow_mode == AgentWorkflowMode.LIVE
            and not candidates.products
        ):
            return self._live_insufficient_stage_output(
                context, RunStage.SOURCE_INTELLIGENCE
            )
        if (
            not candidates.products
            and self._agent_workflow_mode == AgentWorkflowMode.FIXTURE
            and context.fixture_output is not None
        ):
            fixture_products = context.fixture_output.products[
                :_MAX_SOURCE_INTELLIGENCE_PRODUCTS
            ]
            fixture_product_ids = {product.product_id for product in fixture_products}
            candidates = SourceIntelligenceCandidates(
                products=fixture_products,
                listings=tuple(
                    listing
                    for listing in context.fixture_output.listings
                    if listing.product_id in fixture_product_ids
                ),
                source_ids=tuple(
                    snapshot.source_id
                    for snapshot in context.fixture_output.source_snapshots
                ),
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

        if self._agent_workflow_mode == AgentWorkflowMode.LIVE:
            return await self._run_live_source_intelligence(
                context,
                brief,
                region_code,
                candidates,
                request,
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
            runtime_mode=self._agent_workflow_mode.value,
        )

    async def _run_live_source_intelligence(
        self,
        context: ShoppingRunContext,
        brief: ShoppingBrief,
        region_code: RegionCode,
        candidates: SourceIntelligenceCandidates,
        request: ReusableSourceIntelligenceRequest,
    ) -> FixtureStageOutput:
        video_bundles: list[VideoReviewEvidenceBundle] = []
        community_bundles: list[CommunityDiscussionEvidenceBundle] = []
        amazon_bundles: list[AmazonProductEvidenceBundle] = []
        ikea_bundles: list[IKEAStoreEvidenceBundle] = []
        activity: list[dict[str, Any]] = []

        source_snapshots = tuple(item.snapshot for item in context.source_extractions)
        query_hints = request.query_hints

        if self._youtube_review_intelligence_agent is not None and _capability_allowed(
            request, SourceIntelligenceCapability.VIDEO_REVIEW
        ):
            video_bundles.append(
                await self._youtube_review_intelligence_agent.run(
                    YouTubeReviewIntelligenceAgentInput(
                        run_id=context.run_id,
                        brief=brief,
                        products=candidates.products,
                        listings=candidates.listings,
                        source_snapshots=source_snapshots,
                        video_queries=query_hints,
                    )
                )
            )
            activity.extend(
                _agent_tool_activity(self._youtube_review_intelligence_agent)
            )

        if (
            self._reddit_community_intelligence_agent is not None
            and _capability_allowed(
                request,
                SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
            )
        ):
            community_bundles.append(
                await self._reddit_community_intelligence_agent.run(
                    RedditCommunityIntelligenceAgentInput(
                        run_id=context.run_id,
                        brief=brief,
                        products=candidates.products,
                        listings=candidates.listings,
                        source_snapshots=source_snapshots,
                        community_queries=query_hints,
                    )
                )
            )
            activity.extend(
                _agent_tool_activity(self._reddit_community_intelligence_agent)
            )

        if self._amazon_product_intelligence_agent is not None and _capability_allowed(
            request,
            SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
        ):
            amazon_bundles.append(
                await self._amazon_product_intelligence_agent.run(
                    AmazonProductIntelligenceAgentInput(
                        run_id=context.run_id,
                        brief=brief,
                        products=candidates.products,
                        listings=candidates.listings,
                        source_snapshots=source_snapshots,
                        product_queries=query_hints,
                        target_region_code=region_code,
                    )
                )
            )
            activity.extend(
                _agent_tool_activity(self._amazon_product_intelligence_agent)
            )

        if (
            self._ikea_store_intelligence_agent is not None
            and _capability_allowed(
                request,
                SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
            )
            and _ikea_source_relevant(
                brief, candidates.products, context.search_results
            )
        ):
            ikea_bundles.append(
                await self._ikea_store_intelligence_agent.run(
                    IKEAStoreIntelligenceAgentInput(
                        run_id=context.run_id,
                        brief=brief,
                        products=candidates.products,
                        listings=candidates.listings,
                        source_snapshots=source_snapshots,
                        product_queries=query_hints,
                        target_region_code=region_code,
                    )
                )
            )
            activity.extend(_agent_tool_activity(self._ikea_store_intelligence_agent))

        output = SourceIntelligenceRunOutput(
            request=request,
            video_bundles=tuple(video_bundles),
            community_bundles=tuple(community_bundles),
            amazon_bundles=tuple(amazon_bundles),
            ikea_bundles=tuple(ikea_bundles),
        )
        context.source_intelligence = output
        await self._persistence_hooks.persist_source_intelligence(context, output)
        activity_tuple = tuple(activity)
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
            agent_name="ReusableSourceIntelligenceAgents",
            runtime_mode=self._agent_workflow_mode.value,
            tool_activity=activity_tuple,
            fallback_outcome=_fallback_outcome(activity_tuple),
        )

    async def _run_listing_trust(
        self,
        context: ShoppingRunContext,
    ) -> FixtureStageOutput:
        listings = _listing_trust_targets(context)
        contexts = price_plausibility_contexts(_listing_groups_by_product(listings))
        evidence_by_listing_id = _evidence_by_listing_id(_analysis_evidence(context))
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
        activity = _agent_tool_activity(self._seller_listing_trust_agent)
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
            agent_name="SellerListingTrustAgent",
            runtime_mode=self._agent_workflow_mode.value,
            model_name=self._model_name_for_stage(RunStage.LISTING_TRUST),
            tool_activity=activity,
            fallback_outcome=_fallback_outcome(activity),
        )

    async def _run_category_analysis(
        self,
        context: ShoppingRunContext,
    ) -> FixtureStageOutput:
        if self._agent_workflow_mode != AgentWorkflowMode.LIVE:
            return self._fixture_stage_output(context, RunStage.CATEGORY_ANALYSIS)

        products = _analysis_products(context)
        listings = _analysis_listings(context)
        evidence = _analysis_evidence(context)
        if not products:
            return self._live_insufficient_stage_output(
                context, RunStage.CATEGORY_ANALYSIS
            )

        route = await self._category_route(context, products, listings, evidence)
        route_activity = _agent_tool_activity(self._category_router_agent)
        analyses: list[CategoryAnalysis] = []
        activity: list[dict[str, Any]] = [*route_activity]
        for product in products:
            agent_name = route.agent_path[-1]
            analyst = self._analysis_agent_for(agent_name)
            if analyst is None:
                analyst = self._generic_product_analyst_agent
                agent_name = "GenericProductAnalystAgent"
            if analyst is None:
                raise ValueError("No approved live product analyst is configured.")

            product_listings = tuple(
                listing
                for listing in listings
                if listing.product_id == product.product_id
            )
            product_evidence = _evidence_for_product(
                product, product_listings, evidence
            )
            analyses.append(
                await analyst.run(
                    ProductAnalysisAgentInput(
                        run_id=context.run_id,
                        brief=context.active_brief,
                        product=product,
                        listings=product_listings,
                        evidence=product_evidence,
                    )
                )
            )
            activity.extend(_agent_tool_activity(analyst))

        context.category_analyses = tuple(analyses)
        activity_tuple = tuple(activity)
        return FixtureStageOutput(
            stage=RunStage.CATEGORY_ANALYSIS,
            trace_id=self._stage_trace_id(
                context.trace_id,
                RunStage.CATEGORY_ANALYSIS,
            ),
            summary=f"Analyzed {_counted(len(analyses), 'product candidate')}.",
            payload={
                "analysis_count": str(len(analyses)),
                "route": " -> ".join(route.agent_path),
                "router_model": self._model_name_for_agent("CategoryRouterAgent") or "",
                "analyst_model": self._model_name_for_agent(route.agent_path[-1]) or "",
            },
            agent_name="CategoryRouterAgent+ProductAnalysisAgents",
            runtime_mode=self._agent_workflow_mode.value,
            model_name=self._model_name_for_agent(route.agent_path[-1]),
            tool_activity=activity_tuple,
            fallback_outcome=_fallback_outcome(activity_tuple),
        )

    async def _run_comparison_decision(
        self,
        context: ShoppingRunContext,
    ) -> FixtureStageOutput:
        if (
            self._agent_workflow_mode != AgentWorkflowMode.LIVE
            or self._comparison_decision_agent is None
        ):
            return self._fixture_stage_output(context, RunStage.COMPARISON_DECISION)

        products = _analysis_products(context)
        listings = _analysis_listings(context)
        evidence = _analysis_evidence(context)
        if not products:
            return self._live_insufficient_stage_output(
                context, RunStage.COMPARISON_DECISION
            )

        bundle = await self._comparison_decision_agent.run(
            ComparisonDecisionAgentInput(
                run_id=context.run_id,
                brief=context.active_brief,
                products=products,
                listings=listings,
                category_analyses=context.category_analyses,
                trust_assessments=context.trust_assessments,
                deduplication_decisions=_deduplication_decisions(context),
                evidence=evidence,
                user_added_products=_user_added_products(context),
            )
        )
        context.recommendation_bundle = bundle
        activity = _agent_tool_activity(self._comparison_decision_agent)
        return FixtureStageOutput(
            stage=RunStage.COMPARISON_DECISION,
            trace_id=self._stage_trace_id(
                context.trace_id,
                RunStage.COMPARISON_DECISION,
            ),
            summary="Compared candidates and prepared the recommendation.",
            payload={
                "product_count": str(len(products)),
                "no_strong_buy": str(bundle.no_strong_buy),
            },
            agent_name="ComparisonDecisionAgent",
            runtime_mode=self._agent_workflow_mode.value,
            model_name=self._model_name_for_stage(RunStage.COMPARISON_DECISION),
            tool_activity=activity,
            fallback_outcome=_fallback_outcome(activity),
        )

    async def _run_verification(
        self,
        context: ShoppingRunContext,
    ) -> FixtureStageOutput:
        if (
            self._agent_workflow_mode != AgentWorkflowMode.LIVE
            or self._verifier_critic_agent is None
        ):
            return self._fixture_stage_output(context, RunStage.VERIFICATION)

        bundle = context.recommendation_bundle
        if bundle is None:
            return self._live_insufficient_stage_output(context, RunStage.VERIFICATION)

        report = await self._verifier_critic_agent.run(
            VerificationAgentInput(
                run_id=context.run_id,
                brief=context.active_brief,
                recommendation_bundle=bundle,
                products=_analysis_products(context),
                listings=_analysis_listings(context),
                evidence=_analysis_evidence(context),
                trust_assessments=context.trust_assessments,
                category_analyses=context.category_analyses,
                deduplication_decisions=_deduplication_decisions(context),
            )
        )
        context.verification_report = report
        context.recommendation_bundle = report.recommendation_bundle
        activity = _agent_tool_activity(self._verifier_critic_agent)
        return FixtureStageOutput(
            stage=RunStage.VERIFICATION,
            trace_id=self._stage_trace_id(context.trace_id, RunStage.VERIFICATION),
            summary="Checked the recommendation for source support and safety.",
            payload={
                "approved": str(report.approved),
                "blocking_issue_count": str(len(report.blocking_issues)),
            },
            agent_name="VerifierCriticAgent",
            runtime_mode=self._agent_workflow_mode.value,
            model_name=self._model_name_for_stage(RunStage.VERIFICATION),
            tool_activity=activity,
            fallback_outcome=_fallback_outcome(activity),
        )

    def _fixture_stage_output(
        self,
        context: ShoppingRunContext,
        stage: RunStage,
        *,
        fallback_outcome: str | None = None,
    ) -> FixtureStageOutput:
        return FixtureStageOutput(
            stage=stage,
            trace_id=self._stage_trace_id(context.trace_id, stage),
            summary=f"Fixture output for {stage.value}.",
            payload={
                "mode": "fixture",
                "stage": stage.value,
            },
            runtime_mode=AgentWorkflowMode.FIXTURE.value,
            fallback_outcome=fallback_outcome,
        )

    def _live_insufficient_stage_output(
        self, context: ShoppingRunContext, stage: RunStage
    ) -> FixtureStageOutput:
        return FixtureStageOutput(
            stage=stage,
            trace_id=self._stage_trace_id(context.trace_id, stage),
            summary="Not enough verified product offers to continue comparison.",
            payload={"reason": "insufficient_agent_validated_candidates"},
            runtime_mode=AgentWorkflowMode.LIVE.value,
            fallback_outcome="insufficient_research_evidence",
        )

    def _current_or_initial_stage(self, context: ShoppingRunContext) -> RunStage:
        if context.active_stage is not None:
            return context.active_stage
        if context.events:
            return context.events[-1].stage
        return RunStage.INTAKE

    async def _category_route(
        self,
        context: ShoppingRunContext,
        products: tuple[CanonicalProduct, ...],
        listings: tuple[ProductListing, ...],
        evidence: tuple[SourceEvidence, ...],
    ) -> ProductAnalysisRoute:
        if self._category_router_agent is None:
            return self._agent_catalog.route_product_analysis(
                context.active_brief.category
            )
        return await self._category_router_agent.run(
            CategoryRouterAgentInput(
                run_id=context.run_id,
                brief=context.active_brief,
                products=products,
                listings=listings,
                evidence=evidence,
            )
        )

    def _analysis_agent_for(
        self,
        agent_name: str,
    ) -> (
        GenericProductAnalystAgent
        | TechnologyDomainAnalystAgent
        | MonitorSpecialistAgent
        | SmartphoneSpecialistAgent
        | LaptopSpecialistAgent
        | EarphonesHeadphonesSpecialistAgent
        | TVSpecialistAgent
        | SmartwatchSpecialistAgent
        | None
    ):
        return {
            "GenericProductAnalystAgent": self._generic_product_analyst_agent,
            "TechnologyDomainAnalystAgent": self._technology_domain_analyst_agent,
            "MonitorSpecialistAgent": self._monitor_specialist_agent,
            "SmartphoneSpecialistAgent": self._smartphone_specialist_agent,
            "LaptopSpecialistAgent": self._laptop_specialist_agent,
            "EarphonesHeadphonesSpecialistAgent": (
                self._earphones_headphones_specialist_agent
            ),
            "TVSpecialistAgent": self._tv_specialist_agent,
            "SmartwatchSpecialistAgent": self._smartwatch_specialist_agent,
        }.get(agent_name)

    def _model_name_for_stage(self, stage: RunStage) -> str | None:
        if self._agent_workflow_mode != AgentWorkflowMode.LIVE:
            return None
        agent_name = {
            RunStage.INTAKE: "IntakeAgent",
            RunStage.QUERY_PLANNING: "QueryPlannerAgent",
            RunStage.DISCOVERY: "DiscoveryAgent",
            RunStage.LISTING_TRUST: "SellerListingTrustAgent",
            RunStage.CATEGORY_ANALYSIS: "CategoryRouterAgent",
            RunStage.COMPARISON_DECISION: "ComparisonDecisionAgent",
            RunStage.VERIFICATION: "VerifierCriticAgent",
        }.get(stage)
        return self._model_name_for_agent(agent_name) if agent_name else None

    def _model_name_for_agent(self, agent_name: str | None) -> str | None:
        if self._agent_workflow_mode != AgentWorkflowMode.LIVE or agent_name is None:
            return None
        if self._agent_model_resolver is not None:
            return self._agent_model_resolver(agent_name)
        return self._agent_model_name

    def _run_trace_id(self, run_id: RunId) -> str:
        prefix = (
            "live-agent-run"
            if self._agent_workflow_mode == AgentWorkflowMode.LIVE
            else "fixture-run"
        )
        return f"{prefix}-{run_id}"

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


def _analysis_products(context: ShoppingRunContext) -> tuple[CanonicalProduct, ...]:
    if context.deduplication is not None:
        return tuple(group.product for group in context.deduplication.result.groups)
    if context.fixture_output is not None:
        return context.fixture_output.products
    return ()


def _analysis_listings(context: ShoppingRunContext) -> tuple[ProductListing, ...]:
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


def _analysis_evidence(context: ShoppingRunContext) -> tuple[SourceEvidence, ...]:
    return (
        *context.extraction_evidence,
        *(context.fixture_output.source_evidence if context.fixture_output else ()),
    )


def _user_added_products(context: ShoppingRunContext):
    if context.user_added_products:
        return context.user_added_products
    if context.fixture_output is None:
        return ()
    return context.fixture_output.user_added_products


def _deduplication_decisions(context: ShoppingRunContext):
    if context.fixture_output is None:
        return ()
    return context.fixture_output.deduplication_decisions


def _evidence_for_product(
    product: CanonicalProduct,
    listings: tuple[ProductListing, ...],
    evidence: tuple[SourceEvidence, ...],
) -> tuple[SourceEvidence, ...]:
    listing_ids = {listing.listing_id for listing in listings}
    source_ids = set(product.source_ids)
    for listing in listings:
        source_ids.update(listing.source_ids)
        source_ids.update(listing.seller.source_ids)
    selected = tuple(
        item
        for item in evidence
        if item.target.product_id == product.product_id
        or (
            item.target.listing_id is not None and item.target.listing_id in listing_ids
        )
        or item.source_id in source_ids
    )
    return selected or evidence


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


def _merge_live_intake_brief(
    current: ShoppingBrief,
    inferred: ShoppingBrief,
) -> ShoppingBrief:
    return current.model_copy(
        update={
            "category": current.category or inferred.category,
            "category_source": current.category_source or inferred.category_source,
            "region": current.region or inferred.region,
            "budget": current.budget or inferred.budget,
            "constraints": current.constraints or inferred.constraints,
            "preferences": current.preferences or inferred.preferences,
        }
    )


def _agent_tool_activity(agent: object | None) -> tuple[dict[str, Any], ...]:
    if agent is None:
        return ()
    activity = getattr(agent, "workbench_activity", ())
    if activity is None:
        return ()
    return tuple(dict(item) for item in activity)


def _fallback_outcome(activity: tuple[dict[str, Any], ...]) -> str | None:
    for item in reversed(activity):
        status = str(item.get("status", ""))
        lowered = status.casefold()
        if any(term in lowered for term in ("fallback", "blocked", "error")):
            return status
    return None


def _duration_ms(started_at: Timestamp, ended_at: Timestamp) -> float:
    return round((ended_at - started_at).total_seconds() * 1000, 3)


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


def _dedupe_search_queries(queries: tuple[SearchQuery, ...]) -> tuple[SearchQuery, ...]:
    deduped: list[SearchQuery] = []
    seen: set[tuple[str, str, tuple[str, ...], str | None]] = set()
    for query in queries:
        key = (
            query.intent.value,
            query.query.casefold(),
            tuple(source_type.value for source_type in query.required_source_types),
            query.region_code,
        )
        if key in seen:
            continue
        deduped.append(query)
        seen.add(key)
    return tuple(deduped)


def _user_added_lookup_queries(
    user_added_products: tuple[UserAddedProduct, ...],
    *,
    region_code: RegionCode,
) -> tuple[SearchQuery, ...]:
    return tuple(
        SearchQuery(
            query=f"{lookup_text} official retailer listing"[:500],
            intent=SearchIntent.DISCOVERY,
            region_code=region_code,
            required_source_types=(
                SourceType.RETAILER_LISTING,
                SourceType.PRODUCT_PAGE,
                SourceType.OFFICIAL_BRAND_PAGE,
            ),
        )
        for lookup_text in (
            _user_added_lookup_text(user_added) for user_added in user_added_products
        )
        if lookup_text is not None
    )


def _user_added_lookup_text(user_added: UserAddedProduct) -> str | None:
    if user_added.url is not None:
        return None
    candidates = (
        user_added.product.name if user_added.product is not None else None,
        user_added.input_text,
    )
    for candidate in candidates:
        if candidate is None:
            continue
        text = " ".join(candidate.split())
        if text:
            return text[:360]
    return None


def _user_added_product_for_lookup_query(
    query: SearchQuery,
    user_added_products: tuple[UserAddedProduct, ...],
) -> UserAddedProduct | None:
    normalized_query = query.query.casefold()
    for user_added in user_added_products:
        lookup_text = _user_added_lookup_text(user_added)
        if lookup_text is None:
            continue
        if lookup_text.casefold() in normalized_query:
            return user_added
    return None


def _mark_user_added_lookup_result(
    result: SearchResult,
    user_added: UserAddedProduct | None,
) -> SearchResult:
    if user_added is None:
        return result
    provider = result.provider.model_copy(
        update={
            "raw": {
                **result.provider.raw,
                "user_added_candidate_id": str(user_added.candidate_id),
                "user_supplied_query": user_added.input_text
                or (
                    user_added.product.name if user_added.product is not None else None
                ),
            }
        }
    )
    return result.model_copy(update={"provider": provider})


def _user_added_candidate_id_from_search_result(
    result: SearchResult,
) -> CandidateId | None:
    candidate_id = result.provider.raw.get("user_added_candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        return None
    return CandidateId(candidate_id)


def _pending_product_evidence(
    output: ExtractionAgentOutput,
) -> tuple[SourceEvidence, ...]:
    """Keep product claims cited without targeting an unpersisted product ID."""
    listed_product_ids = {listing.product_id for listing in output.listings}
    return tuple(
        record.model_copy(
            update={
                "target": EvidenceTarget(
                    target_type=EvidenceTargetType.SOURCE_METADATA,
                    source_id=record.source_id,
                )
            }
        )
        if record.target.target_type == EvidenceTargetType.PRODUCT
        and record.target.product_id not in listed_product_ids
        else record
        for record in output.source_evidence
    )


def _source_extractions_from_agent(
    item: DiscoveredSourceExtraction,
    output: ExtractionAgentOutput,
) -> tuple[DiscoveredSourceExtraction, ...]:
    if not output.listings:
        return (item,)
    products = {product.product_id: product for product in output.products}
    return tuple(
        DiscoveredSourceExtraction(
            search_result=item.search_result,
            snapshot=item.snapshot,
            listing_extraction=ProductListingExtraction(
                product=products[listing.product_id],
                listing=listing,
                confidence=Confidence(
                    score=0.5,
                    level=ConfidenceLevel.MEDIUM,
                    rationale="Agent-extracted, cited page interpretation.",
                ),
            ),
            user_added_candidate_id=item.user_added_candidate_id,
        )
        for listing in output.listings
    )


def _selected_extraction_results(
    results: tuple[SearchResult, ...],
    *,
    selected_source_ids: tuple[SourceId, ...] | None = None,
) -> tuple[SearchResult, ...]:
    if selected_source_ids is not None:
        selected = set(selected_source_ids)
        if not selected:
            return ()
        results = tuple(result for result in results if result.source_id in selected)
    selected_results: list[SearchResult] = []
    seen_urls: set[str] = set()
    for result in results:
        if selected_source_ids is None and result.source_type in {
            SourceType.SEARCH_RESULT,
            SourceType.VIDEO,
        }:
            continue
        normalized_url = str(result.url).casefold().rstrip("/")
        if normalized_url in seen_urls:
            continue
        selected_results.append(result)
        seen_urls.add(normalized_url)
        if len(selected_results) >= _MAX_EXTRACTION_SOURCES:
            break
    return tuple(selected_results)


def _agent_selected_results(
    results: tuple[SearchResult, ...], selected_source_ids: tuple[SourceId, ...]
) -> tuple[SearchResult, ...]:
    """Enforce agent-selected IDs and URL dedupe, never provider source type."""
    by_id = {item.source_id: item for item in results}
    selected: list[SearchResult] = []
    seen_urls: set[str] = set()
    for source_id in selected_source_ids:
        result = by_id.get(source_id)
        if result is None:
            raise ValueError("Discovery selected an unknown source ID")
        key = _research_url_key(str(result.url))
        if key not in seen_urls:
            selected.append(result)
            seen_urls.add(key)
    return tuple(selected)


def _research_url_key(url: str) -> str:
    return url.casefold().rstrip("/")


def _append_unique_search_results(
    current: tuple[SearchResult, ...], added: tuple[SearchResult, ...]
) -> tuple[SearchResult, ...]:
    known = {item.source_id for item in current}
    return (*current, *(item for item in added if item.source_id not in known))


def _unique_research_leads(
    leads: list[ExtractionResearchLead],
    *,
    matched_evidence_ids: set[SourceId],
    offered_lead_ids: set[SourceId],
) -> tuple[ExtractionResearchLead, ...]:
    selected: list[ExtractionResearchLead] = []
    seen_names: set[tuple[str, str, str]] = set()
    for lead in leads:
        if set(lead.mention.evidence_ids) & (matched_evidence_ids | offered_lead_ids):
            continue
        key = (
            (lead.mention.brand or "").casefold(),
            (lead.mention.model or "").casefold(),
            lead.mention.name.casefold(),
        )
        if key not in seen_names:
            selected.append(lead)
            seen_names.add(key)
        if len(selected) == 12:
            break
    return tuple(selected)


def _research_sufficient(
    extracted: list[DiscoveredSourceExtraction], evidence: list[SourceEvidence]
) -> bool:
    """Mechanical adequacy budget, not semantic source/product classification."""
    product_ids = {
        item.listing_extraction.product.product_id
        for item in extracted
        if item.listing_extraction is not None
    }
    return len(product_ids) >= 3 and len(evidence) >= 2


def _discovery_journal(
    output: Any,
    *,
    cycle: int,
    offered_leads: tuple[ExtractionResearchLead, ...] = (),
) -> dict[str, Any]:
    return {
        "tool_name": "research_discovery_decision",
        "status": output.outcome.value,
        "input": {
            "cycle": cycle,
            "product_leads": [
                lead.mention.model_dump(mode="json") for lead in offered_leads
            ],
        },
        "output": {
            "source_decisions": [
                item.model_dump(mode="json") for item in output.source_decisions
            ],
            "selected_source_ids": [str(item) for item in output.selected_source_ids],
            "notes": list(output.notes),
        },
    }


def _extraction_journal(
    item: DiscoveredSourceExtraction, output: ExtractionAgentOutput, *, cycle: int
) -> dict[str, Any]:
    return {
        "tool_name": "research_extraction_decision",
        "status": "interpreted",
        "input": {
            "cycle": cycle,
            "search_result_id": str(item.search_result.source_id),
            "snapshot_id": str(item.snapshot.source_id),
        },
        "output": {
            "products": [
                product.model_dump(mode="json") for product in output.products
            ],
            "listings": [
                listing.model_dump(mode="json") for listing in output.listings
            ],
            "mentions": [
                mention.model_dump(mode="json") for mention in output.product_mentions
            ],
            "evidence_ids": [
                str(record.evidence_id) for record in output.source_evidence
            ],
            "evidence_gaps": [
                gap.model_dump(mode="json") for gap in output.evidence_gaps
            ],
            "lead_matches": [
                match.model_dump(mode="json") for match in output.lead_matches
            ],
        },
    }


def _research_review_journal(
    *, cycle: int, listings: int, evidence: int, gaps: int, remaining_pages: int
) -> dict[str, Any]:
    return {
        "tool_name": "research_cycle_review",
        "status": "sufficient"
        if listings >= 3 and evidence >= 2
        else "continue_or_limit",
        "input": {"cycle": cycle},
        "output": {
            "listing_count": listings,
            "evidence_count": evidence,
            "gap_count": gaps,
            "remaining_page_budget": remaining_pages,
        },
    }


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
            "title": snapshot.title or result.title,
            "provider": provider,
            "quality": result.quality,
        }
    )


def _link_snapshot_to_user_added_product(
    snapshot: SourceSnapshot,
    user_added: UserAddedProduct,
    *,
    region_code: RegionCode,
) -> SourceSnapshot:
    provider = snapshot.provider.model_copy(
        update={
            "raw": {
                **snapshot.provider.raw,
                "target_region_code": region_code,
                "user_added_candidate_id": str(user_added.candidate_id),
                "user_supplied_url": str(user_added.url),
            }
        }
    )
    return snapshot.model_copy(
        update={
            "source_type": SourceType.RETAILER_LISTING,
            "title": snapshot.title or _user_added_title(user_added, snapshot),
            "provider": provider,
        }
    )


def _link_snapshot_to_user_added_lookup(
    snapshot: SourceSnapshot,
    result: SearchResult,
    *,
    user_added_candidate_id: CandidateId,
) -> SourceSnapshot:
    provider = snapshot.provider.model_copy(
        update={
            "raw": {
                **snapshot.provider.raw,
                "user_added_candidate_id": str(user_added_candidate_id),
                "user_supplied_query": result.provider.raw.get("user_supplied_query"),
                "user_added_match_source_id": str(result.source_id),
            }
        }
    )
    return snapshot.model_copy(update={"provider": provider})


def _user_added_search_result(
    user_added: UserAddedProduct,
    *,
    snapshot: SourceSnapshot,
    region_code: RegionCode,
) -> SearchResult:
    return SearchResult(
        source_id=user_added.candidate_id,
        query=SearchQuery(
            query=_user_added_title(user_added, snapshot),
            intent=SearchIntent.DISCOVERY,
            region_code=region_code,
            required_source_types=(SourceType.RETAILER_LISTING,),
        ),
        url=snapshot.url,
        title=_user_added_title(user_added, snapshot),
        snippet=user_added.notes or user_added.input_text,
        source_type=SourceType.RETAILER_LISTING,
        provider=ProviderMetadata(
            provider_name="user-added-url",
            provider_result_id=str(user_added.candidate_id),
            raw={"user_added_candidate_id": str(user_added.candidate_id)},
        ),
        quality=snapshot.quality,
    )


def _user_added_title(
    user_added: UserAddedProduct,
    snapshot: SourceSnapshot,
) -> str:
    candidates = (
        user_added.product.name if user_added.product is not None else None,
        snapshot.title,
        user_added.input_text,
        str(user_added.url) if user_added.url is not None else None,
        "User-added product URL",
    )
    for candidate in candidates:
        if candidate is None:
            continue
        title = " ".join(candidate.split())
        if title:
            return title[:300]
    return "User-added product URL"


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

    if snapshot.source_type not in {
        SourceType.PRODUCT_PAGE,
        SourceType.RETAILER_LISTING,
        SourceType.OFFICIAL_BRAND_PAGE,
    }:
        return None

    if snapshot.extracted_content is not None:
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
                user_added_candidate_id=item.user_added_candidate_id,
            )
        )
    return tuple(grouped_extractions)


def _deduplicated_user_added_products(
    user_added_products: tuple[UserAddedProduct, ...],
    extractions: tuple[DiscoveredSourceExtraction, ...],
) -> tuple[UserAddedProduct, ...]:
    extraction_by_candidate_id = {
        item.user_added_candidate_id: item.listing_extraction
        for item in extractions
        if item.user_added_candidate_id is not None
        and item.listing_extraction is not None
    }
    updated: list[UserAddedProduct] = []
    for user_added in user_added_products:
        extraction = extraction_by_candidate_id.get(user_added.candidate_id)
        if extraction is None:
            updated.append(user_added)
            continue
        updated.append(
            user_added.model_copy(
                update={
                    "product": extraction.product,
                    "listing": extraction.listing,
                }
            )
        )
    return tuple(updated)


def _is_direct_user_added_url_extraction(item: DiscoveredSourceExtraction) -> bool:
    return item.search_result.provider.provider_name == "user-added-url"


def _user_added_candidate_ids_by_listing_id(
    user_added_products: tuple[UserAddedProduct, ...],
) -> dict[ListingId, CandidateId]:
    return {
        user_added.listing.listing_id: user_added.candidate_id
        for user_added in user_added_products
        if user_added.listing is not None
    }


def _candidate_id_for_group(
    listings: tuple[ProductListing, ...],
    user_added_candidate_by_listing_id: Mapping[ListingId, CandidateId],
) -> CandidateId | None:
    for listing in listings:
        candidate_id = user_added_candidate_by_listing_id.get(listing.listing_id)
        if candidate_id is not None:
            return candidate_id
    return None


def _source_intelligence_candidates(
    extractions: tuple[DiscoveredSourceExtraction, ...],
    *,
    limit: int,
) -> SourceIntelligenceCandidates:
    products_by_id: dict[ProductId, CanonicalProduct] = {}
    listings_by_id: dict[ListingId, ProductListing] = {}
    source_ids: list[SourceId] = []

    for item in extractions:
        if item.user_added_candidate_id is None:
            source_ids.append(item.search_result.source_id)
        source_ids.append(item.snapshot.source_id)
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
        return brief.region.region.country_code
    return default_region_code


def _counted(count: int, noun: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"
