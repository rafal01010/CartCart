from itertools import permutations

import pytest

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


def test_shared_category_path_does_not_invent_an_exact_retailer_id() -> None:
    extractions = (
        make_extraction(
            url="https://shop.example/products/monitors/acme-arc-27",
        ),
        make_extraction(
            name="Nova Beam 32 Monitor",
            title="Nova Beam 32 Monitor",
            url="https://shop.example/products/monitors/nova-beam-32",
            brand="Nova",
            model="Beam 32",
        ),
    )

    result = DeterministicProductDeduplicator().group(extractions)

    assert result.collapsed_count == 0
    assert [group.product.name for group in result.groups] == [
        "Acme Arc 27 Monitor",
        "Nova Beam 32 Monitor",
    ]
    assert [listing.retailer_id for listing in result.listings] == [None, None]
    assert [listing.listing_id for listing in result.listings] == [
        extraction.listing.listing_id for extraction in extractions
    ]


def test_tracking_only_duplicates_on_nested_paths_still_group_by_canonical_url() -> None:
    result = DeterministicProductDeduplicator().group(
        (
            make_extraction(
                url="https://shop.example/products/monitors/arc-27?utm_source=first",
                brand=None,
                model=None,
            ),
            make_extraction(
                url="https://shop.example/products/monitors/arc-27?utm_source=second",
                brand=None,
                model=None,
            ),
        )
    )

    assert result.collapsed_count == 1
    assert group_kinds(result) == (DeterministicMatchKind.CANONICAL_URL,)
    assert [listing.retailer_id for listing in result.listings] == [None, None]
    assert str(result.groups[0].listings[0].canonical_url) == (
        "https://shop.example/products/monitors/arc-27"
    )


@pytest.mark.parametrize(
    ("left_url", "right_url", "explicit_id", "expected_id"),
    (
        (
            "https://shop.example/products/monitors/offer-one",
            "https://shop.example/products/displays/offer-two",
            "monitor-123",
            "MONITOR-123",
        ),
        (
            "https://shop.example/products/arc-27",
            "https://shop.example/item/arc-27",
            None,
            "ARC27",
        ),
        (
            "https://shop.example/search?product_id=arc-27",
            "https://shop.example/details?pid=arc-27",
            None,
            "ARC27",
        ),
        (
            "https://www.ikea.com/us/en/p/first-chair-12345678/",
            "https://www.ikea.com/gb/en/p/renamed-chair-12345678/",
            None,
            "12345678",
        ),
    ),
)
def test_supported_retailer_product_ids_still_group(
    left_url: str,
    right_url: str,
    explicit_id: str | None,
    expected_id: str,
) -> None:
    result = DeterministicProductDeduplicator().group(
        tuple(
            make_extraction(
                url=url, brand=None, model=None, retailer_id=explicit_id
            )
            for url in (left_url, right_url)
        )
    )

    assert result.collapsed_count == 1
    assert group_kinds(result) == (DeterministicMatchKind.RETAILER_ID,)
    assert {listing.retailer_id for listing in result.listings} == {expected_id}


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


@pytest.mark.parametrize(
    ("identifier", "left_value", "right_value"),
    (
        ("upc", "012345678905", "012345678912"),
        ("ean", "4006381333931", "4006381333948"),
    ),
)
@pytest.mark.parametrize(
    "matching_route", ("brand_model", "fuzzy", "url", "retailer", "sku")
)
def test_known_identifier_conflicts_prevent_exact_and_fuzzy_merges(
    identifier: str,
    left_value: str,
    right_value: str,
    matching_route: str,
) -> None:
    left_url = "https://shop.example/offers/one?utm_source=first"
    right_url = (
        "https://shop.example/offers/one?utm_source=second"
        if matching_route == "url"
        else "https://shop.example/offers/two"
    )
    left = make_extraction(
        url=left_url,
        model=None if matching_route == "fuzzy" else "Arc 27",
        retailer_id="arc-27" if matching_route == "retailer" else None,
        sku="arc-27" if matching_route == "sku" else None,
        seller_name="Acme Official",
        seller_trust_signal=SellerTrustSignal.STRONG,
        price="349.00",
        availability_status=ListingAvailabilityStatus.AVAILABLE,
        source_quality_level=SourceQualityLevel.STRONG,
        **{identifier: left_value},
    )
    right = make_extraction(
        url=right_url,
        model=None if matching_route == "fuzzy" else "Arc 27",
        retailer_id="arc-27" if matching_route == "retailer" else None,
        sku="arc-27" if matching_route == "sku" else None,
        seller_name="Discount seller",
        seller_trust_signal=SellerTrustSignal.SUSPICIOUS,
        price="149.00",
        availability_status=ListingAvailabilityStatus.REGION_RESTRICTED,
        source_quality_level=SourceQualityLevel.WEAK,
        **{identifier: right_value},
    )

    result = DeterministicProductDeduplicator().group((left, right))

    assert result.collapsed_count == 0
    assert len(result.groups) == 2
    assert [getattr(group.product, identifier) for group in result.groups] == [
        left_value,
        right_value,
    ]
    assert [decision.outcome for decision in result.fuzzy_decisions] == [
        FuzzyProductMatchOutcome.UNCERTAIN
    ]
    assert identifier.upper() in result.fuzzy_decisions[0].rationale
    for actual, original in zip(
        result.listings, (left.listing, right.listing), strict=True
    ):
        assert actual.model_dump(
            exclude={"product_id", "canonical_url", "retailer_id"}
        ) == original.model_dump(
            exclude={"product_id", "canonical_url", "retailer_id"}
        )
        assert actual.product_id == original.product_id


@pytest.mark.parametrize("matching_identifier", ("upc", "ean"))
def test_matching_identifier_does_not_override_other_identifier_conflict(
    matching_identifier: str,
) -> None:
    left = make_extraction(
        url="https://store-a.example/offers/one",
        upc="012345678905",
        ean="4006381333931",
    )
    right = make_extraction(
        url="https://store-b.example/offers/two",
        upc="012345678905" if matching_identifier == "upc" else "012345678912",
        ean="4006381333931" if matching_identifier == "ean" else "4006381333948",
    )

    result = DeterministicProductDeduplicator().group((left, right))

    assert result.collapsed_count == 0
    assert len(result.groups) == 2
    assert [listing.upc for listing in result.listings] == [
        left.listing.upc, right.listing.upc
    ]
    assert [listing.ean for listing in result.listings] == [
        left.listing.ean, right.listing.ean
    ]
    assert result.fuzzy_decisions[0].outcome == FuzzyProductMatchOutcome.UNCERTAIN


@pytest.mark.parametrize(
    ("identifier", "value"),
    (("upc", "012345678905"), ("ean", "4006381333931")),
)
def test_matching_and_missing_identifiers_remain_compatible(
    identifier: str, value: str
) -> None:
    extractions = tuple(
        make_extraction(
            url=f"https://store-{index}.example/offers/arc",
            **{identifier: value if index < 2 else None},
        )
        for index in range(3)
    )

    result = DeterministicProductDeduplicator().group(extractions)

    assert result.collapsed_count == 2
    assert len(result.groups) == 1
    assert getattr(result.groups[0].product, identifier) == value
    assert group_kinds(result) == (
        DeterministicMatchKind(identifier),
        DeterministicMatchKind.BRAND_MODEL,
    )
    assert len(result.listings) == 3


@pytest.mark.parametrize("order", tuple(permutations(range(3))))
@pytest.mark.parametrize("model", ("Arc 27", None))
@pytest.mark.parametrize(
    ("identifier", "left_value", "right_value"),
    (
        ("upc", "012345678905", "012345678912"),
        ("ean", "4006381333931", "4006381333948"),
    ),
)
def test_missing_identifier_cannot_bridge_conflicting_group_members(
    order: tuple[int, ...],
    model: str | None,
    identifier: str,
    left_value: str,
    right_value: str,
) -> None:
    unknown = make_extraction(url="https://unknown.example/offers/arc", model=model)
    listing_identity = make_extraction(
        url="https://listing.example/offers/arc", model=model, **{identifier: left_value}
    )
    listing_identity = listing_identity.model_copy(
        update={"product": listing_identity.product.model_copy(update={identifier: None})}
    )
    product_identity = make_extraction(
        url="https://product.example/offers/arc", model=model, **{identifier: right_value}
    )
    product_identity = product_identity.model_copy(
        update={"listing": product_identity.listing.model_copy(update={identifier: None})}
    )
    extractions = (unknown, listing_identity, product_identity)

    result = DeterministicProductDeduplicator().group(
        tuple(extractions[index] for index in order)
    )

    assert result.collapsed_count == 1
    assert len(result.groups) == 2
    listing_groups = {
        listing.listing_id: group.product.product_id
        for group in result.groups
        for listing in group.listings
    }
    assert listing_groups[listing_identity.listing.listing_id] != listing_groups[
        product_identity.listing.listing_id
    ]
    assert set(listing_groups) == {
        extraction.listing.listing_id for extraction in extractions
    }


@pytest.mark.parametrize(
    ("identifier", "left_value", "right_value"),
    (
        ("upc", "012345678905", "012345678912"),
        ("ean", "4006381333931", "4006381333948"),
    ),
)
def test_conflicting_product_and_listing_identifiers_cannot_match_on_overlap(
    identifier: str, left_value: str, right_value: str
) -> None:
    first = make_extraction(
        url="https://store-a.example/offers/arc", **{identifier: left_value}
    )
    conflicting = make_extraction(
        url="https://store-b.example/offers/arc", **{identifier: left_value}
    )
    conflicting = conflicting.model_copy(
        update={
            "listing": conflicting.listing.model_copy(update={identifier: right_value})
        }
    )

    result = DeterministicProductDeduplicator().group((first, conflicting))

    assert result.collapsed_count == 0
    assert len(result.groups) == 2
    assert getattr(result.groups[1].product, identifier) == left_value
    assert getattr(result.groups[1].listings[0], identifier) == right_value
    assert result.fuzzy_decisions[0].outcome == FuzzyProductMatchOutcome.UNCERTAIN


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


def test_repeated_listing_id_preserves_all_user_matches_once() -> None:
    from app.schemas.products import UserAddedListingMatch

    first = make_extraction(url="https://example.com/products/arc-27")
    source_id = first.listing.source_ids[0]
    first_match = UserAddedListingMatch(
        candidate_id=new_id(), source_id=source_id, confidence="confirmed"
    )
    second_match = UserAddedListingMatch(
        candidate_id=new_id(), source_id=source_id, confidence="confirmed"
    )
    first = first.model_copy(
        update={"listing": first.listing.model_copy(update={"user_added_matches": (first_match,)})}
    )
    repeat = first.model_copy(
        update={"listing": first.listing.model_copy(update={"user_added_matches": (second_match,)})}
    )
    different_offer = make_extraction(
        url="https://other.example/products/arc-27", seller_name="Other seller", price="250"
    )
    result = DeterministicProductDeduplicator().group((first, repeat, different_offer))
    assert len(result.groups) == 1
    assert len(result.listings) == 2
    assert result.listings[0].user_added_matches == (first_match, second_match)
    assert result.listings[1].seller.seller_name == "Other seller"
    assert result.listings[1].price is not None
    assert result.groups[0].product.listing_ids == tuple(item.listing_id for item in result.listings)
