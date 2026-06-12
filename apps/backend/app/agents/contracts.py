from typing import Protocol

from pydantic import Field

from app.schemas.analysis import (
    CategoryAnalysis,
    DeduplicationDecision,
    ListingTrustAssessment,
    RecommendationBundle,
)
from app.schemas.base import VersionedSchema
from app.schemas.ids import RunId, SourceId
from app.schemas.guided_intake import (
    GuidedAnswerSubmission,
    GuidedIntakeState,
    QuestionId,
    RegionSetupSubmission,
    ShoppingGuardrailResult,
)
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.products import CanonicalProduct, ProductListing, UserAddedProduct
from app.schemas.regions import RegionCode
from app.schemas.search_sources import (
    AmazonProductEvidenceBundle,
    CommunityDiscussionEvidenceBundle,
    EvidenceConflict,
    IKEAStoreEvidenceBundle,
    SearchPlan,
    SearchResult,
    SourceEvidence,
    SourceSnapshot,
    VideoReviewEvidenceBundle,
)


class IntakeAgentInput(VersionedSchema):
    run_id: RunId
    request: CreateSessionRequest


class ShoppingScopeGuardrailInput(VersionedSchema):
    user_input: str = Field(min_length=1, max_length=4000)
    prior_answers: tuple[GuidedAnswerSubmission, ...] = Field(default_factory=tuple)


class ShoppingGuideAgentInput(VersionedSchema):
    user_input: str = Field(min_length=1, max_length=4000)
    region_setup: RegionSetupSubmission | None = None
    prior_answers: tuple[GuidedAnswerSubmission, ...] = Field(default_factory=tuple)
    skipped_question_ids: tuple[QuestionId, ...] = Field(default_factory=tuple)
    reanswer_question_id: QuestionId | None = None
    start_analysis_requested: bool = False


class QueryPlannerAgentInput(VersionedSchema):
    run_id: RunId
    brief: ShoppingBrief


class DiscoveryAgentInput(VersionedSchema):
    run_id: RunId
    brief: ShoppingBrief
    search_plan: SearchPlan
    seed_results: tuple[SearchResult, ...] = Field(default_factory=tuple)


class DiscoveryAgentOutput(VersionedSchema):
    search_results: tuple[SearchResult, ...] = Field(default_factory=tuple)
    selected_source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)


class ExtractionReviewAgentInput(VersionedSchema):
    run_id: RunId
    source_snapshots: tuple[SourceSnapshot, ...] = Field(default_factory=tuple)
    search_results: tuple[SearchResult, ...] = Field(default_factory=tuple)
    notes: tuple[str, ...] = Field(default_factory=tuple)


class ExtractionReviewAgentOutput(VersionedSchema):
    source_snapshots: tuple[SourceSnapshot, ...] = Field(default_factory=tuple)
    source_evidence: tuple[SourceEvidence, ...] = Field(default_factory=tuple)
    products: tuple[CanonicalProduct, ...] = Field(default_factory=tuple)
    listings: tuple[ProductListing, ...] = Field(default_factory=tuple)


class DeduplicationReviewAgentInput(VersionedSchema):
    run_id: RunId
    products: tuple[CanonicalProduct, ...] = Field(default_factory=tuple)
    listings: tuple[ProductListing, ...] = Field(default_factory=tuple)
    evidence: tuple[SourceEvidence, ...] = Field(default_factory=tuple)


class ProductAnalysisAgentInput(VersionedSchema):
    run_id: RunId
    brief: ShoppingBrief
    product: CanonicalProduct
    listings: tuple[ProductListing, ...] = Field(default_factory=tuple)
    evidence: tuple[SourceEvidence, ...] = Field(default_factory=tuple)


class SellerListingTrustAgentInput(VersionedSchema):
    run_id: RunId
    listing: ProductListing
    evidence: tuple[SourceEvidence, ...] = Field(default_factory=tuple)


class SourceIntelligenceAgentInput(VersionedSchema):
    run_id: RunId
    brief: ShoppingBrief
    products: tuple[CanonicalProduct, ...] = Field(default_factory=tuple)
    listings: tuple[ProductListing, ...] = Field(default_factory=tuple)
    source_snapshots: tuple[SourceSnapshot, ...] = Field(default_factory=tuple)


class SourceIntelligenceAgentOutput(VersionedSchema):
    source_evidence: tuple[SourceEvidence, ...] = Field(default_factory=tuple)
    evidence_conflicts: tuple[EvidenceConflict, ...] = Field(default_factory=tuple)


class YouTubeReviewIntelligenceAgentInput(SourceIntelligenceAgentInput):
    video_queries: tuple[str, ...] = Field(default_factory=tuple)


class RedditCommunityIntelligenceAgentInput(SourceIntelligenceAgentInput):
    community_queries: tuple[str, ...] = Field(default_factory=tuple)


class AmazonProductIntelligenceAgentInput(SourceIntelligenceAgentInput):
    product_queries: tuple[str, ...] = Field(default_factory=tuple)
    target_region_code: RegionCode | None = None


class IKEAStoreIntelligenceAgentInput(SourceIntelligenceAgentInput):
    product_queries: tuple[str, ...] = Field(default_factory=tuple)
    target_region_code: RegionCode | None = None


class ComparisonDecisionAgentInput(VersionedSchema):
    run_id: RunId
    brief: ShoppingBrief
    products: tuple[CanonicalProduct, ...] = Field(min_length=1)
    listings: tuple[ProductListing, ...] = Field(default_factory=tuple)
    category_analyses: tuple[CategoryAnalysis, ...] = Field(default_factory=tuple)
    trust_assessments: tuple[ListingTrustAssessment, ...] = Field(default_factory=tuple)
    deduplication_decisions: tuple[DeduplicationDecision, ...] = Field(
        default_factory=tuple
    )
    evidence: tuple[SourceEvidence, ...] = Field(default_factory=tuple)
    user_added_products: tuple[UserAddedProduct, ...] = Field(default_factory=tuple)


class VerificationAgentInput(VersionedSchema):
    run_id: RunId
    brief: ShoppingBrief
    recommendation_bundle: RecommendationBundle
    evidence: tuple[SourceEvidence, ...] = Field(default_factory=tuple)
    trust_assessments: tuple[ListingTrustAssessment, ...] = Field(default_factory=tuple)
    category_analyses: tuple[CategoryAnalysis, ...] = Field(default_factory=tuple)


class VerificationReport(VersionedSchema):
    approved: bool
    recommendation_bundle: RecommendationBundle
    blocking_issues: tuple[str, ...] = Field(default_factory=tuple)
    notes: tuple[str, ...] = Field(default_factory=tuple)


class IntakeAgent(Protocol):
    async def run(self, input_data: IntakeAgentInput) -> ShoppingBrief:
        """Produce a typed shopping brief from user input."""


class ShoppingScopeGuardrail(Protocol):
    async def run(
        self,
        input_data: ShoppingScopeGuardrailInput,
    ) -> ShoppingGuardrailResult:
        """Classify whether guided shopping intake may proceed."""


class ShoppingGuideAgent(Protocol):
    async def run(self, input_data: ShoppingGuideAgentInput) -> GuidedIntakeState:
        """Produce the next user-facing guided intake state."""


class QueryPlannerAgent(Protocol):
    async def run(self, input_data: QueryPlannerAgentInput) -> SearchPlan:
        """Produce a typed search plan for the shopping brief."""


class DiscoveryAgent(Protocol):
    async def run(self, input_data: DiscoveryAgentInput) -> DiscoveryAgentOutput:
        """Produce fixture discovery selections without provider calls."""


class ExtractionReviewAgent(Protocol):
    async def run(
        self,
        input_data: ExtractionReviewAgentInput,
    ) -> ExtractionReviewAgentOutput:
        """Review fixture extraction output without model calls."""


class DeduplicationReviewAgent(Protocol):
    async def run(
        self,
        input_data: DeduplicationReviewAgentInput,
    ) -> tuple[DeduplicationDecision, ...]:
        """Review fixture duplicate decisions."""


class GenericProductAnalystAgent(Protocol):
    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        """Analyze product fit with the generic fallback contract."""


class TechnologyDomainAnalystAgent(Protocol):
    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        """Analyze broad technology-product fit."""


class MonitorSpecialistAgent(Protocol):
    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        """Analyze monitor-specific product fit."""


class SmartphoneSpecialistAgent(Protocol):
    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        """Analyze smartphone-specific product fit."""


class LaptopSpecialistAgent(Protocol):
    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        """Analyze laptop-specific product fit."""


class EarphonesHeadphonesSpecialistAgent(Protocol):
    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        """Analyze earphone/headphone-specific product fit."""


class TVSpecialistAgent(Protocol):
    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        """Analyze TV-specific product fit."""


class SmartwatchSpecialistAgent(Protocol):
    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        """Analyze smartwatch-specific product fit."""


class SellerListingTrustAgent(Protocol):
    async def run(
        self,
        input_data: SellerListingTrustAgentInput,
    ) -> ListingTrustAssessment:
        """Analyze seller and listing trust independently of product quality."""


class SourceIntelligenceAgent(Protocol):
    async def run(
        self,
        input_data: SourceIntelligenceAgentInput,
    ) -> SourceIntelligenceAgentOutput:
        """Produce source-backed evidence from reusable source intelligence."""


class YouTubeReviewIntelligenceAgent(Protocol):
    async def run(
        self,
        input_data: YouTubeReviewIntelligenceAgentInput,
    ) -> VideoReviewEvidenceBundle:
        """Produce video review evidence without assuming transcript availability."""


class RedditCommunityIntelligenceAgent(Protocol):
    async def run(
        self,
        input_data: RedditCommunityIntelligenceAgentInput,
    ) -> CommunityDiscussionEvidenceBundle:
        """Produce qualitative Reddit/community evidence with source context."""


class AmazonProductIntelligenceAgent(Protocol):
    async def run(
        self,
        input_data: AmazonProductIntelligenceAgentInput,
    ) -> AmazonProductEvidenceBundle:
        """Produce Amazon product/listing/review evidence without recommendations."""


class IKEAStoreIntelligenceAgent(Protocol):
    async def run(
        self,
        input_data: IKEAStoreIntelligenceAgentInput,
    ) -> IKEAStoreEvidenceBundle:
        """Produce region-aware official IKEA store evidence and gaps."""


class ComparisonDecisionAgent(Protocol):
    async def run(
        self,
        input_data: ComparisonDecisionAgentInput,
    ) -> RecommendationBundle:
        """Produce recommendation modes from one fixture analysis pass."""


class VerifierCriticAgent(Protocol):
    async def run(self, input_data: VerificationAgentInput) -> VerificationReport:
        """Verify a recommendation bundle without live model calls."""
