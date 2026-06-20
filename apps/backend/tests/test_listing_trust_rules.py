from app.schemas import (
    ListingTrustLevel,
    ListingTrustSignalKind,
    Money,
    ProductListing,
    RegionAvailability,
    SellerProfile,
    SellerTrustSignal,
    SourceQuality,
    SourceQualityLevel,
    new_id,
)
from app.services.listing_trust import (
    ListingTrustRuleContext,
    PriceComparisonBasis,
    assess_listing_trust,
    compare_price_plausibility,
    price_plausibility_contexts,
)


def make_listing(
    *,
    url: str = "https://store.example/products/acme-widget",
    seller_name: str = "Acme Store",
    seller_trust_signal: SellerTrustSignal = SellerTrustSignal.REASONABLE,
    price: str | None = "199.00",
    region: bool = True,
    source_quality_level: SourceQualityLevel = SourceQualityLevel.ADEQUATE,
    retailer_id: str | None = "SKU-123",
) -> ProductListing:
    source_id = new_id()
    return ProductListing(
        product_id=new_id(),
        title="Acme Widget",
        url=url,
        retailer_id=retailer_id,
        seller=SellerProfile(
            seller_name=seller_name,
            trust_signal=seller_trust_signal,
            source_ids=(source_id,),
        ),
        price=Money(amount=price, currency="USD") if price is not None else None,
        region_availability=(
            (
                RegionAvailability(
                    region_code="US",
                    source_ids=(source_id,),
                ),
            )
            if region
            else ()
        ),
        source_quality=SourceQuality(level=source_quality_level),
        source_ids=(source_id,),
    )


def signal_kinds(assessment) -> set[ListingTrustSignalKind]:
    return {signal.kind for signal in assessment.trust_signals}


def test_trust_rules_mark_strong_official_listing() -> None:
    listing = make_listing(
        url="https://apple.com/shop/product/acme-widget",
        seller_name="Apple",
        seller_trust_signal=SellerTrustSignal.STRONG,
        source_quality_level=SourceQualityLevel.STRONG,
    )

    assessment = assess_listing_trust(
        listing,
        ListingTrustRuleContext(
            review_count=250,
            return_policy_present=True,
            warranty_present=True,
        ),
    )

    assert assessment.level == ListingTrustLevel.STRONG
    assert not assessment.red_flags
    assert ListingTrustSignalKind.ESTABLISHED_RETAILER_SOURCE_TYPE in signal_kinds(
        assessment
    )
    assert ListingTrustSignalKind.RETURN_WARRANTY_CLARITY in signal_kinds(assessment)


def test_trust_rules_mark_reasonable_marketplace_listing_with_clear_seller() -> None:
    listing = make_listing(
        url="https://amazon.com/dp/B012345678",
        seller_name="Acme Authorized Store",
        seller_trust_signal=SellerTrustSignal.REASONABLE,
    )

    assessment = assess_listing_trust(
        listing,
        ListingTrustRuleContext(
            review_count=80,
            return_policy_present=True,
            warranty_present=True,
        ),
    )

    assert assessment.level == ListingTrustLevel.REASONABLE
    assert assessment.positive_signals
    assert ListingTrustSignalKind.REVIEW_COUNT in signal_kinds(assessment)


def test_trust_rules_mark_mixed_listing_with_positive_and_negative_signals() -> None:
    listing = make_listing(
        url="https://walmart.com/ip/acme-widget/123",
        seller_name="Acme Marketplace Partner",
        seller_trust_signal=SellerTrustSignal.MIXED,
        source_quality_level=SourceQualityLevel.MIXED,
    )

    assessment = assess_listing_trust(
        listing,
        ListingTrustRuleContext(
            review_count=2,
            return_policy_present=True,
            warranty_present=None,
        ),
    )

    assert assessment.level == ListingTrustLevel.MIXED
    assert assessment.positive_signals
    assert assessment.red_flags


def test_trust_rules_mark_weak_listing_with_missing_metadata() -> None:
    listing = make_listing(
        url="https://unknown-shop.example/acme-widget",
        seller_name="Acme Seller",
        seller_trust_signal=SellerTrustSignal.WEAK,
        price=None,
        region=False,
        source_quality_level=SourceQualityLevel.UNKNOWN,
        retailer_id=None,
    )

    assessment = assess_listing_trust(
        listing,
        ListingTrustRuleContext(
            review_count=0,
            return_policy_present=False,
            warranty_present=False,
        ),
    )

    assert assessment.level == ListingTrustLevel.WEAK
    assert ListingTrustSignalKind.MISSING_METADATA in signal_kinds(assessment)
    assert assessment.red_flags


def test_trust_rules_mark_suspicious_listing_for_price_and_contradictions() -> None:
    listing = make_listing(
        url="https://amazon.com/dp/B012345678",
        seller_name="Too Cheap Deals",
        seller_trust_signal=SellerTrustSignal.REASONABLE,
    )

    assessment = assess_listing_trust(
        listing,
        ListingTrustRuleContext(
            review_count=35,
            return_policy_present=True,
            warranty_present=True,
            suspicious_price=True,
            contradictory_listing_data=(
                "Seller name differs between page title and checkout panel.",
            ),
        ),
    )

    assert assessment.level == ListingTrustLevel.SUSPICIOUS
    assert ListingTrustSignalKind.SUSPICIOUS_PRICE in signal_kinds(assessment)
    assert ListingTrustSignalKind.CONTRADICTORY_LISTING_DATA in signal_kinds(
        assessment
    )


def test_trust_rules_mark_unknown_when_evidence_is_too_sparse() -> None:
    listing = make_listing(
        url="https://unknown-shop.example/acme-widget",
        seller_name="Unknown Seller",
        seller_trust_signal=SellerTrustSignal.UNKNOWN,
        price=None,
        region=False,
        source_quality_level=SourceQualityLevel.UNKNOWN,
        retailer_id=None,
    )

    assessment = assess_listing_trust(listing)

    assert assessment.level == ListingTrustLevel.UNKNOWN
    assert assessment.confidence.level == "low"
    assert ListingTrustSignalKind.REVIEW_COUNT in signal_kinds(assessment)


def test_price_plausibility_flags_same_product_too_good_to_be_true_outlier() -> None:
    normal_a = make_listing(price="199.00")
    normal_b = make_listing(price="209.00")
    normal_c = make_listing(price="219.00")
    outlier = make_listing(
        seller_name="Too Cheap Deals",
        seller_trust_signal=SellerTrustSignal.REASONABLE,
        price="42.00",
    )

    findings = compare_price_plausibility(((normal_a, normal_b, normal_c, outlier),))
    contexts = price_plausibility_contexts(((normal_a, normal_b, normal_c, outlier),))
    assessment = assess_listing_trust(outlier, contexts[outlier.listing_id])

    assert len(findings) == 1
    assert findings[0].listing_id == outlier.listing_id
    assert findings[0].basis == PriceComparisonBasis.CANONICAL_GROUP
    assert assessment.level == ListingTrustLevel.SUSPICIOUS
    assert ListingTrustSignalKind.SUSPICIOUS_PRICE in signal_kinds(assessment)
    assert "too low to treat as a normal discount" in assessment.red_flags[0]


def test_price_plausibility_does_not_penalize_ordinary_discounts() -> None:
    listings = (
        make_listing(price="149.00"),
        make_listing(price="199.00"),
        make_listing(price="209.00"),
        make_listing(price="219.00"),
    )

    assert compare_price_plausibility((listings,)) == ()
    assert price_plausibility_contexts((listings,)) == {}


def test_price_plausibility_uses_category_fallback_conservatively() -> None:
    isolated_outlier = make_listing(
        seller_name="Deal Booth",
        seller_trust_signal=SellerTrustSignal.REASONABLE,
        price="49.00",
    )
    category_groups = (
        (isolated_outlier,),
        (make_listing(price="179.00"),),
        (make_listing(price="189.00"),),
        (make_listing(price="199.00"),),
        (make_listing(price="209.00"),),
    )

    findings = compare_price_plausibility(category_groups)

    assert len(findings) == 1
    assert findings[0].listing_id == isolated_outlier.listing_id
    assert findings[0].basis == PriceComparisonBasis.CATEGORY


def test_price_plausibility_keeps_trusted_retailer_discount_below_suspicious_line() -> None:
    sale_listing = make_listing(
        url="https://apple.com/shop/product/acme-widget",
        seller_name="Apple",
        seller_trust_signal=SellerTrustSignal.STRONG,
        price="99.00",
        source_quality_level=SourceQualityLevel.STRONG,
    )
    listings = (
        sale_listing,
        make_listing(price="249.00"),
        make_listing(price="259.00"),
        make_listing(price="269.00"),
    )

    assert compare_price_plausibility((listings,)) == ()
