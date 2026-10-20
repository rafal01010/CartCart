from decimal import Decimal

import pytest

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
    currency: str = "USD",
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
        price=Money(amount=price, currency=currency) if price is not None else None,
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


@pytest.mark.parametrize(
    ("policies_present", "expected_level"),
    ((None, ListingTrustLevel.REASONABLE), (True, ListingTrustLevel.STRONG)),
)
def test_trust_rules_assess_marketplace_listing_from_supplied_context(
    policies_present: bool | None, expected_level: ListingTrustLevel
) -> None:
    listing = make_listing(
        url="https://amazon.com/dp/B012345678",
        seller_name="Acme Authorized Store",
        seller_trust_signal=SellerTrustSignal.REASONABLE,
    )

    assessment = assess_listing_trust(
        listing,
        ListingTrustRuleContext(
            review_count=80,
            return_policy_present=policies_present,
            warranty_present=policies_present,
        ),
    )

    assert assessment.level == expected_level
    assert assessment.positive_signals
    assert ListingTrustSignalKind.REVIEW_COUNT in signal_kinds(assessment)


def test_trust_rules_assess_positive_and_negative_signals_as_advisory_context() -> None:
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

    assert assessment.level == ListingTrustLevel.REASONABLE
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
    assert ListingTrustSignalKind.CONTRADICTORY_LISTING_DATA in signal_kinds(assessment)


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


def test_price_plausibility_keeps_adequate_same_product_evidence_authoritative() -> (
    None
):
    product_id = new_id()
    listings = tuple(
        make_listing(
            price=price,
            url="https://www.bestbuy.com/site/acme-monitor/1234.p",
            seller_name="Best Buy",
            seller_trust_signal=SellerTrustSignal.STRONG,
            source_quality_level=SourceQualityLevel.STRONG,
        ).model_copy(update={"product_id": product_id})
        for price in ("100.00", "105.00", "110.00")
    )
    expensive_groups = tuple(
        (make_listing(price=price),)
        for price in ("1000.00", "1100.00", "1200.00", "1300.00")
    )

    for groups in ((listings,), (listings, *expensive_groups)):
        findings = compare_price_plausibility(groups)
        contexts = price_plausibility_contexts(groups)
        assessments = tuple(
            assess_listing_trust(listing, contexts.get(listing.listing_id))
            for listing in listings
        )

        assert findings == ()
        assert contexts == {}
        assert tuple(item.level for item in assessments) == (
            ListingTrustLevel.STRONG,
            ListingTrustLevel.STRONG,
            ListingTrustLevel.STRONG,
        )

    outlier = make_listing(price="10.00").model_copy(update={"product_id": product_id})
    groups_with_outlier = ((*listings, outlier), *expensive_groups)
    findings = compare_price_plausibility(groups_with_outlier)
    contexts = price_plausibility_contexts(groups_with_outlier)

    assert len(findings) == 1
    assert findings[0].listing_id == outlier.listing_id
    assert findings[0].basis == PriceComparisonBasis.CANONICAL_GROUP
    assert findings[0].reference_median == Decimal("105.00")
    assert findings[0].comparable_listing_count == 3
    assert (
        assess_listing_trust(outlier, contexts[outlier.listing_id]).level
        == ListingTrustLevel.SUSPICIOUS
    )
    assert tuple(
        assess_listing_trust(listing, contexts.get(listing.listing_id)).level
        for listing in listings
    ) == (
        ListingTrustLevel.STRONG,
        ListingTrustLevel.STRONG,
        ListingTrustLevel.STRONG,
    )


@pytest.mark.parametrize(
    ("unusable_price", "unusable_currency"),
    ((None, "USD"), ("0.00", "USD"), ("20000.00", "GBP")),
)
def test_price_plausibility_falls_back_for_insufficient_usable_canonical_peers(
    unusable_price: str | None, unusable_currency: str
) -> None:
    outlier = make_listing(price="20.00")
    product_id = outlier.product_id
    peer = make_listing(price="200.00").model_copy(update={"product_id": product_id})
    unusable_peer = make_listing(
        price=unusable_price, currency=unusable_currency
    ).model_copy(update={"product_id": product_id})
    category_groups = (
        (outlier, peer, unusable_peer),
        (make_listing(price="210.00"),),
        (make_listing(price="220.00"),),
        (make_listing(price="230.00"),),
    )

    findings = compare_price_plausibility(category_groups)
    contexts = price_plausibility_contexts(category_groups)
    outlier_finding = next(
        finding for finding in findings if finding.listing_id == outlier.listing_id
    )

    assert outlier_finding.basis == PriceComparisonBasis.CATEGORY
    assert outlier_finding.currency == "USD"
    assert outlier_finding.reference_median == Decimal("215.00")
    assert outlier_finding.comparable_listing_count == 4
    assert (
        assess_listing_trust(outlier, contexts[outlier.listing_id]).level
        == ListingTrustLevel.SUSPICIOUS
    )
    assert (
        assess_listing_trust(peer, contexts.get(peer.listing_id)).level
        == ListingTrustLevel.REASONABLE
    )


def test_price_plausibility_requires_same_currency_category_peers() -> None:
    cheap_usd = make_listing(price="20.00")
    foreign_peers = tuple(
        make_listing(price=price, currency="GBP").model_copy(
            update={"product_id": cheap_usd.product_id}
        )
        for price in ("200.00", "210.00")
    )
    groups = (
        (cheap_usd, *foreign_peers),
        (make_listing(price="199.00"),),
        (make_listing(price="209.00"),),
        (make_listing(price="219.00"),),
    )
    assert compare_price_plausibility(groups) == ()
    assert assess_listing_trust(cheap_usd).level == ListingTrustLevel.REASONABLE

    sufficient_groups = (*groups, (make_listing(price="229.00"),))
    findings = compare_price_plausibility(sufficient_groups)
    contexts = price_plausibility_contexts(sufficient_groups)

    assert len(findings) == 1
    assert findings[0].listing_id == cheap_usd.listing_id
    assert findings[0].basis == PriceComparisonBasis.CATEGORY
    assert findings[0].reference_median == Decimal("214.00")
    assert findings[0].comparable_listing_count == 4
    assert (
        assess_listing_trust(cheap_usd, contexts[cheap_usd.listing_id]).level
        == ListingTrustLevel.SUSPICIOUS
    )


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
    contexts = price_plausibility_contexts(category_groups)
    assert (
        assess_listing_trust(
            isolated_outlier, contexts[isolated_outlier.listing_id]
        ).level
        == ListingTrustLevel.SUSPICIOUS
    )


def test_price_plausibility_keeps_trusted_retailer_discount_below_suspicious_line() -> (
    None
):
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

    expensive_groups = tuple(
        (make_listing(price=price),)
        for price in ("1000.00", "1100.00", "1200.00", "1300.00")
    )
    for groups in ((listings,), (listings, *expensive_groups)):
        assert compare_price_plausibility(groups) == ()
        contexts = price_plausibility_contexts(groups)
        assert (
            assess_listing_trust(
                sale_listing, contexts.get(sale_listing.listing_id)
            ).level
            == ListingTrustLevel.STRONG
        )


def test_official_store_does_not_require_reviews_or_complete_purchase_details() -> None:
    listing = make_listing(
        url="https://apple.com/shop/product/kettle",
        seller_name="Apple",
        seller_trust_signal=SellerTrustSignal.UNKNOWN,
        price=None,
        region=False,
        retailer_id=None,
    )
    result = assess_listing_trust(listing)
    assert result.level == ListingTrustLevel.REASONABLE
    assert result.red_flags == ()
    assert ListingTrustSignalKind.MISSING_METADATA in signal_kinds(result)


def test_small_review_history_is_positive_context_without_minimum_count() -> None:
    result = assess_listing_trust(
        make_listing(), ListingTrustRuleContext(review_count=2)
    )
    assert "Listing has some review history (2 reviews)." in result.positive_signals
    assert not any("review" in flag for flag in result.red_flags)


def test_price_plausibility_sources_are_not_fabricated_evidence_ids() -> None:
    cheap = make_listing(price="20.00")
    evidence_id = new_id()
    contexts = price_plausibility_contexts(
        ((cheap, make_listing(price="199.00"), make_listing(price="209.00")),),
        {cheap.listing_id: ListingTrustRuleContext(evidence_ids=(evidence_id,))},
    )
    context = contexts[cheap.listing_id]
    assert context.suspicious_price is True
    assert context.evidence_ids == (evidence_id,)
    assert cheap.source_ids[0] in context.source_ids
