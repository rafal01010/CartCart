from enum import StrEnum
from typing import Any, Protocol

from pydantic import AnyHttpUrl, Field, model_validator

from app.agents.catalog import ProductAnalysisRoute
from app.schemas.analysis import (
    CategoryAnalysis,
    DeduplicationDecision,
    ListingTrustAssessment,
    RecommendationBundle,
    RecommendationMode,
)
from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.ids import CandidateId, ListingId, ProductId, RunId, SourceId
from app.schemas.guided_intake import (
    GuidedAnswerSubmission,
    GuidedIntakeState,
    QuestionId,
    RegionSetupSubmission,
    ShoppingGuardrailResult,
)
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.products import (
    CanonicalProduct,
    ProductListing,
    UserAddedMatchConfidence,
    UserAddedProduct,
)
from app.schemas.regions import RegionCode
from app.schemas.search_sources import (
    AmazonProductEvidenceBundle,
    CommunityDiscussionEvidenceBundle,
    EvidenceConflict,
    EvidenceTargetType,
    IKEAStoreEvidenceBundle,
    SearchPlan,
    SearchResult,
    SourceEvidence,
    SourceSnapshot,
    SourceType,
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


class GeneralShoppingAgentInput(VersionedSchema):
    run_id: RunId
    brief: ShoppingBrief
    user_added_products: tuple[UserAddedProduct, ...] = Field(default_factory=tuple)


class GeneralShoppingOutcome(StrEnum):
    DRAFT = "draft"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class GeneralShoppingEvidence(CartCartBaseModel):
    source_id: SourceId
    snapshot_id: SourceId
    evidence_id: SourceId
    url: AnyHttpUrl
    source_type: SourceType
    quote: str = Field(min_length=1, max_length=400)


class GeneralShoppingCandidate(CartCartBaseModel):
    name: str = Field(min_length=1, max_length=200)
    evidence: tuple[GeneralShoppingEvidence, ...] = Field(min_length=1)


class GeneralShoppingModeSelection(CartCartBaseModel):
    mode: RecommendationMode
    candidate_name: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=1500)
    evidence_ids: tuple[SourceId, ...] = Field(min_length=1, max_length=8)
    listing_id: ListingId | None = None


class GeneralShoppingDecisionDraft(VersionedSchema):
    owner_agent_name: str = "GeneralShoppingAgent"
    category: str = Field(min_length=1, max_length=200)
    specialist_helpful: bool = False
    outcome: GeneralShoppingOutcome
    candidates: tuple[GeneralShoppingCandidate, ...] = Field(default_factory=tuple)
    mode_selections: tuple[GeneralShoppingModeSelection, ...] = Field(
        default_factory=tuple
    )
    selected_candidate_name: str | None = None
    evidence_gaps: tuple[str, ...] = Field(default_factory=tuple)
    hosted_lead_source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    rationale: str = Field(min_length=1, max_length=1500)


class QueryPlannerAgentInput(VersionedSchema):
    run_id: RunId
    brief: ShoppingBrief
    user_added_products: tuple[UserAddedProduct, ...] = Field(default_factory=tuple)


class ExtractedProductMention(VersionedSchema):
    source_id: SourceId
    name: str = Field(min_length=1, max_length=300)
    brand: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    evidence_ids: tuple[SourceId, ...] = Field(min_length=1)


class DiscoveryAgentInput(VersionedSchema):
    run_id: RunId
    brief: ShoppingBrief
    search_plan: SearchPlan
    seed_results: tuple[SearchResult, ...] = Field(default_factory=tuple)
    user_added_products: tuple[UserAddedProduct, ...] = Field(default_factory=tuple)
    product_leads: tuple[ExtractedProductMention, ...] = Field(
        default_factory=tuple, max_length=12
    )
    research_state: "DiscoveryResearchState | None" = None


class DiscoveryResearchState(VersionedSchema):
    cycle: int = Field(ge=1, le=4)
    remaining_page_budget: int = Field(ge=0, le=12)
    product_names: tuple[str, ...] = Field(default_factory=tuple, max_length=12)
    candidates: tuple["DiscoveryCandidateSummary", ...] = Field(
        default_factory=tuple, max_length=12
    )
    evidence: tuple["DiscoveryEvidenceSummary", ...] = Field(
        default_factory=tuple, max_length=24
    )
    listing_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    evidence_gaps: tuple[str, ...] = Field(default_factory=tuple, max_length=12)
    previously_inspected_source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)


class DiscoveryCandidateSummary(VersionedSchema):
    product_id: ProductId
    name: str = Field(min_length=1, max_length=300)
    listing_url: AnyHttpUrl
    seller_name: str = Field(min_length=1, max_length=300)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)


class DiscoveryEvidenceSummary(VersionedSchema):
    evidence_id: SourceId
    source_id: SourceId
    claim: str = Field(min_length=1, max_length=1000)
    target_type: EvidenceTargetType


class DiscoveryAgentOutcome(StrEnum):
    SELECTED = "selected"
    INSUFFICIENT_CANDIDATES = "insufficient_candidates"


class DiscoverySourceKind(StrEnum):
    PROFESSIONAL_REVIEW = "professional_review"
    PRODUCT_PAGE = "product_page"
    RETAILER_LISTING = "retailer_listing"
    OFFICIAL_BRAND_PAGE = "official_brand_page"
    MARKETPLACE_LISTING = "marketplace_listing"
    CATEGORY_COLLECTION = "category_collection"
    COMMUNITY_SOURCE = "community_source"
    IRRELEVANT = "irrelevant"
    UNCERTAIN = "uncertain"


class DiscoveryNextAction(StrEnum):
    FETCH = "fetch"
    RETAIN_AS_EVIDENCE = "retain_as_evidence"
    SEARCH_NAMED_PRODUCT = "search_named_product"
    IGNORE = "ignore"


class DiscoverySourceDecision(VersionedSchema):
    source_id: SourceId
    classification: DiscoverySourceKind
    confidence: float = Field(ge=0, le=1)
    reasons: tuple[str, ...] = Field(min_length=1)
    intended_treatment: str = Field(min_length=1, max_length=300)
    candidate_model_hints: tuple[str, ...] = Field(default_factory=tuple)
    next_action: DiscoveryNextAction


class DiscoveryAgentOutput(VersionedSchema):
    search_results: tuple[SearchResult, ...] = Field(default_factory=tuple)
    source_decisions: tuple[DiscoverySourceDecision, ...] = Field(default_factory=tuple)
    selected_source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    outcome: DiscoveryAgentOutcome = DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES
    notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="before")
    @classmethod
    def _infer_legacy_outcome(cls, data: Any) -> Any:
        if isinstance(data, dict) and "outcome" not in data:
            selected_ids = data.get("selected_source_ids") or ()
            data = {**data}
            data["outcome"] = (
                DiscoveryAgentOutcome.SELECTED
                if selected_ids
                else DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES
            )
        return data

    @model_validator(mode="after")
    def _validate_selected_ids(self) -> "DiscoveryAgentOutput":
        if len(set(self.selected_source_ids)) != len(self.selected_source_ids):
            raise ValueError("selected source IDs must be unique.")

        decision_ids = tuple(item.source_id for item in self.source_decisions)
        if len(set(decision_ids)) != len(decision_ids):
            raise ValueError("discovery source decisions must have unique IDs.")

        result_source_ids = {item.source_id for item in self.search_results}
        if result_source_ids:
            missing_source_ids = tuple(
                source_id
                for source_id in self.selected_source_ids
                if source_id not in result_source_ids
            )
            if missing_source_ids:
                raise ValueError("selected source IDs must exist in search_results.")

        if (
            self.outcome == DiscoveryAgentOutcome.SELECTED
            and not self.selected_source_ids
        ):
            raise ValueError("selected discovery output requires selected_source_ids.")
        if (
            self.outcome == DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES
            and self.selected_source_ids
        ):
            raise ValueError(
                "insufficient discovery output cannot include selected_source_ids."
            )
        return self


class CategoryRouterAgentInput(VersionedSchema):
    run_id: RunId
    brief: ShoppingBrief
    products: tuple[CanonicalProduct, ...] = Field(default_factory=tuple)
    listings: tuple[ProductListing, ...] = Field(default_factory=tuple)
    evidence: tuple[SourceEvidence, ...] = Field(default_factory=tuple)


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


class ExtractionEvidenceGap(VersionedSchema):
    source_id: SourceId
    summary: str = Field(min_length=1, max_length=1000)


class ExtractionAgentInput(VersionedSchema):
    run_id: RunId
    snapshot_ids: tuple[SourceId, ...] = Field(min_length=1, max_length=8)
    category: str | None = None
    user_added_products: tuple[UserAddedProduct, ...] = Field(default_factory=tuple)
    workbench_snapshots: tuple[SourceSnapshot, ...] = Field(default_factory=tuple)
    editorial_snapshot_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    collection_snapshot_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    research_leads: tuple["ExtractionResearchLead", ...] = Field(
        default_factory=tuple, max_length=12
    )


class ExtractionResearchLead(VersionedSchema):
    mention: ExtractedProductMention
    source_evidence: tuple[SourceEvidence, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _evidence_matches_mention(self) -> "ExtractionResearchLead":
        if set(self.mention.evidence_ids) != {
            item.evidence_id for item in self.source_evidence
        } or any(
            item.source_id != self.mention.source_id for item in self.source_evidence
        ):
            raise ValueError("research lead evidence must cite its mention source")
        return self


class ExtractionLeadMatch(VersionedSchema):
    product_id: ProductId
    lead_evidence_ids: tuple[SourceId, ...] = Field(min_length=1)


class ExtractionUserAddedMatch(VersionedSchema):
    candidate_id: CandidateId
    product_id: ProductId
    listing_id: ListingId
    source_id: SourceId
    confidence: UserAddedMatchConfidence
    rationale: str = Field(min_length=1, max_length=500)


class ExtractionAgentOutput(VersionedSchema):
    products: tuple[CanonicalProduct, ...] = Field(default_factory=tuple, max_length=8)
    listings: tuple[ProductListing, ...] = Field(default_factory=tuple, max_length=8)
    source_evidence: tuple[SourceEvidence, ...] = Field(
        default_factory=tuple, max_length=32
    )
    product_mentions: tuple[ExtractedProductMention, ...] = Field(
        default_factory=tuple, max_length=8
    )
    evidence_gaps: tuple[ExtractionEvidenceGap, ...] = Field(
        default_factory=tuple, max_length=8
    )
    lead_matches: tuple[ExtractionLeadMatch, ...] = Field(
        default_factory=tuple, max_length=8
    )
    user_added_matches: tuple[ExtractionUserAddedMatch, ...] = Field(
        default_factory=tuple, max_length=32
    )

    @model_validator(mode="after")
    def _validate_entity_links(self) -> "ExtractionAgentOutput":
        products = {item.product_id: item for item in self.products}
        listings = {item.listing_id: item for item in self.listings}
        evidence_ids = {item.evidence_id for item in self.source_evidence}
        if len(products) != len(self.products) or len(listings) != len(self.listings):
            raise ValueError("extraction entity IDs must be unique")
        if len(evidence_ids) != len(self.source_evidence):
            raise ValueError("extraction evidence IDs must be unique")
        for listing in self.listings:
            if listing.product_id not in products:
                raise ValueError(
                    "extracted listing must reference an extracted product"
                )
        for product in self.products:
            if not set(product.listing_ids).issubset(listings):
                raise ValueError("product references an unknown extracted listing")
        for evidence in self.source_evidence:
            target = evidence.target
            if target.product_id and target.product_id not in products:
                raise ValueError("evidence references an unknown product")
            if target.listing_id and target.listing_id not in listings:
                raise ValueError("evidence references an unknown listing")
        for mention in self.product_mentions:
            if not set(mention.evidence_ids).issubset(evidence_ids):
                raise ValueError("product mention references unknown evidence")
            if any(
                evidence.source_id != mention.source_id
                for evidence in self.source_evidence
                if evidence.evidence_id in mention.evidence_ids
            ):
                raise ValueError("product mention evidence must cite its source")
        for match in self.lead_matches:
            if match.product_id not in products:
                raise ValueError("lead match references unknown extracted product")
        listing_product_ids = {listing.product_id for listing in self.listings}
        for match in self.user_added_matches:
            if (
                match.product_id not in listing_product_ids
                or match.listing_id not in listings
            ):
                raise ValueError("user-added match requires a cited extracted listing")
            if listings[match.listing_id].product_id != match.product_id:
                raise ValueError("user-added match listing/product identity differs")
            if match.source_id not in listings[match.listing_id].source_ids:
                raise ValueError("user-added match must cite its listing source")
        if len(
            {
                (match.candidate_id, match.listing_id)
                for match in self.user_added_matches
            }
        ) != len(self.user_added_matches):
            raise ValueError("duplicate user-added match")
        matched_lead_ids = tuple(
            evidence_id
            for match in self.lead_matches
            for evidence_id in match.lead_evidence_ids
        )
        if len(set(matched_lead_ids)) != len(matched_lead_ids):
            raise ValueError("lead evidence may match only one extracted product")
        return self


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
    target_region_code: RegionCode | None = None
    evidence: tuple[SourceEvidence, ...] = Field(default_factory=tuple)
    rule_based_assessment: ListingTrustAssessment | None = None


class SourceIntelligenceAgentInput(VersionedSchema):
    run_id: RunId
    brief: ShoppingBrief
    products: tuple[CanonicalProduct, ...] = Field(default_factory=tuple)
    listings: tuple[ProductListing, ...] = Field(default_factory=tuple)
    source_snapshots: tuple[SourceSnapshot, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_references(self) -> "SourceIntelligenceAgentInput":
        product_ids = {product.product_id for product in self.products}
        if len(product_ids) != len(self.products):
            raise ValueError("source-specialist product IDs must be unique.")
        listing_ids = {listing.listing_id for listing in self.listings}
        if len(listing_ids) != len(self.listings):
            raise ValueError("source-specialist listing IDs must be unique.")
        if any(listing.product_id not in product_ids for listing in self.listings):
            raise ValueError(
                "source-specialist listings must reference supplied products."
            )
        snapshot_ids = {snapshot.source_id for snapshot in self.source_snapshots}
        if len(snapshot_ids) != len(self.source_snapshots):
            raise ValueError("source-specialist snapshot IDs must be unique.")
        return self


class SourceIntelligenceAgentOutput(VersionedSchema):
    source_evidence: tuple[SourceEvidence, ...] = Field(default_factory=tuple)
    evidence_conflicts: tuple[EvidenceConflict, ...] = Field(default_factory=tuple)


class YouTubeReviewIntelligenceAgentInput(SourceIntelligenceAgentInput):
    video_queries: tuple[str, ...] = Field(default_factory=tuple)
    target_region_code: RegionCode | None = None


class RedditCommunityIntelligenceAgentInput(SourceIntelligenceAgentInput):
    community_queries: tuple[str, ...] = Field(default_factory=tuple)
    target_region_code: RegionCode | None = None


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
    products: tuple[CanonicalProduct, ...] = Field(default_factory=tuple)
    listings: tuple[ProductListing, ...] = Field(default_factory=tuple)
    evidence: tuple[SourceEvidence, ...] = Field(default_factory=tuple)
    trust_assessments: tuple[ListingTrustAssessment, ...] = Field(default_factory=tuple)
    category_analyses: tuple[CategoryAnalysis, ...] = Field(default_factory=tuple)
    deduplication_decisions: tuple[DeduplicationDecision, ...] = Field(
        default_factory=tuple
    )
    user_added_products: tuple[UserAddedProduct, ...] = Field(default_factory=tuple)


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


class GeneralShoppingAgent(Protocol):
    async def run(
        self, input_data: GeneralShoppingAgentInput
    ) -> GeneralShoppingDecisionDraft:
        """Own a broad live shopping request with checked evidence."""


class CategoryRouterAgent(Protocol):
    async def run(self, input_data: CategoryRouterAgentInput) -> ProductAnalysisRoute:
        """Declare the product-analysis route with generic fallback."""


class ExtractionReviewAgent(Protocol):
    async def run(
        self,
        input_data: ExtractionReviewAgentInput,
    ) -> ExtractionReviewAgentOutput:
        """Review fixture extraction output without model calls."""


class ExtractionAgent(Protocol):
    async def run(self, input_data: ExtractionAgentInput) -> ExtractionAgentOutput:
        """Interpret persisted snapshots into cited entities and explicit gaps."""


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


# Provider-only implementations satisfy these service ports. The *Agent ports
# above are reserved for model-running SDK specialists; they must not be used
# as the orchestrator type for direct provider dispatch.
class YouTubeReviewIntelligenceServicePort(Protocol):
    async def run(
        self, input_data: YouTubeReviewIntelligenceAgentInput
    ) -> VideoReviewEvidenceBundle: ...


class RedditCommunityIntelligenceServicePort(Protocol):
    async def run(
        self, input_data: RedditCommunityIntelligenceAgentInput
    ) -> CommunityDiscussionEvidenceBundle: ...


class AmazonProductIntelligenceServicePort(Protocol):
    async def run(
        self, input_data: AmazonProductIntelligenceAgentInput
    ) -> AmazonProductEvidenceBundle: ...


class IKEAStoreIntelligenceServicePort(Protocol):
    async def run(
        self, input_data: IKEAStoreIntelligenceAgentInput
    ) -> IKEAStoreEvidenceBundle: ...


class ComparisonDecisionAgent(Protocol):
    async def run(
        self,
        input_data: ComparisonDecisionAgentInput,
    ) -> RecommendationBundle:
        """Produce recommendation modes from one fixture analysis pass."""


class VerifierCriticAgent(Protocol):
    async def run(self, input_data: VerificationAgentInput) -> VerificationReport:
        """Verify a recommendation bundle without live model calls."""
