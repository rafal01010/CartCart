from dataclasses import dataclass
from decimal import Decimal

from pydantic import AnyHttpUrl, Field

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
    RejectedItem,
    RejectionReason,
    RejectionSeverity,
)
from app.schemas.base import VersionedSchema
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import (
    CandidateId,
    ListingId,
    ProductId,
    RunId,
    SessionId,
    SourceId,
    new_id,
)
from app.schemas.money import Money
from app.schemas.products import (
    CanonicalProduct,
    ListingAvailabilityStatus,
    ProductListing,
    RegionAvailability,
    SellerProfile,
    SellerTrustSignal,
    UserAddedProduct,
)
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceType,
    ExtractionStatus,
    ProviderMetadata,
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


@dataclass(frozen=True)
class FixtureShortlistItem:
    candidate_id: CandidateId
    product_id: ProductId
    listing_id: ListingId | None
    position: int


class MonitorFixtureRunOutput(VersionedSchema):
    search_plan: SearchPlan
    search_results: tuple[SearchResult, ...] = Field(min_length=1)
    source_snapshots: tuple[SourceSnapshot, ...] = Field(min_length=1)
    source_evidence: tuple[SourceEvidence, ...] = Field(min_length=1)
    products: tuple[CanonicalProduct, ...] = Field(min_length=1)
    listings: tuple[ProductListing, ...] = Field(min_length=1)
    shortlist_items: tuple[FixtureShortlistItem, ...] = Field(min_length=1)
    user_added_products: tuple[UserAddedProduct, ...] = Field(default_factory=tuple)
    deduplication_decisions: tuple[DeduplicationDecision, ...] = Field(
        default_factory=tuple
    )
    trust_assessments: tuple[ListingTrustAssessment, ...] = Field(default_factory=tuple)
    category_analyses: tuple[CategoryAnalysis, ...] = Field(default_factory=tuple)
    recommendation_bundle: RecommendationBundle


def build_monitor_fixture_run_output(
    *,
    run_id: RunId,
    session_id: SessionId,
) -> MonitorFixtureRunOutput:
    del run_id, session_id
    quality = SourceQuality(
        level=SourceQualityLevel.STRONG,
        score=0.86,
        rationale="Fixture source has product-specific monitor evidence.",
    )
    query = SearchQuery(
        query="best 27 inch USB-C monitor under 500 reviews",
        intent=SearchIntent.REVIEW,
        region_code="US",
        required_source_types=(
            SourceType.PROFESSIONAL_REVIEW,
            SourceType.OFFICIAL_BRAND_PAGE,
            SourceType.RETAILER_LISTING,
        ),
    )
    search_plan = SearchPlan(
        queries=(query,),
        rationale=(
            "Fixture plan checks monitor reviews, official pages, pricing, "
            "and listing trust."
        ),
    )
    snapshots = (
        _snapshot(
            "fixture-rtings-u2724de",
            "https://example.com/reviews/dell-u2724de",
            "RTINGS-style Dell U2724DE review",
            SourceType.PROFESSIONAL_REVIEW,
            quality,
        ),
        _snapshot(
            "fixture-dell-official-u2724de",
            "https://example.com/dell/u2724de",
            "Dell U2724DE official store",
            SourceType.OFFICIAL_BRAND_PAGE,
            quality,
        ),
        _snapshot(
            "fixture-market-u2724de",
            "https://example.com/market/too-cheap-u2724de",
            "Marketplace Dell U2724DE deal",
            SourceType.RETAILER_LISTING,
            SourceQuality(
                level=SourceQualityLevel.WEAK,
                score=0.28,
                rationale="Fixture marketplace source has weak seller signals.",
            ),
        ),
        _snapshot(
            "fixture-asus-pa278cv",
            "https://example.com/asus/pa278cv",
            "ASUS ProArt PA278CV official page",
            SourceType.OFFICIAL_BRAND_PAGE,
            quality,
        ),
        _snapshot(
            "fixture-lg-27up850",
            "https://example.com/lg/27up850",
            "LG 27UP850 official page",
            SourceType.OFFICIAL_BRAND_PAGE,
            quality,
        ),
        _snapshot(
            "fixture-flashdealz-viewpro",
            "https://example.com/flashdealz/viewpro-ultracheap-27q",
            "FlashDealz ViewPro UltraCheap 27Q listing",
            SourceType.RETAILER_LISTING,
            SourceQuality(
                level=SourceQualityLevel.WEAK,
                score=0.18,
                rationale="Fixture listing has suspicious price and seller gaps.",
            ),
        ),
    )
    search_results = tuple(
        SearchResult(
            source_id=snapshot.source_id,
            query=query,
            url=snapshot.url,
            title=snapshot.title or "Fixture monitor source",
            snippet="Fixture monitor-shopping source.",
            source_type=snapshot.source_type,
            provider=snapshot.provider,
            quality=snapshot.quality,
        )
        for snapshot in snapshots
    )

    dell = CanonicalProduct(
        name="Dell UltraSharp U2724DE",
        brand="Dell",
        model="U2724DE",
        category="monitor",
        source_ids=(snapshots[0].source_id, snapshots[1].source_id),
    )
    asus = CanonicalProduct(
        name="ASUS ProArt Display PA278CV",
        brand="ASUS",
        model="PA278CV",
        category="monitor",
        source_ids=(snapshots[3].source_id,),
    )
    lg = CanonicalProduct(
        name="LG 27UP850-W",
        brand="LG",
        model="27UP850-W",
        category="monitor",
        source_ids=(snapshots[4].source_id,),
    )
    viewpro = CanonicalProduct(
        name="ViewPro UltraCheap 27Q",
        brand="ViewPro",
        model="UltraCheap 27Q",
        category="monitor",
        source_ids=(snapshots[5].source_id,),
    )
    products = (dell, asus, lg, viewpro)

    dell_official = _listing(
        dell,
        "Dell UltraSharp U2724DE - Official Store",
        snapshots[1].url,
        "Dell Official",
        SellerTrustSignal.STRONG,
        "449.99",
        snapshots[1].source_id,
    )
    dell_marketplace = _listing(
        dell,
        "Dell UltraSharp U2724DE - Open Box Marketplace Deal",
        snapshots[2].url,
        "Too Cheap Displays",
        SellerTrustSignal.SUSPICIOUS,
        "259.00",
        snapshots[2].source_id,
    )
    asus_listing = _listing(
        asus,
        "ASUS ProArt Display PA278CV",
        snapshots[3].url,
        "ASUS Official",
        SellerTrustSignal.STRONG,
        "299.99",
        snapshots[3].source_id,
    )
    lg_listing = _listing(
        lg,
        "LG 27UP850-W USB-C Monitor",
        snapshots[4].url,
        "LG Official",
        SellerTrustSignal.REASONABLE,
        "379.99",
        snapshots[4].source_id,
    )
    viewpro_listing = _listing(
        viewpro,
        "ViewPro UltraCheap 27Q - Limited Warehouse Deal",
        snapshots[5].url,
        "FlashDealz Outlet",
        SellerTrustSignal.SUSPICIOUS,
        "129.00",
        snapshots[5].source_id,
    )
    listings = (
        dell_official,
        dell_marketplace,
        asus_listing,
        lg_listing,
        viewpro_listing,
    )

    evidence = _evidence_bundle(
        quality=quality,
        snapshots=snapshots,
        products=products,
        listings=listings,
    )
    evidence_by_claim = {item.claim: item for item in evidence}

    user_added = UserAddedProduct(
        input_text=(
            "User was considering the ViewPro UltraCheap 27Q because it was much "
            "cheaper than name-brand alternatives."
        ),
        url=viewpro_listing.url,
        product=viewpro,
        listing=viewpro_listing,
        notes="Fixture user-added monitor candidate.",
    )
    shortlist_items = (
        FixtureShortlistItem(new_id(), dell.product_id, dell_official.listing_id, 1),
        FixtureShortlistItem(new_id(), asus.product_id, asus_listing.listing_id, 2),
        FixtureShortlistItem(new_id(), lg.product_id, lg_listing.listing_id, 3),
        FixtureShortlistItem(
            user_added.candidate_id,
            viewpro.product_id,
            viewpro_listing.listing_id,
            4,
        ),
    )

    dedupe = DeduplicationDecision(
        candidate_ids=(new_id(), new_id()),
        outcome=DeduplicationOutcome.DUPLICATE,
        canonical_product_id=dell.product_id,
        confidence=_confidence(0.88),
        rationale=(
            "The official and marketplace listings use the same Dell model number "
            "and refer to the same monitor."
        ),
        evidence_ids=(evidence_by_claim["Dell U2724DE model identity confirmed."].evidence_id,),
        source_ids=(snapshots[1].source_id, snapshots[2].source_id),
    )
    trust_assessments = (
        _trust(
            dell_official,
            ListingTrustLevel.STRONG,
            "Official Dell listing with clear seller identity.",
            positive=("Official brand store.", "Normal pricing."),
            evidence=(evidence_by_claim["Dell official listing has normal pricing."],),
        ),
        _trust(
            dell_marketplace,
            ListingTrustLevel.SUSPICIOUS,
            "Marketplace duplicate has a suspiciously low price and weak seller detail.",
            red_flags=("Large unexplained discount.", "Unknown marketplace seller."),
            evidence=(evidence_by_claim["Marketplace duplicate is unusually cheap."],),
        ),
        _trust(
            viewpro_listing,
            ListingTrustLevel.SUSPICIOUS,
            "User-added listing has weak seller identity and an implausibly low price.",
            red_flags=("Sparse seller details.", "Price is far below comparable monitors."),
            evidence=(evidence_by_claim["User-added ViewPro listing has weak seller signals."],),
        ),
    )
    category_analyses = (
        _analysis(
            dell,
            (dell_official.listing_id, dell_marketplace.listing_id),
            "Best balance of USB-C ergonomics, warranty clarity, and evidence quality.",
            strengths=("USB-C hub support.", "Strong ergonomic stand.", "Clear warranty path."),
            weaknesses=("Not the cheapest option.",),
            evidence=(
                evidence_by_claim["Dell U2724DE has USB-C hub and ergonomic strengths."],
                evidence_by_claim["Dell official listing has normal pricing."],
            ),
        ),
        _analysis(
            asus,
            (asus_listing.listing_id,),
            "Good value runner-up with strong creator-monitor evidence.",
            strengths=("Good value.", "Color-focused ProArt positioning."),
            weaknesses=("Less flexible hub evidence than the Dell fixture pick.",),
            evidence=(evidence_by_claim["ASUS PA278CV is a credible value runner-up."],),
        ),
        _analysis(
            lg,
            (lg_listing.listing_id,),
            "Useful 4K runner-up if resolution matters more than hub features.",
            strengths=("4K resolution.", "Reasonable official-source support."),
            weaknesses=("Costs more than the ASUS value pick.",),
            evidence=(evidence_by_claim["LG 27UP850 is a credible 4K runner-up."],),
        ),
        _analysis(
            viewpro,
            (viewpro_listing.listing_id,),
            "Weak evidence and seller risk make this a poor buy despite the low price.",
            strengths=("Low advertised price.",),
            weaknesses=("Weak seller trust.", "Sparse product evidence."),
            warnings=("Do not treat the low price as equivalent to a safe listing.",),
            evidence=(evidence_by_claim["User-added ViewPro listing has weak seller signals."],),
        ),
    )
    recommendation = _recommendation(
        products=products,
        listings=listings,
        evidence_by_claim=evidence_by_claim,
    )
    return MonitorFixtureRunOutput(
        search_plan=search_plan,
        search_results=search_results,
        source_snapshots=snapshots,
        source_evidence=evidence,
        products=products,
        listings=listings,
        shortlist_items=shortlist_items,
        user_added_products=(user_added,),
        deduplication_decisions=(dedupe,),
        trust_assessments=trust_assessments,
        category_analyses=category_analyses,
        recommendation_bundle=recommendation,
    )


def _snapshot(
    provider_result_id: str,
    url: str,
    title: str,
    source_type: SourceType,
    quality: SourceQuality,
) -> SourceSnapshot:
    return SourceSnapshot(
        url=AnyHttpUrl(url),
        source_type=source_type,
        provider=ProviderMetadata(
            provider_name="fixture",
            provider_result_id=provider_result_id,
        ),
        title=title,
        extraction_status=ExtractionStatus.SUCCEEDED,
        quality=quality,
    )


def _listing(
    product: CanonicalProduct,
    title: str,
    url: AnyHttpUrl,
    seller_name: str,
    trust_signal: SellerTrustSignal,
    price: str,
    source_id: SourceId,
) -> ProductListing:
    return ProductListing(
        product_id=product.product_id,
        title=title,
        url=url,
        seller=SellerProfile(
            seller_name=seller_name,
            seller_url=AnyHttpUrl(str(url)),
            trust_signal=trust_signal,
            trust_confidence=_confidence(
                0.9 if trust_signal == SellerTrustSignal.STRONG else 0.25
            ),
            trust_notes="Fixture seller signal.",
            source_ids=(source_id,),
        ),
        price=Money(amount=Decimal(price), currency="USD"),
        region_availability=(
            RegionAvailability(
                region_code="US",
                status=ListingAvailabilityStatus.AVAILABLE,
                source_ids=(source_id,),
            ),
        ),
        source_ids=(source_id,),
    )


def _evidence_bundle(
    *,
    quality: SourceQuality,
    snapshots: tuple[SourceSnapshot, ...],
    products: tuple[CanonicalProduct, ...],
    listings: tuple[ProductListing, ...],
) -> tuple[SourceEvidence, ...]:
    dell, asus, lg, viewpro = products
    dell_official, dell_marketplace, _asus_listing, _lg_listing, viewpro_listing = (
        listings
    )
    weak_market_quality = snapshots[2].quality
    weak_viewpro_quality = snapshots[5].quality
    return (
        _product_evidence(
            snapshots[0],
            dell,
            EvidenceType.PRODUCT_SPEC,
            "Dell U2724DE has USB-C hub and ergonomic strengths.",
            quality,
            0.88,
        ),
        _product_evidence(
            snapshots[1],
            dell,
            EvidenceType.PRODUCT_SPEC,
            "Dell U2724DE model identity confirmed.",
            quality,
            0.9,
        ),
        _listing_evidence(
            snapshots[1],
            dell_official,
            EvidenceType.PRICE,
            "Dell official listing has normal pricing.",
            quality,
            0.84,
        ),
        _listing_evidence(
            snapshots[2],
            dell_marketplace,
            EvidenceType.SELLER_TRUST,
            "Marketplace duplicate is unusually cheap.",
            weak_market_quality,
            0.76,
        ),
        _product_evidence(
            snapshots[3],
            asus,
            EvidenceType.REVIEW_CLAIM,
            "ASUS PA278CV is a credible value runner-up.",
            quality,
            0.78,
        ),
        _product_evidence(
            snapshots[4],
            lg,
            EvidenceType.REVIEW_CLAIM,
            "LG 27UP850 is a credible 4K runner-up.",
            quality,
            0.77,
        ),
        _listing_evidence(
            snapshots[5],
            viewpro_listing,
            EvidenceType.SELLER_TRUST,
            "User-added ViewPro listing has weak seller signals.",
            weak_viewpro_quality,
            0.82,
        ),
    )


def _product_evidence(
    snapshot: SourceSnapshot,
    product: CanonicalProduct,
    evidence_type: EvidenceType,
    claim: str,
    source_quality: SourceQuality,
    confidence_score: float,
) -> SourceEvidence:
    return SourceEvidence(
        source_id=snapshot.source_id,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.PRODUCT,
            product_id=product.product_id,
        ),
        evidence_type=evidence_type,
        claim=claim,
        confidence=_confidence(confidence_score),
        source_quality=source_quality,
    )


def _listing_evidence(
    snapshot: SourceSnapshot,
    listing: ProductListing,
    evidence_type: EvidenceType,
    claim: str,
    source_quality: SourceQuality,
    confidence_score: float,
) -> SourceEvidence:
    return SourceEvidence(
        source_id=snapshot.source_id,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.LISTING,
            listing_id=listing.listing_id,
        ),
        evidence_type=evidence_type,
        claim=claim,
        confidence=_confidence(confidence_score),
        source_quality=source_quality,
    )


def _trust(
    listing: ProductListing,
    level: ListingTrustLevel,
    summary: str,
    *,
    evidence: tuple[SourceEvidence, ...],
    positive: tuple[str, ...] = (),
    red_flags: tuple[str, ...] = (),
) -> ListingTrustAssessment:
    return ListingTrustAssessment(
        listing_id=listing.listing_id,
        level=level,
        confidence=_confidence(0.85 if level == ListingTrustLevel.STRONG else 0.72),
        summary=summary,
        red_flags=red_flags,
        positive_signals=positive,
        evidence_ids=tuple(item.evidence_id for item in evidence),
        source_ids=tuple(listing.source_ids),
    )


def _analysis(
    product: CanonicalProduct,
    listing_ids: tuple[ListingId, ...],
    fit_summary: str,
    *,
    strengths: tuple[str, ...],
    weaknesses: tuple[str, ...],
    evidence: tuple[SourceEvidence, ...],
    warnings: tuple[str, ...] = (),
) -> CategoryAnalysis:
    return CategoryAnalysis(
        product_id=product.product_id,
        listing_ids=listing_ids,
        category="monitor",
        fit_summary=fit_summary,
        strengths=strengths,
        weaknesses=weaknesses,
        warnings=warnings,
        confidence=_confidence(0.82),
        evidence_ids=tuple(item.evidence_id for item in evidence),
        source_ids=product.source_ids,
    )


def _recommendation(
    *,
    products: tuple[CanonicalProduct, ...],
    listings: tuple[ProductListing, ...],
    evidence_by_claim: dict[str, SourceEvidence],
) -> RecommendationBundle:
    dell, asus, lg, viewpro = products
    dell_official, _dell_marketplace, asus_listing, lg_listing, viewpro_listing = (
        listings
    )
    dell_evidence = evidence_by_claim[
        "Dell U2724DE has USB-C hub and ergonomic strengths."
    ]
    asus_evidence = evidence_by_claim[
        "ASUS PA278CV is a credible value runner-up."
    ]
    lg_evidence = evidence_by_claim["LG 27UP850 is a credible 4K runner-up."]
    viewpro_evidence = evidence_by_claim[
        "User-added ViewPro listing has weak seller signals."
    ]
    matrix = ComparisonMatrix(
        criteria=(
            ComparisonCriterion(name="fit", weight=0.4),
            ComparisonCriterion(name="value", weight=0.25),
            ComparisonCriterion(name="seller_trust", weight=0.35),
        ),
        rows=(
            ComparisonRow(
                product_id=dell.product_id,
                listing_id=dell_official.listing_id,
                scores={"fit": 0.9, "value": 0.78, "seller_trust": 0.95},
                evidence_ids=(dell_evidence.evidence_id,),
                summary="Best overall monitor fixture pick.",
            ),
            ComparisonRow(
                product_id=asus.product_id,
                listing_id=asus_listing.listing_id,
                scores={"fit": 0.78, "value": 0.9, "seller_trust": 0.88},
                evidence_ids=(asus_evidence.evidence_id,),
                summary="Best value runner-up.",
            ),
            ComparisonRow(
                product_id=lg.product_id,
                listing_id=lg_listing.listing_id,
                scores={"fit": 0.8, "value": 0.74, "seller_trust": 0.8},
                evidence_ids=(lg_evidence.evidence_id,),
                summary="4K-focused runner-up.",
            ),
            ComparisonRow(
                product_id=viewpro.product_id,
                listing_id=viewpro_listing.listing_id,
                scores={"fit": 0.35, "value": 0.3, "seller_trust": 0.1},
                evidence_ids=(viewpro_evidence.evidence_id,),
                summary="Rejected because seller trust is too weak.",
            ),
        ),
    )
    return RecommendationBundle(
        final_product_id=dell.product_id,
        final_listing_id=dell_official.listing_id,
        final_rationale=(
            "Dell UltraSharp U2724DE is the fixture best pick because it balances "
            "monitor fit, USB-C convenience, evidence quality, and a trustworthy "
            "official listing."
        ),
        runner_up_product_ids=(asus.product_id, lg.product_id),
        mode_results=(
            RecommendationModeResult(
                mode=RecommendationMode.BEST_OVERALL,
                product_id=dell.product_id,
                listing_id=dell_official.listing_id,
                title="Best overall",
                rationale="Best blend of features, evidence, and seller safety.",
                confidence=_confidence(0.84),
                evidence_ids=(dell_evidence.evidence_id,),
                source_ids=dell.source_ids,
            ),
            RecommendationModeResult(
                mode=RecommendationMode.BEST_VALUE,
                product_id=asus.product_id,
                listing_id=asus_listing.listing_id,
                title="Best value",
                rationale="Good monitor fundamentals at a lower fixture price.",
                confidence=_confidence(0.78),
                evidence_ids=(asus_evidence.evidence_id,),
                source_ids=asus.source_ids,
            ),
            RecommendationModeResult(
                mode=RecommendationMode.WITHIN_BUDGET,
                product_id=asus.product_id,
                listing_id=asus_listing.listing_id,
                title="Best within budget",
                rationale="Best fixture option that stays within the stated budget.",
                confidence=_confidence(0.78),
                evidence_ids=(asus_evidence.evidence_id,),
                source_ids=asus.source_ids,
            ),
            RecommendationModeResult(
                mode=RecommendationMode.STRETCH_PICK,
                product_id=lg.product_id,
                listing_id=lg_listing.listing_id,
                title="Stretch upgrade",
                rationale=(
                    "Worth considering only if the budget is flexible and the "
                    "4K resolution tradeoff matters more than staying lower cost."
                ),
                confidence=_confidence(0.76),
                evidence_ids=(lg_evidence.evidence_id,),
                source_ids=lg.source_ids,
            ),
            RecommendationModeResult(
                mode=RecommendationMode.RUNNER_UP,
                product_id=lg.product_id,
                listing_id=lg_listing.listing_id,
                title="4K runner-up",
                rationale="Worth considering when 4K resolution matters most.",
                confidence=_confidence(0.76),
                evidence_ids=(lg_evidence.evidence_id,),
                source_ids=lg.source_ids,
            ),
        ),
        comparison_matrix=matrix,
        rejected_items=(
            RejectedItem(
                product_id=viewpro.product_id,
                listing_id=viewpro_listing.listing_id,
                reason_code=RejectionReason.SUSPICIOUS_LISTING,
                reason=(
                    "Rejected because the user-added listing combines sparse "
                    "product evidence with suspicious seller signals."
                ),
                severity=RejectionSeverity.BLOCKING,
                evidence_ids=(viewpro_evidence.evidence_id,),
                source_ids=viewpro.source_ids,
            ),
        ),
        warnings=(
            "Avoid the suspicious marketplace duplicate even though it names the same Dell model.",
            "Do not buy the user-added ViewPro listing from the fixture seller.",
        ),
        evidence_ids=(
            dell_evidence.evidence_id,
            asus_evidence.evidence_id,
            lg_evidence.evidence_id,
            viewpro_evidence.evidence_id,
        ),
        source_ids=(
            *dell.source_ids,
            *asus.source_ids,
            *lg.source_ids,
            *viewpro.source_ids,
        ),
    )


def _confidence(score: float) -> Confidence:
    level = ConfidenceLevel.HIGH if score >= 0.75 else ConfidenceLevel.MEDIUM
    return Confidence(score=score, level=level, rationale="Monitor fixture confidence.")
