from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import (
    CanonicalProduct,
    Confidence,
    ConfidenceLevel,
    ListingAvailabilityStatus,
    Money,
    ProductListing,
    RegionAvailability,
    SellerProfile,
    SellerTrustSignal,
    UserAddedProduct,
    new_id,
)


def make_seller(
    seller_name: str,
    trust_signal: SellerTrustSignal,
) -> SellerProfile:
    seller_slug = seller_name.lower().replace(" ", "-")
    return SellerProfile(
        seller_name=seller_name,
        seller_url=f"https://example.com/sellers/{seller_slug}",
        trust_signal=trust_signal,
        trust_confidence=Confidence(
            score=0.82 if trust_signal == SellerTrustSignal.STRONG else 0.38,
            level=(
                ConfidenceLevel.HIGH
                if trust_signal == SellerTrustSignal.STRONG
                else ConfidenceLevel.LOW
            ),
            rationale="Fixture seller trust signal.",
        ),
        source_ids=(new_id(),),
    )


def make_region_availability(
    status: ListingAvailabilityStatus,
) -> RegionAvailability:
    return RegionAvailability(
        region_code="us",
        status=status,
        source_ids=(new_id(),),
        checked_at="2026-05-30T00:00:00Z",
    )


def test_same_product_can_have_multiple_listings_with_different_seller_trust() -> None:
    product = CanonicalProduct(
        name="Acme Travel Laptop 13",
        brand="Acme",
        model="Travel 13",
        category="laptop",
        source_ids=(new_id(),),
    )

    official_listing = ProductListing(
        product_id=product.product_id,
        title="Acme Travel Laptop 13 - Official Store",
        url="https://example.com/acme/travel-13",
        seller=make_seller("Acme Official", SellerTrustSignal.STRONG),
        price=Money(amount="999.00", currency="usd"),
        region_availability=(
            make_region_availability(ListingAvailabilityStatus.AVAILABLE),
        ),
        source_ids=(new_id(),),
        captured_at="2026-05-30T00:05:00Z",
    )
    risky_listing = ProductListing(
        product_id=product.product_id,
        title="Acme Travel Laptop 13 - Marketplace Deal",
        url="https://example.com/market/acme-travel-13",
        seller=make_seller("Too Cheap Deals", SellerTrustSignal.SUSPICIOUS),
        price=Money(amount="499.00", currency="USD"),
        region_availability=(
            make_region_availability(ListingAvailabilityStatus.REGION_RESTRICTED),
        ),
        source_ids=(new_id(),),
    )
    grouped_product = product.model_copy(
        update={
            "listing_ids": (
                official_listing.listing_id,
                risky_listing.listing_id,
            )
        }
    )

    assert official_listing.product_id == grouped_product.product_id
    assert risky_listing.product_id == grouped_product.product_id
    assert official_listing.listing_id != risky_listing.listing_id
    assert official_listing.seller.trust_signal == SellerTrustSignal.STRONG
    assert risky_listing.seller.trust_signal == SellerTrustSignal.SUSPICIOUS
    assert official_listing.price is not None
    assert official_listing.price.currency == "USD"
    assert official_listing.region_availability[0].region_code == "US"
    assert risky_listing.region_availability[0].status == (
        ListingAvailabilityStatus.REGION_RESTRICTED
    )


def test_canonical_product_rejects_listing_only_fields() -> None:
    with pytest.raises(ValidationError):
        CanonicalProduct(
            name="Acme Travel Laptop 13",
            price={"amount": "999.00", "currency": "USD"},
        )

    with pytest.raises(ValidationError):
        CanonicalProduct(
            name="Acme Travel Laptop 13",
            seller={"seller_name": "Acme Official"},
        )


def test_product_listing_requires_listing_identity_url_seller_and_sources() -> None:
    product_id = new_id()

    with pytest.raises(ValidationError):
        ProductListing(
            product_id=product_id,
            title="Acme Travel Laptop 13",
            url="https://example.com/acme/travel-13",
            seller=make_seller("Acme Official", SellerTrustSignal.REASONABLE),
            source_ids=(),
        )

    with pytest.raises(ValidationError):
        ProductListing(
            product_id=product_id,
            title="Acme Travel Laptop 13",
            url="not-a-url",
            seller=make_seller("Acme Official", SellerTrustSignal.REASONABLE),
            source_ids=(new_id(),),
        )


def test_user_added_product_accepts_manual_product_or_listing_and_rejects_mismatch() -> None:
    product = CanonicalProduct(name="Acme Travel Laptop 13")
    listing = ProductListing(
        product_id=product.product_id,
        title="Acme Travel Laptop 13",
        url="https://example.com/acme/travel-13",
        seller=make_seller("Acme Official", SellerTrustSignal.REASONABLE),
        source_ids=(new_id(),),
    )
    user_added = UserAddedProduct(
        input_text="This is the one I was considering.",
        product=product,
        listing=listing,
        created_at="2026-05-30T00:10:00Z",
    )

    assert user_added.product is not None
    assert user_added.listing is not None
    assert user_added.created_at == datetime(2026, 5, 30, 0, 10, tzinfo=UTC)

    with pytest.raises(ValidationError):
        UserAddedProduct()

    with pytest.raises(ValidationError):
        UserAddedProduct(
            product=product,
            listing=ProductListing(
                product_id=new_id(),
                title="Different product listing",
                url="https://example.com/other",
                seller=make_seller("Other Seller", SellerTrustSignal.MIXED),
                source_ids=(new_id(),),
            ),
        )
