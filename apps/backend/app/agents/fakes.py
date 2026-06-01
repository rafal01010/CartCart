from dataclasses import dataclass

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
    ListingTrustLevel,
    RecommendationBundle,
    RecommendationMode,
    RecommendationModeResult,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import new_id
from app.schemas.intake import FieldSource, ShoppingBrief
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
        evidence_ids = tuple(item.evidence_id for item in input_data.evidence) or (
            new_id(),
        )
        return ListingTrustAssessment(
            listing_id=input_data.listing.listing_id,
            level=ListingTrustLevel.REASONABLE,
            confidence=_confidence(),
            summary="Fixture seller trust assessment.",
            positive_signals=("Seller identity is present in fixture data.",),
            evidence_ids=evidence_ids,
            source_ids=input_data.listing.source_ids,
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
        return RecommendationBundle(
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
