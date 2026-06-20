from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.money import Money
from app.schemas.products import (
    CanonicalProduct,
    ListingAvailabilityStatus,
    ProductListing,
    ProductListingExtraction,
    RegionAvailability,
    SellerProfile,
    SellerTrustSignal,
)
from app.schemas.ids import new_id
from app.schemas.search_sources import SourceQuality, SourceQualityLevel
from app.services.product_deduplication import (
    DeterministicMatchKind,
    DeterministicProductDeduplicator,
    FuzzyProductMatchOutcome,
    canonical_listing_url,
)


def make_extraction(
    *,
    name: str = "Acme Arc 27 Monitor",
    title: str = "Acme Arc 27 Monitor",
    url: str,
    brand: str | None = "Acme",
    model: str | None = "Arc 27",
    seller_name: str = "Fixture Store",
    retailer_id: str | None = None,
    sku: str | None = None,
    upc: str | None = None,
    ean: str | None = None,
    seller_trust_signal: SellerTrustSignal = SellerTrustSignal.UNKNOWN,
    price: str | None = None,
    availability_status: ListingAvailabilityStatus = ListingAvailabilityStatus.UNKNOWN,
    source_quality_level: SourceQualityLevel = SourceQualityLevel.UNKNOWN,
) -> ProductListingExtraction:
    source_id = new_id()
    product = CanonicalProduct(
        name=name,
        brand=brand,
        model=model,
        sku=sku,
        upc=upc,
        ean=ean,
        source_ids=(source_id,),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title=title,
        url=url,
        retailer_id=retailer_id,
        sku=sku,
        upc=upc,
        ean=ean,
        seller=SellerProfile(
            seller_name=seller_name,
            trust_signal=seller_trust_signal,
            source_ids=(source_id,),
        ),
        price=Money(amount=price, currency="USD") if price is not None else None,
        region_availability=(
            RegionAvailability(
                region_code="US",
                status=availability_status,
                source_ids=(source_id,),
            ),
        ),
        source_quality=SourceQuality(level=source_quality_level),
        source_ids=(source_id,),
    )
    return ProductListingExtraction(
        product=product,
        listing=listing,
        confidence=Confidence(
            score=0.9,
            level=ConfidenceLevel.HIGH,
            rationale="Fixture extraction.",
        ),
    )


def group_kinds(result) -> tuple[DeterministicMatchKind, ...]:
    return tuple(
        evidence.kind for group in result.groups for evidence in group.match_evidence
    )


def test_canonical_url_strips_tracking_and_collapses_same_listing() -> None:
    result = DeterministicProductDeduplicator().group(
        (
            make_extraction(url="https://www.example.com/products/arc-27?utm_source=a"),
            make_extraction(url="https://example.com/products/arc-27?utm_campaign=b"),
        )
    )

    assert result.collapsed_count == 1
    assert len(result.groups) == 1
    assert group_kinds(result) == (DeterministicMatchKind.CANONICAL_URL,)
    assert str(result.groups[0].listings[0].canonical_url) == (
        "https://example.com/products/arc-27"
    )
    assert {listing.product_id for listing in result.listings} == {
        result.groups[0].product.product_id
    }


def test_retailer_id_matching_collapses_same_retailer_product() -> None:
    result = DeterministicProductDeduplicator().group(
        (
            make_extraction(
                url="https://www.amazon.com/dp/B012345678?tag=affiliate",
                brand=None,
                model=None,
            ),
            make_extraction(
                url="https://amazon.com/gp/product/B012345678?psc=1",
                brand=None,
                model=None,
            ),
        )
    )

    assert result.collapsed_count == 1
    assert group_kinds(result) == (DeterministicMatchKind.RETAILER_ID,)
    assert {listing.retailer_id for listing in result.listings} == {"B012345678"}


def test_upc_ean_and_sku_matching_collapse_obvious_duplicates() -> None:
    deduplicator = DeterministicProductDeduplicator()

    upc_result = deduplicator.group(
        (
            make_extraction(
                url="https://store-a.example/item/one",
                model=None,
                upc="012345 678905",
            ),
            make_extraction(
                url="https://store-b.example/listing/two",
                model=None,
                upc="012345678905",
            ),
        )
    )
    ean_result = deduplicator.group(
        (
            make_extraction(
                url="https://store-a.example/item/three",
                model=None,
                ean="4006381333931",
            ),
            make_extraction(
                url="https://store-b.example/listing/four",
                model=None,
                ean="4 006381 333931",
            ),
        )
    )
    sku_result = deduplicator.group(
        (
            make_extraction(
                url="https://store-a.example/item/five",
                model=None,
                sku="arc-27-usb-c",
            ),
            make_extraction(
                url="https://store-b.example/listing/six",
                model=None,
                sku="ARC 27 USB C",
            ),
        )
    )

    assert upc_result.collapsed_count == 1
    assert ean_result.collapsed_count == 1
    assert sku_result.collapsed_count == 1
    assert group_kinds(upc_result) == (DeterministicMatchKind.UPC,)
    assert group_kinds(ean_result) == (DeterministicMatchKind.EAN,)
    assert group_kinds(sku_result) == (DeterministicMatchKind.SKU,)


def test_exact_brand_model_collapses_but_brand_mismatch_stays_distinct() -> None:
    exact_result = DeterministicProductDeduplicator().group(
        (
            make_extraction(
                url="https://store-a.example/item/acme-arc-27",
                brand="Acme",
                model="Arc 27",
            ),
            make_extraction(
                url="https://store-b.example/item/acme-arc-27",
                brand="ACME",
                model="arc 27",
            ),
        )
    )
    mismatch_result = DeterministicProductDeduplicator().group(
        (
            make_extraction(
                url="https://store-a.example/item/acme-arc-27",
                brand="Acme",
                model="Arc 27",
            ),
            make_extraction(
                url="https://store-b.example/item/nova-arc-27",
                brand="Nova",
                model="Arc 27",
            ),
        )
    )

    assert exact_result.collapsed_count == 1
    assert group_kinds(exact_result) == (DeterministicMatchKind.BRAND_MODEL,)
    assert mismatch_result.collapsed_count == 0
    assert len(mismatch_result.groups) == 2


def test_conservative_fuzzy_matching_collapses_high_confidence_same_product() -> None:
    result = DeterministicProductDeduplicator().group(
        (
            make_extraction(
                name="Acme Arc 27 USB-C Monitor",
                title="Acme Arc 27-inch USB-C Monitor",
                url="https://store-a.example/item/acme-arc-monitor",
                brand="Acme",
                model=None,
            ),
            make_extraction(
                name="ACME Arc 27 USB C Monitor",
                title="ACME Arc 27 USB C monitor",
                url="https://store-b.example/listing/acme-arc-monitor",
                brand="Acme",
                model=None,
            ),
        )
    )

    assert result.collapsed_count == 1
    assert len(result.groups) == 1
    assert group_kinds(result) == (DeterministicMatchKind.FUZZY_TITLE_SPECS,)
    assert [decision.outcome for decision in result.fuzzy_decisions] == [
        FuzzyProductMatchOutcome.SAME_PRODUCT
    ]


def test_conservative_fuzzy_matching_preserves_same_family_variants() -> None:
    result = DeterministicProductDeduplicator().group(
        (
            make_extraction(
                name="Acme Arc 27 Monitor",
                title="Acme Arc 27-inch Monitor",
                url="https://store-a.example/item/acme-arc-27",
                brand="Acme",
                model=None,
            ),
            make_extraction(
                name="Acme Arc 32 Monitor",
                title="Acme Arc 32-inch Monitor",
                url="https://store-b.example/listing/acme-arc-32",
                brand="Acme",
                model=None,
            ),
        )
    )

    assert result.collapsed_count == 0
    assert len(result.groups) == 2
    assert [decision.outcome for decision in result.fuzzy_decisions] == [
        FuzzyProductMatchOutcome.SAME_FAMILY
    ]
    assert result.fuzzy_decisions[0].conflicting_spec_tokens


def test_conservative_fuzzy_matching_preserves_uncertain_missing_specs() -> None:
    result = DeterministicProductDeduplicator().group(
        (
            make_extraction(
                name="Acme Arc Monitor",
                title="Acme Arc Monitor",
                url="https://store-a.example/item/acme-arc",
                brand="Acme",
                model=None,
            ),
            make_extraction(
                name="Acme Arc 27 Monitor",
                title="Acme Arc 27 Monitor",
                url="https://store-b.example/listing/acme-arc-27",
                brand="Acme",
                model=None,
            ),
        )
    )

    assert result.collapsed_count == 0
    assert len(result.groups) == 2
    assert [decision.outcome for decision in result.fuzzy_decisions] == [
        FuzzyProductMatchOutcome.UNCERTAIN
    ]


def test_conservative_fuzzy_matching_marks_different_product_without_grouping() -> None:
    result = DeterministicProductDeduplicator().group(
        (
            make_extraction(
                name="Acme Arc 27 Monitor",
                title="Acme Arc 27 Monitor",
                url="https://store-a.example/item/acme-arc-27",
                brand="Acme",
                model=None,
            ),
            make_extraction(
                name="Nova Arc 27 Monitor",
                title="Nova Arc 27 Monitor",
                url="https://store-b.example/listing/nova-arc-27",
                brand="Nova",
                model=None,
            ),
        )
    )

    assert result.collapsed_count == 0
    assert len(result.groups) == 2
    assert [decision.outcome for decision in result.fuzzy_decisions] == [
        FuzzyProductMatchOutcome.DIFFERENT_PRODUCT
    ]


def test_canonical_listing_url_preserves_variant_query_parameters() -> None:
    assert canonical_listing_url(
        "HTTPS://WWW.EXAMPLE.COM/products/arc-27/?color=black&utm_source=test#reviews"
    ) == "https://example.com/products/arc-27?color=black"
    assert canonical_listing_url(
        "https://example.com/products/arc-27?size=27&color=black"
    ) == "https://example.com/products/arc-27?color=black&size=27"


def test_grouping_preserves_listing_specific_seller_price_availability_and_quality() -> None:
    result = DeterministicProductDeduplicator().group(
        (
            make_extraction(
                url="https://official.example/products/acme-arc-27",
                seller_name="Acme Official",
                seller_trust_signal=SellerTrustSignal.STRONG,
                price="349.00",
                availability_status=ListingAvailabilityStatus.AVAILABLE,
                source_quality_level=SourceQualityLevel.STRONG,
            ),
            make_extraction(
                url="https://market.example/listings/acme-arc-27-deal",
                seller_name="Too Cheap Deals",
                seller_trust_signal=SellerTrustSignal.SUSPICIOUS,
                price="149.00",
                availability_status=ListingAvailabilityStatus.REGION_RESTRICTED,
                source_quality_level=SourceQualityLevel.WEAK,
            ),
        )
    )

    assert result.collapsed_count == 1
    assert len(result.groups) == 1
    grouped = result.groups[0]
    assert len(grouped.listings) == 2
    assert set(grouped.product.listing_ids) == {
        listing.listing_id for listing in grouped.listings
    }
    assert {listing.product_id for listing in grouped.listings} == {
        grouped.product.product_id
    }

    listings_by_seller = {
        listing.seller.seller_name: listing for listing in grouped.listings
    }
    official = listings_by_seller["Acme Official"]
    risky = listings_by_seller["Too Cheap Deals"]

    assert official.seller.trust_signal == SellerTrustSignal.STRONG
    assert risky.seller.trust_signal == SellerTrustSignal.SUSPICIOUS
    assert official.price is not None
    assert official.price.amount == 349
    assert risky.price is not None
    assert risky.price.amount == 149
    assert official.region_availability[0].status == ListingAvailabilityStatus.AVAILABLE
    assert risky.region_availability[0].status == (
        ListingAvailabilityStatus.REGION_RESTRICTED
    )
    assert official.source_quality.level == SourceQualityLevel.STRONG
    assert risky.source_quality.level == SourceQualityLevel.WEAK
