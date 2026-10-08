from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
import re
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AnyHttpUrl

from app.agents.context_management import (
    active_budget, context_events, managed_context, set_context_stage,
)

from app.agents import (
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
    GeneralShoppingAgent,
    GeneralShoppingAgentInput,
    GeneralShoppingCandidate,
    GeneralShoppingDecisionDraft,
    GeneralShoppingEvidence,
    GeneralShoppingOutcome,
    IKEAStoreIntelligenceAgentInput,
    IntakeAgent,
    IntakeAgentInput,
    LaptopSpecialistAgent,
    MonitorSpecialistAgent,
    ProductAnalysisAgentInput,
    QueryPlannerAgent,
    QueryPlannerAgentInput,
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
    YouTubeReviewIntelligenceAgentInput,
    EarphonesHeadphonesSpecialistAgent,
)
from app.agents.contracts import (
    AmazonProductIntelligenceServicePort,
    IKEAStoreIntelligenceServicePort,
    RedditCommunityIntelligenceServicePort,
    YouTubeReviewIntelligenceServicePort,
)
from app.agents.catalog import ProductAnalysisRoute, build_default_agent_catalog
from app.agents.live_source_intelligence_manager import (
    SourceIntelligenceManagerAgent,
    SourceManagerInput,
)
from app.agents.live_verifier_critic import verify_recommendation_guardrails
from app.agents.research_tools import _safe_public_result_url
from app.agents.fixture_research import (
    FixtureDiscoveryAgent,
    FixtureExtractionAgent,
    FixtureSearchReplayProvider,
    FixtureSnapshotReplayProvider,
)
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
from app.providers.source_quality import SourceClass, SourceEvidenceContext
from app.schemas.analysis import (
    CategoryAnalysis,
    ComparisonMatrix,
    ComparisonCriterion,
    ComparisonRow,
    ListingTrustAssessment,
    ListingTrustLevel,
    RecommendationBundle,
    RecommendationMode,
    RecommendationModeResult,
)
from app.schemas.errors import ErrorBody, ErrorEnvelope
from app.schemas.ids import (
    CandidateId,
    ListingId,
    ProductId,
    RunId,
    SessionId,
    SourceId,
    new_id,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.intake import BudgetMode, CreateSessionRequest, ShoppingBrief
from app.schemas.products import (
    MANUAL_UNVERIFIED_SUMMARY,
    CanonicalProduct,
    ProductListing,
    ProductListingExtraction,
    UserAddedListingMatch,
    UserAddedMatchConfidence,
    UserAddedProduct,
)
from app.schemas.regions import RegionCode
from app.schemas.runs import (
    AgentRunRecord,
    RecomputePlan,
    RecomputeStage,
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
    DeterministicProductGroup,
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
        return max(0, self.pre_dedupe_count - self.post_dedupe_count)


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
    general_owner_draft: GeneralShoppingDecisionDraft | None = None
    owner_products: tuple[CanonicalProduct, ...] = ()
    owner_listings: tuple[ProductListing, ...] = ()
    owner_evidence: tuple[SourceEvidence, ...] = ()
    active_stage: RunStage | None = None
    refinement_plan: RecomputePlan | None = None
    prior_recommendation: RecommendationBundle | None = None


@dataclass(frozen=True)
class ReusedRefinementArtifacts:
    products: tuple[CanonicalProduct, ...]
    listings: tuple[ProductListing, ...]
    evidence: tuple[SourceEvidence, ...]
    trust_assessments: tuple[ListingTrustAssessment, ...]
    category_analyses: tuple[CategoryAnalysis, ...]
    recommendation: RecommendationBundle
    user_added_products: tuple[UserAddedProduct, ...] = ()


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

    async def load_owner_result_sources(
        self, run_id: RunId
    ) -> tuple[
        tuple[SearchResult, ...], tuple[SourceSnapshot, ...], tuple[SourceEvidence, ...]
    ]:
        """Reload same-run references independently of the owner's draft."""

    async def persist_owner_product(
        self, run_id: RunId, product: CanonicalProduct
    ) -> CanonicalProduct:
        """Persist a quote-backed product without asserting a verified listing."""

    async def load_owner_result_products(
        self, run_id: RunId
    ) -> tuple[tuple[CanonicalProduct, ...], tuple[ProductListing, ...]]:
        """Load same-run products and distinct listings for owner result mapping."""

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

    async def load_owner_result_sources(
        self, run_id: RunId
    ) -> tuple[
        tuple[SearchResult, ...], tuple[SourceSnapshot, ...], tuple[SourceEvidence, ...]
    ]:
        if self._search_source_repository is None:
            raise ValueError("Owner result requires source persistence.")
        return (
            await self._search_source_repository.list_search_results(run_id),
            await self._search_source_repository.list_source_snapshots(run_id),
            await self._search_source_repository.list_source_evidence(run_id),
        )

    async def persist_owner_product(
        self, run_id: RunId, product: CanonicalProduct
    ) -> CanonicalProduct:
        if self._product_repository is None:
            raise ValueError("Owner result requires product persistence.")
        return await self._product_repository.add_canonical_product(run_id, product)

    async def load_owner_result_products(
        self, run_id: RunId
    ) -> tuple[tuple[CanonicalProduct, ...], tuple[ProductListing, ...]]:
        if self._product_repository is None:
            raise ValueError("Owner result requires product persistence.")
        return (
            await self._product_repository.list_canonical_products_for_run(run_id),
            await self._product_repository.list_product_listings_for_run(run_id),
        )

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

        # Research entities were already persisted from the typed fixture-agent
        # replay. This compatibility bundle supplies only downstream analysis.
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
        if context.general_owner_draft is not None:
            recommendation_bundle = context.recommendation_bundle
            if recommendation_bundle.verification_action not in {
                "approved",
                "revised",
                "blocked",
            }:
                recommendation_bundle = _blocked_owner_result(
                    recommendation_bundle, ("Verification was not completed.",)
                )
        else:
            recommendation_bundle = integrate_trust_analysis_into_recommendation(
                context.recommendation_bundle, context.trust_assessments
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
        manual_candidate_by_product_id = {
            item.product.product_id: item.candidate_id
            for item in context.user_added_products
            if item.manual_fallback_reason is not None and item.product is not None
        }
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
                )
                or manual_candidate_by_product_id.get(group.product.product_id),
                position=shortlist_position,
            )
            shortlist_position += 1

        for user_added in context.user_added_products:
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
        for community_bundle in output.community_bundles:
            await self._persist_bundle_source_snapshots(
                context,
                output,
                SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
                community_bundle.source_references,
                source_type=SourceType.COMMUNITY_DISCUSSION,
            )
            await self._source_intelligence_repository.add_community_discussion_bundle(
                context.run_id,
                community_bundle,
            )
        for amazon_bundle in output.amazon_bundles:
            await self._persist_bundle_source_snapshots(
                context,
                output,
                SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
                amazon_bundle.source_references,
                source_type=SourceType.RETAILER_LISTING,
            )
            await self._source_intelligence_repository.add_amazon_product_bundle(
                context.run_id,
                amazon_bundle,
            )
        for ikea_bundle in output.ikea_bundles:
            await self._persist_bundle_source_snapshots(
                context,
                output,
                SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
                ikea_bundle.source_references,
                source_type=SourceType.OFFICIAL_BRAND_PAGE,
            )
            await self._source_intelligence_repository.add_ikea_store_bundle(
                context.run_id,
                ikea_bundle,
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
            RunStage.GENERAL_OWNER,
            "GeneralShoppingAgent",
            "Shopping request reviewed.",
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
        general_shopping_agent: GeneralShoppingAgent | None = None,
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
        youtube_review_intelligence_service: YouTubeReviewIntelligenceServicePort
        | None = None,
        reddit_community_intelligence_service: (
            RedditCommunityIntelligenceServicePort | None
        ) = None,
        amazon_product_intelligence_service: AmazonProductIntelligenceServicePort
        | None = None,
        ikea_store_intelligence_service: IKEAStoreIntelligenceServicePort | None = None,
        source_intelligence_manager: SourceIntelligenceManagerAgent | None = None,
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
        self._general_shopping_agent = general_shopping_agent
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
        self._youtube_review_intelligence_service = youtube_review_intelligence_service
        self._reddit_community_intelligence_service = (
            reddit_community_intelligence_service
        )
        self._amazon_product_intelligence_service = amazon_product_intelligence_service
        self._ikea_store_intelligence_service = ikea_store_intelligence_service
        self._source_intelligence_manager = source_intelligence_manager
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

    @managed_context
    async def run(
        self,
        run_id: RunId,
        brief: ShoppingBrief | None = None,
        original_input: CreateSessionRequest | None = None,
        refinement_plan: RecomputePlan | None = None,
        reused_artifacts: ReusedRefinementArtifacts | None = None,
    ) -> ShoppingRunContext:
        run = await self._persistence_hooks.load_run(run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")

        if brief is not None:
            active_brief = brief
        elif original_input is not None:
            active_brief = ShoppingBrief(original_query=original_input.query)
        elif self._agent_workflow_mode == AgentWorkflowMode.FIXTURE:
            active_brief = ShoppingBrief(original_query="Need a monitor")
        else:
            raise ValueError("Live shopping runs require a shopping brief or request.")
        fixture_output = (
            build_monitor_fixture_run_output(run_id=run_id, session_id=run.session_id)
            if self._agent_workflow_mode == AgentWorkflowMode.FIXTURE
            and _fixture_replay_category(active_brief) == "monitor"
            and isinstance(self._search_provider, FakeSearchProvider)
            and self._search_provider.results is None
            and isinstance(self._extraction_provider, FakeExtractionProvider)
            and self._extraction_provider.snapshot is None
            else None
        )
        if self._agent_workflow_mode == AgentWorkflowMode.FIXTURE:
            self._discovery_agent = self._discovery_agent or FixtureDiscoveryAgent(
                fixture_output
            )
            self._extraction_agent = self._extraction_agent or FixtureExtractionAgent(
                fixture_output
            )
            if fixture_output is not None:
                self._search_provider = FixtureSearchReplayProvider(
                    results=tuple(
                        item.model_copy(
                            update={
                                "provider": item.provider.model_copy(
                                    update={"provider_name": "fixture-search"}
                                )
                            }
                        )
                        for item in fixture_output.search_results
                    )
                )
                self._extraction_provider = FixtureSnapshotReplayProvider(
                    fixture_output
                )
        context = ShoppingRunContext(
            run_id=run_id,
            session_id=run.session_id,
            trace_id=self._run_trace_id(run_id),
            active_brief=active_brief,
            original_input=original_input,
        )
        context.fixture_output = fixture_output
        context.refinement_plan = refinement_plan
        if reused_artifacts is not None:
            context.fixture_output = None
            context.owner_products = reused_artifacts.products
            context.owner_listings = reused_artifacts.listings
            context.owner_evidence = reused_artifacts.evidence
            context.trust_assessments = reused_artifacts.trust_assessments
            context.category_analyses = reused_artifacts.category_analyses
            context.prior_recommendation = reused_artifacts.recommendation
            context.user_added_products = reused_artifacts.user_added_products
        await self._persistence_hooks.checkpoint()

        try:
            if (
                refinement_plan is not None
                and RecomputeStage.SEARCH not in refinement_plan.stages
            ):
                if reused_artifacts is None:
                    raise ValueError(
                        "Refinement reuse requires validated saved artifacts."
                    )
                stages = {
                    RunStage.COMPARISON_DECISION,
                    RunStage.VERIFICATION,
                }
                if RecomputeStage.ANALYSIS in refinement_plan.stages:
                    stages.add(RunStage.CATEGORY_ANALYSIS)
                definitions = tuple(
                    item for item in self._STAGES if item.stage in stages
                )
            elif (
                refinement_plan is not None
                and RecomputeStage.RE_INTAKE not in refinement_plan.stages
            ):
                definitions = tuple(
                    item for item in self._STAGES if item.stage != RunStage.INTAKE
                )
            else:
                definitions = self._STAGES
            for definition in definitions:
                context.active_stage = definition.stage
                await self._run_stage(context, definition)

            if context.fixture_output is not None:
                await self._persistence_hooks.persist_fixture_output(
                    context, context.fixture_output
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
        set_context_stage(definition.stage.value)
        budget = active_budget()
        context_start = len(budget.events) if budget else 0
        try:
            if definition.stage == RunStage.INTAKE:
                stage_output = await self._run_intake(context)
            elif definition.stage == RunStage.GENERAL_OWNER:
                stage_output = await self._run_general_owner(context)
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
                agent_name=(
                    "SourceIntelligenceManagerAgent"
                    if definition.stage == RunStage.SOURCE_INTELLIGENCE
                    and self._source_intelligence_manager is not None
                    and self._agent_workflow_mode == AgentWorkflowMode.LIVE
                    else definition.agent_name
                ),
                status=RunStatus.FAILED,
                trace_id=self._stage_trace_id(context.trace_id, definition.stage),
                started_at=started_at,
                ended_at=ended_at,
                runtime_mode=(
                    "provider_service"
                    if definition.stage == RunStage.SOURCE_INTELLIGENCE
                    and self._agent_workflow_mode == AgentWorkflowMode.LIVE
                    and self._source_intelligence_manager is None
                    else self._agent_workflow_mode.value
                ),
                model_name=(
                    self._model_name_for_agent("SourceIntelligenceManagerAgent")
                    if definition.stage == RunStage.SOURCE_INTELLIGENCE
                    and self._source_intelligence_manager is not None
                    else self._model_name_for_stage(definition.stage)
                ),
                duration_ms=_duration_ms(started_at, ended_at),
                tool_activity=(
                    *(tuple(context.research_activity)
                      if definition.stage in {RunStage.EXTRACTION, RunStage.GENERAL_OWNER}
                      else ()),
                    *context_events(context_start),
                ),
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
            tool_activity=(*stage_output.tool_activity, *context_events(context_start)),
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

    async def _run_general_owner(
        self, context: ShoppingRunContext
    ) -> FixtureStageOutput:
        if self._agent_workflow_mode != AgentWorkflowMode.LIVE:
            return self._fixture_stage_output(context, RunStage.GENERAL_OWNER)
        if self._general_shopping_agent is None:
            raise ValueError("Live shopping runs require GeneralShoppingAgent.")

        context.user_added_products = (
            await self._persistence_hooks.load_user_added_products(context.session_id)
        )
        draft = await self._general_shopping_agent.run(
            GeneralShoppingAgentInput(
                run_id=context.run_id,
                brief=context.active_brief,
                user_added_products=context.user_added_products,
            )
        )
        context.general_owner_draft = draft
        owner_activity = _agent_tool_activity(self._general_shopping_agent)
        if any(
            item.get("tool_name") == "general_owner"
            and item.get("status") == "research_failed"
            for item in owner_activity
        ):
            context.research_activity.extend(owner_activity)
            raise RuntimeError(
                "CartCart could not complete product research. No buying decision "
                "was made. Please retry after checking the research service."
            )
        activity = (
            *owner_activity,
            {
                "tool_name": "general_owner_draft",
                "status": draft.outcome.value,
                "input": {"run_id": str(context.run_id)},
                "output": {
                    "category": draft.category,
                    "specialist_helpful": draft.specialist_helpful,
                    "selected_candidate_name": draft.selected_candidate_name,
                    "mode_selections": [
                        item.mode.value for item in draft.mode_selections
                    ],
                    "evidence_ids": [
                        str(item.evidence_id)
                        for candidate in draft.candidates
                        for item in candidate.evidence
                    ],
                    "hosted_lead_source_ids": [
                        str(source_id) for source_id in draft.hosted_lead_source_ids
                    ],
                    "evidence_gaps": list(draft.evidence_gaps),
                    "owner_agent_name": draft.owner_agent_name,
                    "result_author": draft.owner_agent_name,
                },
            },
        )
        usage: dict[str, Any] = next(
            (
                item.get("output", {}).get("usage", {})
                for item in reversed(activity)
                if item.get("tool_name") == "general_owner"
            ),
            {},
        )
        return FixtureStageOutput(
            stage=RunStage.GENERAL_OWNER,
            trace_id=self._stage_trace_id(context.trace_id, RunStage.GENERAL_OWNER),
            summary="Shopping question reviewed.",
            payload={
                "outcome": draft.outcome.value,
                "result_author": draft.owner_agent_name,
            },
            agent_name=draft.owner_agent_name,
            runtime_mode=AgentWorkflowMode.LIVE.value,
            model_name=next(
                (
                    item.get("output", {}).get("last_agent_model")
                    for item in reversed(activity)
                    if item.get("tool_name") == "general_owner"
                ),
                self._model_name_for_stage(RunStage.GENERAL_OWNER),
            ),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
            tool_activity=activity,
            fallback_outcome=(
                "insufficient_evidence"
                if draft.outcome == GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
                else _fallback_outcome(activity)
            ),
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
        if self._discovery_agent is not None:
            discovery_output = await self._discovery_agent.run(
                DiscoveryAgentInput(
                    run_id=context.run_id,
                    brief=brief,
                    search_plan=context.search_plan,
                    seed_results=context.search_results,
                    user_added_products=context.user_added_products,
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
            if self._discovery_agent is not None
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
        if self._discovery_agent is None or self._extraction_agent is None:
            raise ValueError("Research requires DiscoveryAgent and ExtractionAgent.")
        brief = context.active_brief
        region_code = _effective_region_code(brief, self._default_region_code)
        context.user_added_products = (
            await self._persistence_hooks.load_user_added_products(context.session_id)
        )
        extracted_sources: list[DiscoveredSourceExtraction] = []

        extracted_sources.extend(
            await self._extract_user_added_url_products(
                context.user_added_products,
                region_code=region_code,
            )
        )

        context.source_extractions = tuple(extracted_sources)
        await self._persistence_hooks.persist_source_extractions(
            context,
            context.source_extractions,
        )
        activity: list[dict[str, Any]] = []
        if self._extraction_agent is not None:
            activity.extend(
                await self._run_agent_research_loop(
                    context, extracted_sources, region_code=region_code
                )
            )
            await self._persistence_hooks.persist_extraction_evidence(
                context, context.extraction_evidence
            )
        if context.fixture_output is not None:
            extracted_listing_ids = {
                item.listing_extraction.listing.listing_id
                for item in context.source_extractions
                if item.listing_extraction is not None
            }
            expected_listing_ids = {
                listing.listing_id for listing in context.fixture_output.listings
            }
            if extracted_listing_ids != expected_listing_ids:
                context.fixture_output = None
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
            agent_name="ExtractionAgent",
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
                    journal: dict[str, Any] = {
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
            if _research_sufficient(
                interpreted, evidence
            ) and _user_added_hints_resolved(interpreted, context.user_added_products):
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
                    user_added_products=context.user_added_products,
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
        for user_added in context.user_added_products:
            if user_added.url is not None:
                continue
            candidate_matches = [
                (item.listing_extraction.product.product_id, match.confidence)
                for item in interpreted
                if item.listing_extraction is not None
                for match in item.listing_extraction.listing.user_added_matches
                if match.candidate_id == user_added.candidate_id
            ]
            if (
                not candidate_matches
                or any(
                    confidence == UserAddedMatchConfidence.POSSIBLE
                    for _, confidence in candidate_matches
                )
                or len({product_id for product_id, _ in candidate_matches}) > 1
            ):
                journal = {
                    "tool_name": "user_added_product_resolution",
                    "status": "ambiguous" if candidate_matches else "unresolved",
                    "input": {"candidate_id": str(user_added.candidate_id)},
                    "output": {
                        "possible_product_ids": list(
                            dict.fromkeys(str(product_id) for product_id, _ in candidate_matches)
                        )
                    },
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
        output = await self._extraction_agent.run(
            ExtractionAgentInput(
                run_id=context.run_id,
                snapshot_ids=(item.snapshot.source_id,),
                category=context.active_brief.category,
                user_added_products=context.user_added_products,
                editorial_snapshot_ids=(item.snapshot.source_id,) if editorial else (),
                collection_snapshot_ids=(item.snapshot.source_id,)
                if collection
                else (),
                research_leads=research_leads,
            )
        )
        allowed_candidates = {item.candidate_id for item in context.user_added_products}
        for match in output.user_added_matches:
            if match.candidate_id not in allowed_candidates:
                raise ValueError("Extraction matched an unknown user-added candidate")
            listing = next(
                item for item in output.listings if item.listing_id == match.listing_id
            )
            if (
                match.source_id != item.snapshot.source_id
                or match.source_id not in listing.source_ids
            ):
                raise ValueError("User-added match does not cite the inspected page")
        return output

    async def _extract_user_added_url_products(
        self,
        user_added_products: tuple[UserAddedProduct, ...],
        *,
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
            extracted_sources.append(
                DiscoveredSourceExtraction(
                    search_result=result,
                    snapshot=snapshot,
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
        matched_candidate_ids = {
            match.candidate_id
            for item in context.source_extractions
            if item.listing_extraction is not None
            for match in item.listing_extraction.listing.user_added_matches
            if match.confidence == UserAddedMatchConfidence.CONFIRMED
        }
        manual_products_by_candidate_id = {
            item.candidate_id: item.product.model_copy(
                update={"product_id": new_id(), "source_ids": (), "listing_ids": ()}
            )
            for item in context.user_added_products
            if item.manual_fallback_reason is not None
            and item.product is not None
            and item.candidate_id not in matched_candidate_ids
        }
        manual_groups = tuple(
            DeterministicProductGroup(product=product, listings=())
            for product in manual_products_by_candidate_id.values()
        )
        if manual_groups:
            result = DeterministicDeduplicationResult(
                groups=(*result.groups, *manual_groups),
                fuzzy_decisions=result.fuzzy_decisions,
            )
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
            pre_dedupe_count=len(candidate_extractions) + len(manual_groups),
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
        context.user_added_products = tuple(
            item.model_copy(
                update={
                    "research_attempted": True,
                    "product": manual_products_by_candidate_id.get(
                        item.candidate_id, item.product
                    ),
                }
            )
            for item in context.user_added_products
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
            return self._insufficient_stage_output(
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
            if self._source_intelligence_manager is not None:
                return await self._run_agent_source_intelligence(
                    context, brief, region_code, candidates, request
                )
            return await self._run_provider_source_intelligence(
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

    async def _run_agent_source_intelligence(
        self,
        context: ShoppingRunContext,
        brief: ShoppingBrief,
        region_code: RegionCode,
        candidates: SourceIntelligenceCandidates,
        request: ReusableSourceIntelligenceRequest,
    ) -> FixtureStageOutput:
        assert self._source_intelligence_manager is not None
        allowed = tuple(
            capability
            for capability in request.requested_capabilities
            if _capability_allowed(request, capability)
        )
        result = await self._source_intelligence_manager.run(
            SourceManagerInput(
                run_id=context.run_id,
                brief=brief,
                products=candidates.products,
                listings=candidates.listings,
                source_snapshots=tuple(
                    item.snapshot for item in context.source_extractions
                ),
                query_hints=request.query_hints,
                region_code=region_code,
                allowed_capabilities=allowed,
            )
        )
        output = SourceIntelligenceRunOutput(
            request=request,
            video_bundles=result.video_bundles,
            community_bundles=result.community_bundles,
            amazon_bundles=result.amazon_bundles,
            ikea_bundles=result.ikea_bundles,
            notes=result.notes,
        )
        context.source_intelligence = output
        await self._persistence_hooks.persist_source_intelligence(context, output)
        return FixtureStageOutput(
            stage=RunStage.SOURCE_INTELLIGENCE,
            trace_id=self._stage_trace_id(
                context.trace_id, RunStage.SOURCE_INTELLIGENCE
            ),
            summary=_source_intelligence_summary(output),
            payload={
                "bundle_count": str(output.bundle_count),
                "evidence_count": str(output.evidence_count),
                "gap_count": str(output.gap_count),
            },
            agent_name="SourceIntelligenceManagerAgent",
            runtime_mode="live",
            model_name=result.model_name,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
            tool_activity=result.activity,
            fallback_outcome=next(
                (
                    str(item["status"])
                    for item in result.activity
                    if item.get("status")
                    in {"model_or_validation_failure", "evidence_gap"}
                ),
                _fallback_outcome(result.activity),
            ),
        )

    async def _run_provider_source_intelligence(
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

        if (
            self._youtube_review_intelligence_service is not None
            and _capability_allowed(request, SourceIntelligenceCapability.VIDEO_REVIEW)
        ):
            video_bundles.append(
                await self._youtube_review_intelligence_service.run(
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
                _agent_tool_activity(self._youtube_review_intelligence_service)
            )

        if (
            self._reddit_community_intelligence_service is not None
            and _capability_allowed(
                request,
                SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
            )
        ):
            community_bundles.append(
                await self._reddit_community_intelligence_service.run(
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
                _agent_tool_activity(self._reddit_community_intelligence_service)
            )

        if (
            self._amazon_product_intelligence_service is not None
            and _capability_allowed(
                request,
                SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
            )
        ):
            amazon_bundles.append(
                await self._amazon_product_intelligence_service.run(
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
                _agent_tool_activity(self._amazon_product_intelligence_service)
            )

        if (
            self._ikea_store_intelligence_service is not None
            and _capability_allowed(
                request,
                SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
            )
            and _ikea_source_relevant(
                brief, candidates.products, context.search_results
            )
        ):
            ikea_bundles.append(
                await self._ikea_store_intelligence_service.run(
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
            activity.extend(_agent_tool_activity(self._ikea_store_intelligence_service))

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
            agent_name="ProviderSourceIntelligenceServices",
            runtime_mode="provider_service",
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
                        target_region_code=_effective_region_code(
                            context.active_brief, self._default_region_code
                        ),
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
            return self._insufficient_stage_output(context, RunStage.CATEGORY_ANALYSIS)

        route = await self._category_route(context, products, listings, evidence)
        route_activity = _agent_tool_activity(self._category_router_agent)
        analyses: list[CategoryAnalysis] = []
        activity: list[dict[str, Any]] = [*route_activity]
        for product in products:
            if any(
                item.manual_fallback_reason is not None
                and item.product is not None
                and item.product.product_id == product.product_id
                and not product.source_ids
                for item in context.user_added_products
            ):
                # A shopper report alone cannot satisfy the cited-analysis contract.
                continue
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
            context.refinement_plan is not None
            and context.refinement_plan.stages == (RecomputeStage.RESULT_MODE,)
            and context.prior_recommendation is not None
        ):
            requested = context.refinement_plan.requested_result_mode
            prior = context.prior_recommendation
            mode_results = prior.mode_results
            if requested is not None:
                mode_results = tuple(
                    sorted(mode_results, key=lambda item: item.mode != requested)
                )
            context.recommendation_bundle = prior.model_copy(
                update={
                    "bundle_id": new_id(),
                    "mode_results": mode_results,
                    "verification_action": None,
                    "verification_changes": (),
                }
            )
            return FixtureStageOutput(
                stage=RunStage.COMPARISON_DECISION,
                trace_id=self._stage_trace_id(
                    context.trace_id, RunStage.COMPARISON_DECISION
                ),
                summary="Prepared the requested view of the saved comparison.",
                runtime_mode=self._agent_workflow_mode.value,
                agent_name="SavedComparisonModeSelector",
            )
        if (
            self._agent_workflow_mode == AgentWorkflowMode.LIVE
            and context.general_owner_draft
        ):
            bundle = _with_manual_comparison_rows(
                await self._owner_recommendation(context), context
            )
            context.recommendation_bundle = bundle
            return FixtureStageOutput(
                stage=RunStage.COMPARISON_DECISION,
                trace_id=self._stage_trace_id(
                    context.trace_id, RunStage.COMPARISON_DECISION
                ),
                summary="Prepared the shopping decision for review.",
                payload={
                    "result_author": bundle.result_author or "",
                    "no_strong_buy": str(bundle.no_strong_buy),
                },
                agent_name=context.general_owner_draft.owner_agent_name,
                runtime_mode=AgentWorkflowMode.LIVE.value,
                fallback_outcome="insufficient_evidence"
                if bundle.no_strong_buy
                else None,
            )
        if not _analysis_products(context) or (
            self._agent_workflow_mode == AgentWorkflowMode.FIXTURE
            and context.fixture_output is None
            and context.prior_recommendation is None
        ):
            context.recommendation_bundle = _with_manual_comparison_rows(
                _no_product_recommendation(context), context
            )
            return self._insufficient_stage_output(
                context, RunStage.COMPARISON_DECISION
            )
        if (
            self._agent_workflow_mode != AgentWorkflowMode.LIVE
            or self._comparison_decision_agent is None
        ):
            if context.prior_recommendation is not None:
                from app.agents.live_comparison_decision import (
                    evidence_backed_fallback_recommendation,
                )

                context.recommendation_bundle = evidence_backed_fallback_recommendation(
                    ComparisonDecisionAgentInput(
                        run_id=context.run_id,
                        brief=context.active_brief,
                        products=_analysis_products(context),
                        listings=_analysis_listings(context),
                        category_analyses=context.category_analyses,
                        trust_assessments=context.trust_assessments,
                        evidence=_analysis_evidence(context),
                        user_added_products=_user_added_products(context),
                        requested_result_mode=(
                            context.refinement_plan.requested_result_mode
                            if context.refinement_plan
                            else None
                        ),
                    )
                )
                return FixtureStageOutput(
                    stage=RunStage.COMPARISON_DECISION,
                    trace_id=self._stage_trace_id(
                        context.trace_id, RunStage.COMPARISON_DECISION
                    ),
                    summary="Recomputed the decision from saved evidence.",
                    runtime_mode=AgentWorkflowMode.FIXTURE.value,
                )
            return self._fixture_stage_output(context, RunStage.COMPARISON_DECISION)

        products = _analysis_products(context)
        listings = _analysis_listings(context)
        evidence = _analysis_evidence(context)
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
                requested_result_mode=(
                    context.refinement_plan.requested_result_mode
                    if context.refinement_plan
                    else None
                ),
            )
        )
        bundle = _with_manual_comparison_rows(bundle, context)
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

    async def _owner_recommendation(
        self, context: ShoppingRunContext
    ) -> RecommendationBundle:
        draft = context.general_owner_draft
        assert draft is not None
        (
            searches,
            snapshots,
            evidence,
        ) = await self._persistence_hooks.load_owner_result_sources(context.run_id)
        search_by_id = {item.source_id: item for item in searches}
        snapshot_by_id = {item.source_id: item for item in snapshots}
        evidence_by_id = {item.evidence_id: item for item in evidence}
        context.owner_evidence = evidence
        (
            context.owner_products,
            context.owner_listings,
        ) = await self._persistence_hooks.load_owner_result_products(context.run_id)
        activity = _agent_tool_activity(self._general_shopping_agent)
        chain = tuple(
            f"{item['input']['source_agent']} -> {item['output']['target_agent']}"
            for item in activity
            if item.get("tool_name") == "sdk_handoff"
            and item.get("status") == "completed"
        )
        provenance: dict[str, Any] = {"result_author": draft.owner_agent_name, "handoff_chain": chain}
        expected_chain = (
            ()
            if draft.owner_agent_name == "GeneralShoppingAgent"
            else ("GeneralShoppingAgent -> TechnologyDomainAnalystAgent",)
            if draft.owner_agent_name == "TechnologyDomainAnalystAgent"
            else (
                "GeneralShoppingAgent -> TechnologyDomainAnalystAgent",
                f"TechnologyDomainAnalystAgent -> {draft.owner_agent_name}",
            )
        )
        if chain != expected_chain or draft.owner_agent_name not in {
            "GeneralShoppingAgent",
            "TechnologyDomainAnalystAgent",
            *self._agent_catalog.require(
                "TechnologyDomainAnalystAgent"
            ).target_handoff_agent_names,
        }:
            return _owner_no_strong_buy(
                draft, provenance, "Owner handoff chain did not match the final author."
            )
        selected = next(
            (
                item
                for item in draft.candidates
                if item.name == draft.selected_candidate_name
            ),
            None,
        )
        if draft.outcome != GeneralShoppingOutcome.DRAFT or selected is None:
            return _owner_no_strong_buy(draft, provenance)

        async def validated_candidate(
            candidate: GeneralShoppingCandidate,
        ) -> tuple[GeneralShoppingEvidence, ...] | None:
            valid = []
            for reference in candidate.evidence:
                search = search_by_id.get(reference.source_id)
                snapshot = snapshot_by_id.get(reference.snapshot_id)
                quote = evidence_by_id.get(reference.evidence_id)
                linked_snapshot = (
                    await self._persistence_hooks.load_snapshot_for_search_result(
                        context, reference.source_id
                    )
                    if search is not None
                    else None
                )
                allowed_source_types: set[SourceType] = set()
                excluded_source = False
                if search is not None:
                    assessment = score_source_quality(
                        str(search.url),
                        SourceQualityMetadata(
                            evidence_context=SourceEvidenceContext.GENERAL,
                            target_region_code=(
                                context.active_brief.region.region.country_code
                                if context.active_brief.region is not None
                                else None
                            ),
                        ),
                    )
                    source_class = assessment.source_class
                    excluded_source = assessment.excluded
                    assessed_type = {
                        SourceClass.REVIEW_TESTING: SourceType.PROFESSIONAL_REVIEW,
                        SourceClass.REVIEW_EDITORIAL: SourceType.PROFESSIONAL_REVIEW,
                        SourceClass.OFFICIAL_MANUFACTURER: SourceType.OFFICIAL_BRAND_PAGE,
                        SourceClass.OFFICIAL_STORE_REGIONAL: SourceType.OFFICIAL_BRAND_PAGE,
                        SourceClass.ESTABLISHED_RETAILER_FIRST_PARTY: SourceType.RETAILER_LISTING,
                        SourceClass.ESTABLISHED_RETAILER_MIXED: SourceType.RETAILER_LISTING,
                        SourceClass.OPEN_MARKETPLACE: SourceType.RETAILER_LISTING,
                    }.get(source_class)
                    allowed_source_types = (
                        {assessed_type, SourceType.PRODUCT_PAGE}
                        if assessed_type
                        in {SourceType.OFFICIAL_BRAND_PAGE, SourceType.RETAILER_LISTING}
                        else {assessed_type}
                        if assessed_type is not None
                        else {search.source_type}
                    )
                if (
                    search is None
                    or snapshot is None
                    or quote is None
                    or linked_snapshot is None
                    or linked_snapshot.source_id != snapshot.source_id
                    or quote.source_id != snapshot.source_id
                    or reference.source_type not in allowed_source_types
                    or excluded_source
                    or not _safe_public_result_url(str(search.url))
                    or str(search.url) != str(reference.url)
                    or str(snapshot.url) != str(reference.url)
                    or quote.claim != reference.quote
                    or snapshot.extraction_status != ExtractionStatus.SUCCEEDED
                    or snapshot.extracted_content is None
                    or quote.claim not in snapshot.extracted_content.text
                    or snapshot.quality.level == SourceQualityLevel.WEAK
                    or quote.source_quality.level
                    in {SourceQualityLevel.WEAK, SourceQualityLevel.UNKNOWN}
                    or candidate.name.casefold()
                    not in (quote.claim + " " + (snapshot.title or "")).casefold()
                ):
                    continue
                valid.append(reference)
            domains = {urlsplit(str(item.url)).hostname for item in valid}
            kinds = {item.source_type for item in valid}
            if (
                len(valid) != len(candidate.evidence)
                or len(domains) < 2
                or SourceType.PROFESSIONAL_REVIEW not in kinds
                or not kinds.intersection(
                    {
                        SourceType.PRODUCT_PAGE,
                        SourceType.RETAILER_LISTING,
                        SourceType.OFFICIAL_BRAND_PAGE,
                    }
                )
            ):
                return None

            return tuple(valid)

        valid = await validated_candidate(selected)
        if valid is None:
            return _owner_no_strong_buy(
                draft,
                provenance,
                "Selected product citations failed same-run validation.",
            )

        product = next(
            (
                item
                for item in _analysis_products(context)
                if item.name.casefold() == selected.name.casefold()
            ),
            None,
        )
        snapshot_ids = tuple(dict.fromkeys(item.snapshot_id for item in valid))
        evidence_ids = tuple(dict.fromkeys(item.evidence_id for item in valid))
        if product is None:
            product = await self._persistence_hooks.persist_owner_product(
                context.run_id,
                CanonicalProduct(
                    name=selected.name, category=draft.category, source_ids=snapshot_ids
                ),
            )
            context.owner_products = (*context.owner_products, product)
        matching_listings = tuple(
            item
            for item in _analysis_listings(context)
            if item.product_id == product.product_id
        )
        if matching_listings and all(
            any(
                a.listing_id == item.listing_id
                and a.level == ListingTrustLevel.SUSPICIOUS
                for a in context.trust_assessments
            )
            for item in matching_listings
        ):
            return _owner_no_strong_buy(
                draft,
                provenance,
                "Every known listing for the selected product was suspicious.",
            )
        if (
            context.active_brief.budget
            and context.active_brief.budget.mode == BudgetMode.HARD_CAP
        ):
            budget = context.active_brief.budget.amount
            if not any(
                item.price is not None
                and item.price.currency == budget.currency
                and Decimal(item.price.amount) <= Decimal(budget.amount)
                and not any(
                    assessment.listing_id == item.listing_id
                    and assessment.level == ListingTrustLevel.SUSPICIOUS
                    for assessment in context.trust_assessments
                )
                for item in matching_listings
            ):
                return _owner_no_strong_buy(
                    draft,
                    provenance,
                    "No safe checked listing price supported the hard budget cap.",
                )
        # A quoted product is never promoted into a verified purchase listing.
        confidence = Confidence(score=0.6, level=ConfidenceLevel.MEDIUM)
        mode_results = [
            RecommendationModeResult(
                mode=RecommendationMode.BEST_OVERALL,
                product_id=product.product_id,
                title="Best overall",
                rationale=draft.rationale,
                confidence=confidence,
                evidence_ids=evidence_ids,
                source_ids=snapshot_ids,
            )
        ]
        rows = [
            ComparisonRow(
                product_id=product.product_id,
                evidence_ids=evidence_ids,
                summary=selected.name,
            )
        ]
        runner_up_ids: list[ProductId] = []
        seen_modes = {RecommendationMode.BEST_OVERALL}
        seen_rows: set[tuple[ProductId, ListingId | None]] = {(product.product_id, None)}
        for mode in draft.mode_selections:
            if mode.mode in seen_modes:
                continue
            if (
                mode.mode == RecommendationMode.RUNNER_UP
                and mode.candidate_name == selected.name
            ):
                continue
            candidate = next(
                (item for item in draft.candidates if item.name == mode.candidate_name),
                None,
            )
            if candidate is None:
                continue
            candidate_references = await validated_candidate(candidate)
            if candidate_references is None or not set(mode.evidence_ids).issubset(
                {item.evidence_id for item in candidate_references}
            ):
                continue
            supporting = tuple(
                item
                for item in candidate_references
                if item.evidence_id in mode.evidence_ids
            )
            mode_product = next(
                (
                    item
                    for item in _analysis_products(context)
                    if item.name.casefold() == candidate.name.casefold()
                ),
                None,
            )
            mode_listing = (
                next(
                    (
                        item
                        for item in _analysis_listings(context)
                        if mode_product is not None
                        and item.product_id == mode_product.product_id
                        and item.listing_id == mode.listing_id
                    ),
                    None,
                )
                if mode.listing_id is not None
                else None
            )
            if mode.listing_id is not None and mode_listing is None:
                continue
            if mode_listing is not None:
                mode_trust = next(
                    (
                        item
                        for item in context.trust_assessments
                        if item.listing_id == mode_listing.listing_id
                    ),
                    None,
                )
                if mode_trust is None or mode_trust.level in {
                    ListingTrustLevel.SUSPICIOUS,
                    ListingTrustLevel.WEAK,
                    ListingTrustLevel.UNKNOWN,
                }:
                    continue
            if mode.mode in {
                RecommendationMode.BEST_VALUE,
                RecommendationMode.WITHIN_BUDGET,
                RecommendationMode.STRETCH_PICK,
            } and (mode_listing is None or mode_listing.price is None):
                continue
            if mode.mode in {
                RecommendationMode.BEST_VALUE,
                RecommendationMode.WITHIN_BUDGET,
                RecommendationMode.STRETCH_PICK,
            }:
                assert mode_listing is not None and mode_listing.price is not None
                if not any(
                    (
                        item.source_id in mode_listing.source_ids
                        or item.snapshot_id in mode_listing.source_ids
                    )
                    and any(
                        Decimal(number.rstrip(".,").replace(",", ""))
                        == Decimal(mode_listing.price.amount)
                        for number in re.findall(r"\d[\d,.]*", item.quote)
                        if number.rstrip(".,")
                        .replace(",", "")
                        .replace(".", "", 1)
                        .isdigit()
                    )
                    for item in supporting
                ):
                    continue
            if mode.mode in {
                RecommendationMode.WITHIN_BUDGET,
                RecommendationMode.STRETCH_PICK,
            }:
                mode_budget = context.active_brief.budget
                if (
                    mode_budget is None
                    or mode_listing is None
                    or mode_listing.price is None
                    or mode_listing.price.currency != mode_budget.amount.currency
                ):
                    continue
                listing_amount = Decimal(mode_listing.price.amount)
                budget_amount = Decimal(mode_budget.amount.amount)
                if (
                    mode.mode == RecommendationMode.WITHIN_BUDGET
                    and listing_amount > budget_amount
                ):
                    continue
                if (
                    mode.mode == RecommendationMode.STRETCH_PICK
                    and listing_amount <= budget_amount
                ):
                    continue
            if mode_product is None:
                if mode.mode != RecommendationMode.RUNNER_UP:
                    continue
                mode_product = await self._persistence_hooks.persist_owner_product(
                    context.run_id,
                    CanonicalProduct(
                        name=candidate.name,
                        category=draft.category,
                        source_ids=tuple(
                            dict.fromkeys(
                                item.snapshot_id for item in candidate_references
                            )
                        ),
                    ),
                )
                context.owner_products = (*context.owner_products, mode_product)
            mode_source_ids = tuple(
                dict.fromkeys(item.snapshot_id for item in supporting)
            )
            mode_results.append(
                RecommendationModeResult(
                    mode=mode.mode,
                    product_id=mode_product.product_id,
                    listing_id=mode_listing.listing_id if mode_listing else None,
                    title={
                        RecommendationMode.BEST_VALUE: "Best value",
                        RecommendationMode.WITHIN_BUDGET: "Best within budget",
                        RecommendationMode.STRETCH_PICK: "Stretch upgrade",
                        RecommendationMode.RUNNER_UP: "Runner-up",
                    }[mode.mode],
                    rationale=mode.rationale,
                    confidence=confidence,
                    evidence_ids=mode.evidence_ids,
                    source_ids=mode_source_ids,
                )
            )
            row_key = (
                mode_product.product_id,
                mode_listing.listing_id if mode_listing else None,
            )
            if row_key not in seen_rows:
                rows.append(
                    ComparisonRow(
                        product_id=mode_product.product_id,
                        listing_id=mode_listing.listing_id if mode_listing else None,
                        evidence_ids=mode.evidence_ids,
                        summary=candidate.name,
                    )
                )
                seen_rows.add(row_key)
            if (
                mode.mode == RecommendationMode.RUNNER_UP
                and mode_product.product_id != product.product_id
            ):
                runner_up_ids.append(mode_product.product_id)
            seen_modes.add(mode.mode)
        return RecommendationBundle(
            **provenance,
            final_product_id=product.product_id,
            final_rationale=draft.rationale,
            mode_results=tuple(mode_results),
            runner_up_product_ids=tuple(runner_up_ids),
            comparison_matrix=ComparisonMatrix(
                criteria=(ComparisonCriterion(name="Evidence support"),),
                rows=tuple(rows),
            ),
            evidence_ids=evidence_ids,
            source_ids=snapshot_ids,
        )

    async def _run_verification(
        self,
        context: ShoppingRunContext,
    ) -> FixtureStageOutput:
        if self._agent_workflow_mode != AgentWorkflowMode.LIVE:
            if (
                context.prior_recommendation is not None
                and context.recommendation_bundle is not None
            ):
                report = verify_recommendation_guardrails(
                    VerificationAgentInput(
                        run_id=context.run_id,
                        brief=context.active_brief,
                        recommendation_bundle=context.recommendation_bundle,
                        products=_analysis_products(context),
                        listings=_analysis_listings(context),
                        evidence=_analysis_evidence(context),
                        trust_assessments=context.trust_assessments,
                        category_analyses=context.category_analyses,
                        user_added_products=_user_added_products(context),
                    )
                )
                context.verification_report = report
                context.recommendation_bundle = report.recommendation_bundle
            return self._fixture_stage_output(context, RunStage.VERIFICATION)

        bundle = context.recommendation_bundle
        if bundle is None:
            return self._insufficient_stage_output(context, RunStage.VERIFICATION)
        if self._verifier_critic_agent is None:
            context.recommendation_bundle = _blocked_owner_result(
                bundle, ("Verification was unavailable.",)
            )
            return self._insufficient_stage_output(context, RunStage.VERIFICATION)

        verification_input = VerificationAgentInput(
            run_id=context.run_id,
            brief=context.active_brief,
            recommendation_bundle=bundle,
            products=_analysis_products(context),
            listings=_analysis_listings(context),
            evidence=_analysis_evidence(context),
            trust_assessments=context.trust_assessments,
            category_analyses=context.category_analyses,
            deduplication_decisions=_deduplication_decisions(context),
            user_added_products=_user_added_products(context),
        )
        backend_report = verify_recommendation_guardrails(verification_input)
        if bundle.verification_action == "blocked":
            report = VerificationReport(
                approved=False,
                recommendation_bundle=bundle,
                blocking_issues=bundle.verification_changes,
            )
        elif backend_report.approved:
            report = await self._verifier_critic_agent.run(verification_input)
        else:
            report = backend_report
        if report.approved:
            revised_input = verification_input.model_copy(
                update={"recommendation_bundle": report.recommendation_bundle}
            )
            revised_guardrails = verify_recommendation_guardrails(revised_input)
            if not revised_guardrails.approved:
                report = revised_guardrails
        if report.approved and (
            report.recommendation_bundle.final_product_id != bundle.final_product_id
            or report.recommendation_bundle.final_listing_id != bundle.final_listing_id
            or report.recommendation_bundle.no_strong_buy != bundle.no_strong_buy
            or tuple(
                (item.mode, item.product_id, item.listing_id)
                for item in report.recommendation_bundle.mode_results
            )
            != tuple(
                (item.mode, item.product_id, item.listing_id)
                for item in bundle.mode_results
            )
        ):
            report = VerificationReport(
                approved=False,
                recommendation_bundle=report.recommendation_bundle,
                blocking_issues=(
                    "Verifier changed the active owner's selected product or listing.",
                ),
            )
        changes = tuple(
            key
            for key, value in bundle.model_dump(mode="json").items()
            if report.recommendation_bundle.model_dump(mode="json").get(key) != value
            and key not in {"verification_action", "verification_changes"}
        )
        if report.approved and changes and not report.notes:
            report = VerificationReport(
                approved=False,
                recommendation_bundle=report.recommendation_bundle,
                blocking_issues=("Verifier revision did not include an audit reason.",),
            )
        if not report.approved:
            verified_bundle = _blocked_owner_result(bundle, report.blocking_issues)
            action = "blocked"
        else:
            action = "revised" if changes else "approved"
            verified_bundle = report.recommendation_bundle.model_copy(
                update={
                    "result_author": bundle.result_author,
                    "handoff_chain": bundle.handoff_chain,
                    "verification_action": action,
                    "verification_changes": (*changes, *report.notes),
                }
            )
        context.verification_report = report
        context.recommendation_bundle = verified_bundle
        activity = _agent_tool_activity(self._verifier_critic_agent)
        return FixtureStageOutput(
            stage=RunStage.VERIFICATION,
            trace_id=self._stage_trace_id(context.trace_id, RunStage.VERIFICATION),
            summary="Checked the recommendation for source support and safety.",
            payload={
                "approved": str(report.approved),
                "action": action,
                "changed_fields": ",".join(changes),
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

    def _insufficient_stage_output(
        self, context: ShoppingRunContext, stage: RunStage
    ) -> FixtureStageOutput:
        return FixtureStageOutput(
            stage=stage,
            trace_id=self._stage_trace_id(context.trace_id, stage),
            summary="Not enough verified product offers to continue comparison.",
            payload={"reason": "insufficient_agent_validated_candidates"},
            runtime_mode=self._agent_workflow_mode.value,
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
            RunStage.GENERAL_OWNER: "GeneralShoppingAgent",
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


def _fixture_replay_category(brief: ShoppingBrief) -> str | None:
    """Route only an explicit fixture scenario, never infer a product from it."""
    if brief.category:
        return brief.category.casefold()
    query = brief.original_query.casefold()
    matches = tuple(
        category
        for category, pattern in (
            ("monitor", r"\b(monitors?|displays?)\b"),
            ("tv", r"\b(tvs?|televisions?)\b"),
            ("furniture", r"\b(furniture|sofas?|chairs?|desks?)\b"),
        )
        if re.search(pattern, query)
    )
    return matches[0] if len(matches) == 1 else None


def _no_product_recommendation(context: ShoppingRunContext) -> RecommendationBundle:
    category = _fixture_replay_category(context.active_brief)
    subject = f"{category} products" if category else "products"
    has_listings = any(
        item.listing_extraction is not None for item in context.source_extractions
    )
    next_step = "Try a more specific request or check again later."
    reason = (
        f"We found some {subject}, but not enough verified offers to compare them "
        f"reliably. {next_step}"
        if has_listings
        else f"Not enough verified {subject} and seller information was found to "
        f"make a reliable recommendation. {next_step}"
    )
    return RecommendationBundle(
        no_strong_buy=True,
        no_strong_buy_reason=reason,
        comparison_matrix=ComparisonMatrix(),
        evidence_ids=tuple(
            record.evidence_id for record in context.extraction_evidence
        ),
        source_ids=tuple(
            dict.fromkeys(record.source_id for record in context.extraction_evidence)
        ),
        warnings=(
            "There is not enough information to compare the available products."
            if has_listings
            else "No product listing was verified for this request.",
        ),
    )


def _with_manual_comparison_rows(
    bundle: RecommendationBundle, context: ShoppingRunContext
) -> RecommendationBundle:
    manual_ids = tuple(
        item.product.product_id
        for item in context.user_added_products
        if item.manual_fallback_reason is not None
        and item.product is not None
        and not item.product.source_ids
        and not any(
            listing.product_id == item.product.product_id
            for listing in _analysis_listings(context)
        )
        and not (
            bundle.final_product_id == item.product.product_id and bundle.evidence_ids
        )
    )
    if not manual_ids:
        return bundle
    criteria = bundle.comparison_matrix.criteria or tuple(
        ComparisonCriterion(name=name)
        for name in ("fit", "value", "listing_trust", "evidence")
    )
    rows_by_id = {row.product_id: row for row in bundle.comparison_matrix.rows}
    for product_id in manual_ids:
        rows_by_id[product_id] = ComparisonRow(
            product_id=product_id,
            scores={criterion.name: 0.0 for criterion in criteria},
            summary=MANUAL_UNVERIFIED_SUMMARY,
        )
    return bundle.model_copy(
        update={
            "comparison_matrix": ComparisonMatrix(
                criteria=criteria,
                rows=tuple(rows_by_id.values()),
            ),
        }
    )


def _owner_no_strong_buy(
    _draft: GeneralShoppingDecisionDraft,
    provenance: dict[str, Any],
    rejection_reason: str | None = None,
) -> RecommendationBundle:
    return RecommendationBundle(
        **provenance,
        verification_action="blocked" if rejection_reason else None,
        verification_changes=(rejection_reason,) if rejection_reason else (),
        no_strong_buy=True,
        no_strong_buy_reason=(
            "There is not enough checked evidence to choose a product yet. "
            "Try a more specific request or check again later."
        ),
        comparison_matrix=ComparisonMatrix(),
    )


def _blocked_owner_result(
    bundle: RecommendationBundle, issues: tuple[str, ...]
) -> RecommendationBundle:
    return RecommendationBundle(
        result_author=bundle.result_author,
        handoff_chain=bundle.handoff_chain,
        verification_action="blocked",
        verification_changes=issues,
        no_strong_buy=True,
        no_strong_buy_reason=(
            "We could not confirm enough details to recommend a product safely. "
            "Try a more specific request or check again later."
        ),
        comparison_matrix=ComparisonMatrix(),
    )


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
        products = (
            *tuple(group.product for group in context.deduplication.result.groups),
            *context.owner_products,
        )
    elif context.fixture_output is not None:
        products = (*context.fixture_output.products, *context.owner_products)
    else:
        products = context.owner_products
    return tuple({item.product_id: item for item in products}.values())


def _analysis_listings(context: ShoppingRunContext) -> tuple[ProductListing, ...]:
    listings: list[ProductListing] = list(context.owner_listings)
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
        *context.owner_evidence,
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
        for availability in listing.region_availability:
            source_ids.update(availability.source_ids)
    selected = tuple(
        item
        for item in evidence
        if item.target.product_id in {None, product.product_id}
        and item.target.listing_id in {None, *listing_ids}
        and (
            item.target.product_id == product.product_id
            or (
                item.target.listing_id is not None
                and item.target.listing_id in listing_ids
            )
            or item.source_id in source_ids
        )
    )
    return selected


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
        user_added.input_text,
        user_added.product.name if user_added.product is not None else None,
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
        if (
            f"{lookup_text} official retailer listing"[:500].casefold()
            == normalized_query
        ):
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
    matches_by_listing: dict[ListingId, list[UserAddedListingMatch]] = {}
    for match in output.user_added_matches:
        matches_by_listing.setdefault(match.listing_id, []).append(
            UserAddedListingMatch(
                candidate_id=match.candidate_id,
                source_id=match.source_id,
                confidence=match.confidence,
            )
        )
    direct_match = (
        (
            UserAddedListingMatch(
                candidate_id=item.user_added_candidate_id,
                source_id=item.snapshot.source_id,
                confidence=UserAddedMatchConfidence.CONFIRMED,
            ),
        )
        if item.user_added_candidate_id is not None
        else ()
    )
    return tuple(
        DiscoveredSourceExtraction(
            search_result=item.search_result,
            snapshot=item.snapshot,
            listing_extraction=ProductListingExtraction(
                product=products[listing.product_id],
                listing=listing.model_copy(
                    update={
                        "user_added_matches": (
                            *matches_by_listing.get(listing.listing_id, ()),
                            *direct_match,
                        )
                    }
                ),
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


def _user_added_hints_resolved(
    extracted: list[DiscoveredSourceExtraction],
    user_added_products: tuple[UserAddedProduct, ...],
) -> bool:
    for user_added in user_added_products:
        if user_added.url is not None:
            continue
        matches = {
            item.listing_extraction.product.product_id
            for item in extracted
            if item.listing_extraction is not None
            for match in item.listing_extraction.listing.user_added_matches
            if match.candidate_id == user_added.candidate_id
            and match.confidence == UserAddedMatchConfidence.CONFIRMED
        }
        if len(matches) != 1:
            return False
    return True


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
            "user_added_matches": [
                match.model_dump(mode="json") for match in output.user_added_matches
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
    updated: list[UserAddedProduct] = []
    for user_added in user_added_products:
        matches = [
            (item, match.confidence)
            for item in extractions
            if item.listing_extraction is not None
            for match in item.listing_extraction.listing.user_added_matches
            if match.candidate_id == user_added.candidate_id
        ]
        if not matches:
            updated.append(
                user_added.model_copy(
                    update={
                        "product": None,
                        "listing": None,
                        "possible_product_ids": (),
                    }
                )
                if user_added.url is None
                and user_added.input_text is not None
                and (user_added.listing is not None or user_added.possible_product_ids)
                else user_added
            )
            continue
        product_ids = tuple(
            dict.fromkeys(
                item.listing_extraction.product.product_id for item, _ in matches
                if item.listing_extraction is not None
            )
        )
        confirmed = [
            item
            for item, confidence in matches
            if confidence == UserAddedMatchConfidence.CONFIRMED
        ]
        if len(product_ids) != 1 or not confirmed:
            updated.append(
                user_added.model_copy(
                    update={
                        "product": None,
                        "listing": None,
                        "possible_product_ids": product_ids,
                    }
                )
            )
            continue
        preferred = next(
            (
                item
                for item in confirmed
                if item.search_result.provider.raw.get("user_added_candidate_id")
                == str(user_added.candidate_id)
            ),
            confirmed[0],
        )
        extraction = preferred.listing_extraction
        assert extraction is not None
        updated.append(
            user_added.model_copy(
                update={
                    "product": extraction.product,
                    "listing": extraction.listing,
                    "possible_product_ids": (),
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
