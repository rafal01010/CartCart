from dataclasses import dataclass
from decimal import Decimal
import re

from pydantic import AnyHttpUrl

from app.agents.contracts import (
    ComparisonDecisionAgentInput,
    DeduplicationReviewAgentInput,
    DiscoveryAgentInput,
    DiscoveryAgentOutput,
    ExtractionReviewAgentInput,
    ExtractionReviewAgentOutput,
    AmazonProductIntelligenceAgentInput,
    IKEAStoreIntelligenceAgentInput,
    IntakeAgentInput,
    ProductAnalysisAgentInput,
    QueryPlannerAgentInput,
    RedditCommunityIntelligenceAgentInput,
    SellerListingTrustAgentInput,
    ShoppingGuideAgentInput,
    ShoppingScopeGuardrailInput,
    SourceIntelligenceAgentInput,
    SourceIntelligenceAgentOutput,
    VerificationAgentInput,
    VerificationReport,
    YouTubeReviewIntelligenceAgentInput,
)
from app.schemas.analysis import (
    CategoryAnalysis,
    ComparisonCriterion,
    ComparisonMatrix,
    ComparisonRow,
    DeduplicationDecision,
    DeduplicationOutcome,
    ListingTrustAssessment,
    RecommendationBundle,
    RecommendationMode,
    RecommendationModeResult,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.guided_intake import (
    AnalysisStartAvailability,
    ChoiceGuidedAnswer,
    ChoiceWithTextGuidedAnswer,
    CurrentGuidedQuestion,
    GuidedAnswer,
    GuidedAnswerSurface,
    GuidedCaptureTarget,
    GuidedIntakeState,
    GuidedIntakeStatus,
    GuidedQuestionPurpose,
    InlineChoiceControl,
    InlineChoiceControlType,
    InlineChoiceOption,
    LocalRegionSetupState,
    NaturalLanguageGuidedAnswer,
    PriorQuestionNavigationState,
    ProgressDisplayKind,
    ProgressDisplayStatus,
    ReanswerableQuestion,
    RegionSetupStatus,
    RegionSetupSubmission,
    ShoppingGuardrailDecision,
    ShoppingGuardrailReason,
    ShoppingGuardrailResult,
    SkippableQuestionState,
    YesNoGuidedAnswer,
)
from app.schemas.ids import new_id
from app.schemas.intake import (
    BudgetConstraint,
    BudgetMode,
    FieldSource,
    PreferenceConstraint,
    PreferenceMode,
    RegionPreference,
    ShoppingBrief,
)
from app.schemas.money import Money
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.schemas.search_sources import (
    AmazonEvidenceFactType,
    AmazonListingContext,
    AmazonProductEvidence,
    AmazonProductEvidenceBundle,
    CommunityDiscussionContext,
    CommunityDiscussionEvidence,
    CommunityDiscussionEvidenceBundle,
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceType,
    ExtractionStatus,
    IKEAEvidenceFactType,
    IKEAStoreContext,
    IKEAStoreEvidence,
    IKEAStoreEvidenceBundle,
    ProviderMetadata,
    RegionalStoreAvailability,
    SearchIntent,
    SearchPlan,
    SearchQuery,
    SearchResult,
    SourceEvidence,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
    TranscriptAvailability,
    VideoReviewEvidenceBundle,
    VideoSource,
)
from app.schemas.source_references import SourceReference
from app.services.listing_trust import ListingTrustRuleContext, assess_listing_trust
from app.services.recommendation_trust import (
    integrate_trust_analysis_into_recommendation,
)

FIRST_QUESTION_ID = "first-question"
MONITOR_CONNECTION_QUESTION_ID = "monitor-connection"
COMPARISON_PRIORITY_QUESTION_ID = "comparison-priority"
BUDGET_QUESTION_ID = "budget"
CONSIDERED_PRODUCTS_QUESTION_ID = "considered-products"


@dataclass(frozen=True)
class FakeIntakeAgent:
    output: ShoppingBrief | None = None

    async def run(self, input_data: IntakeAgentInput) -> ShoppingBrief:
        if self.output is not None:
            return self.output
        return ShoppingBrief(
            original_query=input_data.request.query,
            category="monitor",
            category_source=FieldSource.INFERRED,
            region=input_data.request.region,
            budget=input_data.request.budget,
            constraints=input_data.request.constraints,
            preferences=input_data.request.preferences,
        )


@dataclass(frozen=True)
class FakeShoppingScopeGuardrail:
    output: ShoppingGuardrailResult | None = None

    async def run(
        self,
        input_data: ShoppingScopeGuardrailInput,
    ) -> ShoppingGuardrailResult:
        if self.output is not None:
            return self.output
        return _guardrail_for_user_input(input_data.user_input)


@dataclass(frozen=True)
class FakeShoppingGuideAgent:
    output: GuidedIntakeState | None = None

    async def run(self, input_data: ShoppingGuideAgentInput) -> GuidedIntakeState:
        if self.output is not None:
            return self.output

        guardrail = _guardrail_for_user_input(input_data.user_input)
        if guardrail.decision == ShoppingGuardrailDecision.BLOCKED:
            return GuidedIntakeState(
                status=GuidedIntakeStatus.BLOCKED,
                guardrail=guardrail,
                region_setup=_region_setup_state(input_data.region_setup),
                progress=ProgressDisplayStatus(
                    kind=ProgressDisplayKind.BLOCKED,
                    message="This request is outside shopping help.",
                ),
            )

        answer_map = {
            submission.question_id: submission.answer
            for submission in input_data.prior_answers
        }
        first_followup = _first_followup_question_id(input_data.user_input)
        ready_requested = (
            input_data.start_analysis_requested
            or CONSIDERED_PRODUCTS_QUESTION_ID in answer_map
            or CONSIDERED_PRODUCTS_QUESTION_ID in input_data.skipped_question_ids
        )
        if ready_requested and input_data.reanswer_question_id is None:
            return _ready_guided_state(input_data, answer_map)

        question_id = input_data.reanswer_question_id
        if question_id is None:
            if (
                first_followup not in answer_map
                and first_followup not in input_data.skipped_question_ids
            ):
                question_id = first_followup
            elif (
                BUDGET_QUESTION_ID not in answer_map
                and BUDGET_QUESTION_ID not in input_data.skipped_question_ids
            ):
                question_id = BUDGET_QUESTION_ID
            else:
                question_id = CONSIDERED_PRODUCTS_QUESTION_ID

        question = _guided_question_by_id(question_id, input_data.user_input)
        return GuidedIntakeState(
            status=GuidedIntakeStatus.COLLECTING,
            current_question=question,
            navigation=_navigation_state(answer_map, input_data.reanswer_question_id),
            skippable_question=SkippableQuestionState(
                can_skip=question.question_id
                in {BUDGET_QUESTION_ID, CONSIDERED_PRODUCTS_QUESTION_ID},
            ),
            analysis_start=AnalysisStartAvailability(
                enough_information=True,
                can_skip_all_and_start_analysis=True,
                message="We can start with what you have already shared.",
            ),
            region_setup=_region_setup_state(input_data.region_setup),
            progress=ProgressDisplayStatus(
                kind=ProgressDisplayKind.IDLE,
                message="Ready for your answer.",
            ),
        )


@dataclass(frozen=True)
class FakeQueryPlannerAgent:
    output: SearchPlan | None = None

    async def run(self, input_data: QueryPlannerAgentInput) -> SearchPlan:
        if self.output is not None:
            return self.output
        return SearchPlan(
            queries=(
                SearchQuery(
                    query=f"{input_data.brief.original_query} reviews",
                    intent=SearchIntent.REVIEW,
                    required_source_types=(SourceType.PROFESSIONAL_REVIEW,),
                ),
            ),
            rationale="Fixture query plan.",
        )


@dataclass(frozen=True)
class FakeDiscoveryAgent:
    output: DiscoveryAgentOutput | None = None

    async def run(self, input_data: DiscoveryAgentInput) -> DiscoveryAgentOutput:
        if self.output is not None:
            return self.output
        search_results = input_data.seed_results or (
            _search_result(input_data.search_plan.queries[0]),
        )
        return DiscoveryAgentOutput(
            search_results=search_results,
            selected_source_ids=tuple(result.source_id for result in search_results),
        )


@dataclass(frozen=True)
class FakeExtractionReviewAgent:
    output: ExtractionReviewAgentOutput | None = None

    async def run(
        self,
        input_data: ExtractionReviewAgentInput,
    ) -> ExtractionReviewAgentOutput:
        if self.output is not None:
            return self.output
        snapshot = input_data.source_snapshots[0] if input_data.source_snapshots else (
            _source_snapshot()
        )
        evidence = _source_metadata_evidence(snapshot)
        product = CanonicalProduct(
            name="Fixture Monitor 27",
            brand="Fixture",
            model="Monitor 27",
            category="monitor",
            source_ids=(snapshot.source_id,),
        )
        listing = ProductListing(
            product_id=product.product_id,
            title="Fixture Monitor 27 - Official Store",
            url=AnyHttpUrl("https://example.com/products/fixture-monitor-27"),
            seller=SellerProfile(seller_name="Fixture Official"),
            source_ids=(snapshot.source_id,),
        )
        return ExtractionReviewAgentOutput(
            source_snapshots=(snapshot,),
            source_evidence=(evidence,),
            products=(product,),
            listings=(listing,),
        )


@dataclass(frozen=True)
class FakeDeduplicationReviewAgent:
    output: tuple[DeduplicationDecision, ...] | None = None

    async def run(
        self,
        input_data: DeduplicationReviewAgentInput,
    ) -> tuple[DeduplicationDecision, ...]:
        if self.output is not None:
            return self.output
        product_id = (
            input_data.products[0].product_id if input_data.products else new_id()
        )
        evidence_ids = tuple(item.evidence_id for item in input_data.evidence) or (
            new_id(),
        )
        return (
            DeduplicationDecision(
                candidate_ids=(new_id(), new_id()),
                outcome=DeduplicationOutcome.UNCERTAIN,
                canonical_product_id=product_id,
                confidence=_confidence(0.6),
                rationale="Fixture dedupe decision.",
                evidence_ids=evidence_ids,
            ),
        )


@dataclass(frozen=True)
class FakeGenericProductAnalystAgent:
    output: CategoryAnalysis | None = None

    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        return self.output or _category_analysis(input_data, "generic")


@dataclass(frozen=True)
class FakeTechnologyDomainAnalystAgent:
    output: CategoryAnalysis | None = None

    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        return self.output or _category_analysis(input_data, "technology")


@dataclass(frozen=True)
class FakeMonitorSpecialistAgent:
    output: CategoryAnalysis | None = None

    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        return self.output or _category_analysis(input_data, "monitor")


@dataclass(frozen=True)
class FakeSmartphoneSpecialistAgent:
    output: CategoryAnalysis | None = None

    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        return self.output or _category_analysis(input_data, "smartphone")


@dataclass(frozen=True)
class FakeLaptopSpecialistAgent:
    output: CategoryAnalysis | None = None

    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        return self.output or _category_analysis(input_data, "laptop")


@dataclass(frozen=True)
class FakeEarphonesHeadphonesSpecialistAgent:
    output: CategoryAnalysis | None = None

    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        return self.output or _category_analysis(input_data, "earphones_headphones")


@dataclass(frozen=True)
class FakeTVSpecialistAgent:
    output: CategoryAnalysis | None = None

    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        return self.output or _category_analysis(input_data, "tv")


@dataclass(frozen=True)
class FakeSmartwatchSpecialistAgent:
    output: CategoryAnalysis | None = None

    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        return self.output or _category_analysis(input_data, "smartwatch")


@dataclass(frozen=True)
class FakeSellerListingTrustAgent:
    output: ListingTrustAssessment | None = None

    async def run(
        self,
        input_data: SellerListingTrustAgentInput,
    ) -> ListingTrustAssessment:
        if self.output is not None:
            return self.output
        if input_data.rule_based_assessment is not None:
            return input_data.rule_based_assessment
        evidence_ids = tuple(item.evidence_id for item in input_data.evidence) or (
            new_id(),
        )
        return assess_listing_trust(
            input_data.listing,
            ListingTrustRuleContext(
                evidence_ids=evidence_ids,
                source_ids=input_data.listing.source_ids,
            ),
        )


@dataclass(frozen=True)
class FakeSourceIntelligenceAgent:
    output: SourceIntelligenceAgentOutput | None = None

    async def run(
        self,
        input_data: SourceIntelligenceAgentInput,
    ) -> SourceIntelligenceAgentOutput:
        if self.output is not None:
            return self.output
        snapshot = input_data.source_snapshots[0] if input_data.source_snapshots else (
            _source_snapshot()
        )
        return SourceIntelligenceAgentOutput(
            source_evidence=(_source_metadata_evidence(snapshot),),
        )


@dataclass(frozen=True)
class FakeYouTubeReviewIntelligenceAgent:
    output: VideoReviewEvidenceBundle | None = None

    async def run(
        self,
        input_data: YouTubeReviewIntelligenceAgentInput,
    ) -> VideoReviewEvidenceBundle:
        if self.output is not None:
            return self.output
        source_id = new_id()
        video = VideoSource(
            video_id="fixture-video-1",
            url=AnyHttpUrl("https://www.youtube.com/watch?v=fixture-video-1"),
            title="Fixture review video",
            channel_name="Fixture Reviews",
            transcript_availability=TranscriptAvailability.NOT_CHECKED,
        )
        return VideoReviewEvidenceBundle(
            videos=(video,),
            source_references=(
                SourceReference(
                    source_id=source_id,
                    url=video.url,
                    title=video.title,
                ),
            ),
            transcript_gap_notes=("Fixture mode does not retrieve transcripts.",),
        )


@dataclass(frozen=True)
class FakeRedditCommunityIntelligenceAgent:
    output: CommunityDiscussionEvidenceBundle | None = None

    async def run(
        self,
        input_data: RedditCommunityIntelligenceAgentInput,
    ) -> CommunityDiscussionEvidenceBundle:
        if self.output is not None:
            return self.output
        source_id = new_id()
        product_id = (
            input_data.products[0].product_id if input_data.products else new_id()
        )
        source_url = AnyHttpUrl(
            "https://www.reddit.com/r/BuyItForLife/comments/fixture/thread/"
        )
        discussion = CommunityDiscussionContext(
            source_id=source_id,
            url=source_url,
            community_name="r/BuyItForLife",
            thread_id="fixture-thread",
            thread_title="Fixture owner impressions",
            comment_count=12,
            extracted_public_summary=(
                "Fixture public thread summary with recurring owner comments."
            ),
        )
        return CommunityDiscussionEvidenceBundle(
            source_references=(
                SourceReference(
                    source_id=source_id,
                    url=source_url,
                    title=discussion.thread_title,
                ),
            ),
            discussions=(discussion,),
            evidence=(
                CommunityDiscussionEvidence(
                    source_id=source_id,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.PRODUCT,
                        product_id=product_id,
                    ),
                    claim=(
                        "Fixture Reddit discussion reports recurring owner "
                        "setup concerns."
                    ),
                    confidence=_confidence(0.6),
                    source_quality=SourceQuality(
                        level=SourceQualityLevel.MIXED,
                        score=0.6,
                    ),
                    context_source_ids=(source_id,),
                    recurring_signal=True,
                    evidence_quality_warnings=(
                        "Community evidence is qualitative and anecdotal.",
                    ),
                ),
            ),
            evidence_gaps=(
                SourceEvidenceGap(
                    capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.PRODUCT,
                        product_id=product_id,
                    ),
                    source_id=source_id,
                    summary="Fixture mode does not fetch private or full Reddit text.",
                ),
            ),
        )


@dataclass(frozen=True)
class FakeAmazonProductIntelligenceAgent:
    output: AmazonProductEvidenceBundle | None = None

    async def run(
        self,
        input_data: AmazonProductIntelligenceAgentInput,
    ) -> AmazonProductEvidenceBundle:
        if self.output is not None:
            return self.output
        source_id = new_id()
        product_id = (
            input_data.products[0].product_id if input_data.products else new_id()
        )
        listing_id = (
            input_data.listings[0].listing_id if input_data.listings else new_id()
        )
        region_code = _target_region_code(input_data.target_region_code, input_data)
        listing_url = AnyHttpUrl("https://www.amazon.com/dp/B012345678")
        context = AmazonListingContext(
            source_id=source_id,
            marketplace_name="Amazon",
            marketplace_domain="amazon.com",
            marketplace_country_code=region_code,
            listing_url=listing_url,
            asin="B012345678",
            product_title="Fixture product listing",
            seller_name="Fixture Marketplace Seller",
            fulfillment="Fulfilled by Amazon",
            ships_to_region_code=region_code,
            ships_to_region=True,
            review_count=128,
            average_rating=4.2,
        )
        return AmazonProductEvidenceBundle(
            source_references=(
                SourceReference(
                    source_id=source_id,
                    url=listing_url,
                    title=context.product_title,
                ),
            ),
            listing_contexts=(context,),
            evidence=(
                AmazonProductEvidence(
                    source_id=source_id,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.PRODUCT,
                        product_id=product_id,
                    ),
                    fact_type=AmazonEvidenceFactType.PRODUCT_PAGE_FACT,
                    claim="Fixture Amazon page provides product-page facts.",
                    confidence=_confidence(0.7),
                    source_quality=SourceQuality(
                        level=SourceQualityLevel.ADEQUATE,
                        score=0.7,
                    ),
                    listing_context_source_id=source_id,
                ),
                AmazonProductEvidence(
                    source_id=source_id,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.LISTING,
                        listing_id=listing_id,
                    ),
                    fact_type=AmazonEvidenceFactType.LISTING_IDENTITY,
                    claim="Fixture Amazon listing identity preserves ASIN B012345678.",
                    confidence=_confidence(0.75),
                    source_quality=SourceQuality(
                        level=SourceQualityLevel.ADEQUATE,
                        score=0.7,
                    ),
                    listing_context_source_id=source_id,
                ),
                AmazonProductEvidence(
                    source_id=source_id,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.SELLER,
                        listing_id=listing_id,
                    ),
                    fact_type=AmazonEvidenceFactType.SELLER_FULFILLMENT,
                    claim="Fixture seller and fulfillment are represented separately.",
                    confidence=_confidence(0.65),
                    source_quality=SourceQuality(
                        level=SourceQualityLevel.MIXED,
                        score=0.6,
                    ),
                    listing_context_source_id=source_id,
                ),
                AmazonProductEvidence(
                    source_id=source_id,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.REVIEW,
                        review_id="fixture-review-summary",
                    ),
                    fact_type=AmazonEvidenceFactType.REVIEW_SUMMARY,
                    claim="Fixture Amazon review summary is source-specific evidence.",
                    confidence=_confidence(0.6),
                    source_quality=SourceQuality(
                        level=SourceQualityLevel.MIXED,
                        score=0.6,
                    ),
                    listing_context_source_id=source_id,
                ),
                AmazonProductEvidence(
                    source_id=source_id,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.REGION,
                        region_code=region_code,
                    ),
                    fact_type=AmazonEvidenceFactType.REGIONAL_AVAILABILITY,
                    claim=(
                        "Fixture Amazon listing includes regional ship-to evidence."
                    ),
                    confidence=_confidence(0.65),
                    source_quality=SourceQuality(
                        level=SourceQualityLevel.ADEQUATE,
                        score=0.7,
                    ),
                    listing_context_source_id=source_id,
                ),
            ),
            evidence_gaps=(
                SourceEvidenceGap(
                    capability=(
                        SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW
                    ),
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.REVIEW,
                        review_id="fixture-review-summary",
                    ),
                    source_id=source_id,
                    summary="Fixture mode does not retrieve individual Amazon reviews.",
                ),
            ),
        )


@dataclass(frozen=True)
class FakeIKEAStoreIntelligenceAgent:
    output: IKEAStoreEvidenceBundle | None = None

    async def run(
        self,
        input_data: IKEAStoreIntelligenceAgentInput,
    ) -> IKEAStoreEvidenceBundle:
        if self.output is not None:
            return self.output
        source_id = new_id()
        product_id = (
            input_data.products[0].product_id if input_data.products else new_id()
        )
        region_code = _target_region_code(input_data.target_region_code, input_data)
        official_url = AnyHttpUrl(
            "https://www.ikea.com/us/en/p/fixture-product-12345678/"
        )
        context = IKEAStoreContext(
            source_id=source_id,
            country_code=region_code,
            official_url=official_url,
            product_code="12345678",
            product_name="Fixture IKEA product",
            store_name=f"IKEA {region_code}",
            delivery_area=f"{region_code} online delivery",
            availability=RegionalStoreAvailability.UNKNOWN,
        )
        return IKEAStoreEvidenceBundle(
            source_references=(
                SourceReference(
                    source_id=source_id,
                    url=official_url,
                    title=context.product_name,
                ),
            ),
            store_contexts=(context,),
            evidence=(
                IKEAStoreEvidence(
                    source_id=source_id,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.PRODUCT,
                        product_id=product_id,
                    ),
                    fact_type=IKEAEvidenceFactType.OFFICIAL_PRODUCT_FACT,
                    claim="Fixture IKEA page preserves official product context.",
                    confidence=_confidence(0.7),
                    source_quality=SourceQuality(
                        level=SourceQualityLevel.STRONG,
                        score=0.85,
                    ),
                    store_context_source_id=source_id,
                ),
                IKEAStoreEvidence(
                    source_id=source_id,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.REGION,
                        region_code=region_code,
                    ),
                    fact_type=IKEAEvidenceFactType.STORE_DELIVERY_CONTEXT,
                    claim="Fixture IKEA evidence is scoped to a country or region.",
                    confidence=_confidence(0.65),
                    source_quality=SourceQuality(
                        level=SourceQualityLevel.ADEQUATE,
                        score=0.7,
                    ),
                    store_context_source_id=source_id,
                ),
            ),
            evidence_gaps=(
                SourceEvidenceGap(
                    capability=SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.REGION,
                        region_code=region_code,
                    ),
                    source_id=source_id,
                    summary=(
                        "Fixture mode does not assert live IKEA regional inventory."
                    ),
                ),
            ),
        )


@dataclass(frozen=True)
class FakeComparisonDecisionAgent:
    output: RecommendationBundle | None = None

    async def run(
        self,
        input_data: ComparisonDecisionAgentInput,
    ) -> RecommendationBundle:
        if self.output is not None:
            return self.output
        product = input_data.products[0]
        listing = input_data.listings[0] if input_data.listings else None
        evidence_ids = tuple(item.evidence_id for item in input_data.evidence) or (
            new_id(),
        )
        matrix = ComparisonMatrix(
            criteria=(ComparisonCriterion(name="fit", weight=1.0),),
            rows=(
                ComparisonRow(
                    product_id=product.product_id,
                    listing_id=listing.listing_id if listing else None,
                    scores={"fit": 0.8},
                    evidence_ids=evidence_ids,
                    summary="Fixture comparison row.",
                ),
            ),
        )
        recommendation = RecommendationBundle(
            final_product_id=product.product_id,
            final_listing_id=listing.listing_id if listing else None,
            final_rationale="Fixture recommendation.",
            mode_results=(
                RecommendationModeResult(
                    mode=RecommendationMode.BEST_OVERALL,
                    product_id=product.product_id,
                    listing_id=listing.listing_id if listing else None,
                    title="Fixture best overall",
                    rationale="Fixture mode selected the first product.",
                    confidence=_confidence(),
                    evidence_ids=evidence_ids,
                ),
            ),
            comparison_matrix=matrix,
            evidence_ids=evidence_ids,
        )
        return integrate_trust_analysis_into_recommendation(
            recommendation,
            input_data.trust_assessments,
        )


@dataclass(frozen=True)
class FakeVerifierCriticAgent:
    output: VerificationReport | None = None

    async def run(self, input_data: VerificationAgentInput) -> VerificationReport:
        if self.output is not None:
            return self.output
        return VerificationReport(
            approved=True,
            recommendation_bundle=input_data.recommendation_bundle,
            notes=("Fixture verification approved.",),
        )


def _guardrail_for_user_input(user_input: str) -> ShoppingGuardrailResult:
    normalized = user_input.lower()
    if any(term in normalized for term in ("homework", "write an essay", "poem")):
        return _blocked_guardrail(
            ShoppingGuardrailReason.OFF_TOPIC,
            "I can help with shopping decisions. Try asking what to buy or compare.",
        )
    if any(term in normalized for term in ("gun", "explosive", "weapon")):
        return _blocked_guardrail(
            ShoppingGuardrailReason.UNSAFE_PRODUCT,
            "I cannot help choose unsafe products. I can help with ordinary consumer purchases.",
        )
    if any(term in normalized for term in ("fake passport", "stolen", "illegal")):
        return _blocked_guardrail(
            ShoppingGuardrailReason.ILLEGAL_PRODUCT,
            "I cannot help with illegal purchases. I can help with ordinary consumer products.",
        )
    if any(term in normalized for term in ("porn", "explicit sexual")):
        return _blocked_guardrail(
            ShoppingGuardrailReason.INAPPROPRIATE_PRODUCT,
            "I cannot help with that request. I can help with ordinary consumer purchases.",
        )
    return ShoppingGuardrailResult(decision=ShoppingGuardrailDecision.ALLOWED)


def _blocked_guardrail(
    reason: ShoppingGuardrailReason,
    message: str,
) -> ShoppingGuardrailResult:
    return ShoppingGuardrailResult(
        decision=ShoppingGuardrailDecision.BLOCKED,
        reason=reason,
        message=message,
    )


def _first_followup_question_id(user_input: str) -> str:
    normalized = user_input.lower()
    if "monitor" in normalized:
        return MONITOR_CONNECTION_QUESTION_ID
    if " between " in f" {normalized} " or " vs " in normalized:
        return COMPARISON_PRIORITY_QUESTION_ID
    return BUDGET_QUESTION_ID


def _guided_question_by_id(question_id: str, user_input: str) -> CurrentGuidedQuestion:
    if question_id == FIRST_QUESTION_ID:
        return CurrentGuidedQuestion(
            question_id=FIRST_QUESTION_ID,
            text="Send your question",
            purpose=GuidedQuestionPurpose.FIRST_QUESTION,
            capture_targets=(GuidedCaptureTarget.SHOPPING_QUESTION,),
        )
    if question_id == MONITOR_CONNECTION_QUESTION_ID:
        return CurrentGuidedQuestion(
            question_id=MONITOR_CONNECTION_QUESTION_ID,
            text="Would one-cable setup be useful for this monitor?",
            purpose=GuidedQuestionPurpose.PRIORITIES,
            answer_surface=GuidedAnswerSurface.INLINE_CHOICE,
            capture_targets=(GuidedCaptureTarget.PRIORITIES,),
            inline_choice=InlineChoiceControl(
                control_id="monitor-connection-choice",
                control_type=InlineChoiceControlType.YES_NO,
                options=(
                    InlineChoiceOption(choice_id="yes", label="Yes"),
                    InlineChoiceOption(choice_id="no", label="No"),
                ),
            ),
        )
    if question_id == COMPARISON_PRIORITY_QUESTION_ID:
        return CurrentGuidedQuestion(
            question_id=COMPARISON_PRIORITY_QUESTION_ID,
            text="For that comparison, what should matter most?",
            purpose=GuidedQuestionPurpose.PRIORITIES,
            answer_surface=GuidedAnswerSurface.INLINE_CHOICE,
            capture_targets=(GuidedCaptureTarget.PRIORITIES,),
            inline_choice=InlineChoiceControl(
                control_id="comparison-priority-choice",
                control_type=InlineChoiceControlType.TWO_OPTION_PLUS_TYPE_ANSWER,
                options=(
                    InlineChoiceOption(choice_id="everyday-use", label="Everyday use"),
                    InlineChoiceOption(choice_id="best-value", label="Best value"),
                ),
                custom_answer_label="Type my answer",
            ),
        )
    if question_id == BUDGET_QUESTION_ID:
        return CurrentGuidedQuestion(
            question_id=BUDGET_QUESTION_ID,
            text="What budget should we stay near?",
            purpose=GuidedQuestionPurpose.BUDGET,
            capture_targets=(GuidedCaptureTarget.BUDGET,),
        )
    return CurrentGuidedQuestion(
        question_id=CONSIDERED_PRODUCTS_QUESTION_ID,
        text="Are there any products you want CartCart to check?",
        purpose=GuidedQuestionPurpose.CONSIDERED_PRODUCTS,
        capture_targets=(
            GuidedCaptureTarget.CONSIDERED_PRODUCT_NAMES,
            GuidedCaptureTarget.CONSIDERED_PRODUCT_DESCRIPTIONS,
        ),
    )


def _ready_guided_state(
    input_data: ShoppingGuideAgentInput,
    answer_map: dict[str, GuidedAnswer],
) -> GuidedIntakeState:
    return GuidedIntakeState(
        status=GuidedIntakeStatus.READY_FOR_ANALYSIS,
        navigation=_navigation_state(answer_map, input_data.reanswer_question_id),
        analysis_start=AnalysisStartAvailability(
            enough_information=True,
            message="We have enough to start checking options.",
        ),
        region_setup=_region_setup_state(input_data.region_setup),
        progress=ProgressDisplayStatus(
            kind=ProgressDisplayKind.CHECKING_OPTIONS,
            message="Ready to start checking options.",
        ),
        ready_brief=_brief_for_guide(input_data, answer_map),
    )


def _navigation_state(
    answer_map: dict[str, GuidedAnswer],
    reanswer_question_id: str | None,
) -> PriorQuestionNavigationState:
    ordered_question_ids = (
        MONITOR_CONNECTION_QUESTION_ID,
        COMPARISON_PRIORITY_QUESTION_ID,
        BUDGET_QUESTION_ID,
        CONSIDERED_PRODUCTS_QUESTION_ID,
    )
    questions = tuple(
        ReanswerableQuestion(
            question_id=question_id,
            label=_reanswer_label(question_id),
        )
        for question_id in ordered_question_ids
        if question_id in answer_map
    )
    return PriorQuestionNavigationState(
        can_go_back=bool(questions),
        current_reanswer_question_id=reanswer_question_id,
        reanswerable_questions=questions,
    )


def _region_setup_state(
    submission: RegionSetupSubmission | None,
) -> LocalRegionSetupState:
    if submission is None:
        return LocalRegionSetupState(
            status=RegionSetupStatus.NEEDS_ANSWER,
            prompt_text=(
                "Where are you buying from? "
                "It helps show options you can actually buy."
            ),
            resumes_pending_question=True,
        )
    if submission.status == RegionSetupStatus.PROVIDED:
        return LocalRegionSetupState(
            status=RegionSetupStatus.PROVIDED,
            region=submission.region,
            resumes_pending_question=True,
        )
    return LocalRegionSetupState(
        status=RegionSetupStatus.REFUSED,
        resumes_pending_question=True,
    )


def _brief_for_guide(
    input_data: ShoppingGuideAgentInput,
    answer_map: dict[str, GuidedAnswer],
) -> ShoppingBrief:
    answer_texts = tuple(
        text for text in (_answer_text(answer) for answer in answer_map.values()) if text
    )
    constraints = tuple(
        PreferenceConstraint(text=text, mode=PreferenceMode.HARD)
        for text in answer_texts
        if _looks_like_constraint(text)
    )
    preferences = tuple(
        PreferenceConstraint(text=text, mode=PreferenceMode.SOFT)
        for text in answer_texts
        if not _looks_like_constraint(text)
    )
    return ShoppingBrief(
        original_query=input_data.user_input,
        region=_region_preference_from_setup(input_data.region_setup),
        budget=_budget_from_texts(answer_texts),
        constraints=constraints,
        preferences=preferences,
        **_category_fields(input_data.user_input),
    )


def _region_preference_from_setup(
    submission: RegionSetupSubmission | None,
) -> RegionPreference | None:
    if submission is None or submission.status != RegionSetupStatus.PROVIDED:
        return None
    if submission.region is None:
        return None
    return RegionPreference(region=submission.region, source=FieldSource.USER_PROVIDED)


def _category_fields(user_input: str) -> dict[str, str]:
    normalized = user_input.lower()
    categories = {
        "laptop": "laptop",
        "phone": "smartphone",
        "iphone": "smartphone",
        "samsung": "smartphone",
        "camera": "camera",
        "desk": "desk",
        "monitor": "monitor",
        "headphone": "headphones",
        "earbud": "earbuds",
    }
    for keyword, category in categories.items():
        if keyword in normalized:
            return {"category": category, "category_source": FieldSource.INFERRED}
    return {}


def _answer_text(answer: GuidedAnswer | None) -> str | None:
    if answer is None:
        return None
    if isinstance(answer, NaturalLanguageGuidedAnswer | ChoiceWithTextGuidedAnswer):
        return answer.text
    if isinstance(answer, YesNoGuidedAnswer):
        return "Yes" if answer.value else "No"
    if isinstance(answer, ChoiceGuidedAnswer):
        return answer.choice_id.replace("-", " ")
    return None


def _budget_from_texts(texts: tuple[str, ...]) -> BudgetConstraint | None:
    for text in texts:
        match = re.search(
            r"(?:\$|usd\s*)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
            text,
            re.I,
        )
        if match is None:
            continue
        return BudgetConstraint(
            amount=Money(amount=Decimal(match.group(1).replace(",", "")), currency="USD"),
            mode=BudgetMode.PREFERRED,
        )
    return None


def _looks_like_constraint(text: str) -> bool:
    normalized = text.lower()
    return any(term in normalized for term in ("must", "need", "needs", "cannot"))


def _reanswer_label(question_id: str) -> str:
    labels = {
        MONITOR_CONNECTION_QUESTION_ID: "Monitor setup",
        COMPARISON_PRIORITY_QUESTION_ID: "Comparison priority",
        BUDGET_QUESTION_ID: "Budget",
        CONSIDERED_PRODUCTS_QUESTION_ID: "Products to check",
    }
    return labels.get(question_id, "Earlier answer")


def _search_result(query: SearchQuery) -> SearchResult:
    return SearchResult(
        query=query,
        url=AnyHttpUrl("https://example.com/reviews/fixture-monitor-27"),
        title="Fixture Monitor 27 Review",
        snippet="Fixture search result.",
        source_type=SourceType.PROFESSIONAL_REVIEW,
        provider=ProviderMetadata(provider_name="fixture"),
        quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.7),
    )


def _source_snapshot() -> SourceSnapshot:
    return SourceSnapshot(
        url=AnyHttpUrl("https://example.com/reviews/fixture-monitor-27"),
        source_type=SourceType.PROFESSIONAL_REVIEW,
        provider=ProviderMetadata(provider_name="fixture"),
        title="Fixture Monitor 27 Review",
        extraction_status=ExtractionStatus.SUCCEEDED,
        quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.7),
    )


def _source_metadata_evidence(snapshot: SourceSnapshot) -> SourceEvidence:
    return SourceEvidence(
        source_id=snapshot.source_id,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.SOURCE_METADATA,
            source_id=snapshot.source_id,
        ),
        evidence_type=EvidenceType.OTHER,
        claim="Fixture source was available for review.",
        confidence=_confidence(),
        source_quality=snapshot.quality,
    )


def _category_analysis(
    input_data: ProductAnalysisAgentInput,
    category: str,
) -> CategoryAnalysis:
    evidence_ids = tuple(item.evidence_id for item in input_data.evidence) or (
        new_id(),
    )
    return CategoryAnalysis(
        product_id=input_data.product.product_id,
        listing_ids=tuple(listing.listing_id for listing in input_data.listings),
        category=category,
        fit_summary=f"Fixture {category} analysis.",
        strengths=("Fixture strength.",),
        confidence=_confidence(),
        evidence_ids=evidence_ids,
        source_ids=input_data.product.source_ids,
    )


def _confidence(score: float = 0.8) -> Confidence:
    level = ConfidenceLevel.HIGH if score >= 0.75 else ConfidenceLevel.MEDIUM
    return Confidence(score=score, level=level, rationale="Fixture confidence.")


def _target_region_code(
    explicit_region_code: str | None,
    input_data: SourceIntelligenceAgentInput,
) -> str:
    if explicit_region_code is not None:
        return explicit_region_code
    if input_data.brief.region is not None:
        return input_data.brief.region.region.country_code
    return "US"
