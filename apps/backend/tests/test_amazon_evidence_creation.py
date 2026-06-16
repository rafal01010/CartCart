import pytest

from app.schemas import (
    AmazonEvidenceFactType,
    AmazonListingContext,
    CanonicalProduct,
    SourceQuality,
    SourceQualityLevel,
    new_id,
)
from app.schemas.source_references import SourceReference
from app.services.amazon_evidence_creation import (
    AmazonEvidenceCreationError,
    AmazonProductEvidenceCreator,
    AmazonProductEvidenceInput,
)


def test_amazon_evidence_preserves_listing_risk_review_ambiguity_and_unavailable_shipping() -> None:
    product = CanonicalProduct(name="Fixture Portable Monitor")
    listing_id = new_id()
    listing_title = "Fixture Portable Monitor 15"
    source_id = new_id()
    url = "https://www.amazon.com/dp/B012345678"
    bundle = AmazonProductEvidenceCreator().create(
        (
            AmazonProductEvidenceInput(
                product_id=product.product_id,
                listing_id=listing_id,
                source_reference=SourceReference(
                    source_id=source_id,
                    url=url,
                    title=listing_title,
                ),
                listing_context=AmazonListingContext(
                    source_id=source_id,
                    marketplace_name="Amazon",
                    marketplace_domain="amazon.com",
                    marketplace_country_code="US",
                    listing_url=url,
                    asin="B012345678",
                    external_listing_id="B012345678",
                    product_title=listing_title,
                    variant_label="Size: 15 inch",
                    seller_name="Fixture Deals",
                    fulfillment="Fulfilled by Amazon",
                    ships_to_region_code="PH",
                    ships_to_region=False,
                    review_count=420,
                    average_rating=4.3,
                ),
                source_quality=SourceQuality(
                    level=SourceQualityLevel.ADEQUATE,
                    score=0.76,
                ),
                product_page_claim="Amazon product page states: USB-C video input.",
                review_summary_claim=(
                    "Average rating 4.3 out of 5 from 420 reviews."
                ),
                review_quality_warnings=(
                    "Review totals may combine multiple Amazon variants.",
                ),
            ),
        )
    )

    context = bundle.listing_contexts[0]
    assert context.marketplace_domain == "amazon.com"
    assert context.asin == "B012345678"
    assert context.seller_name == "Fixture Deals"
    assert context.fulfillment == "Fulfilled by Amazon"
    assert context.ships_to_region is False
    assert str(bundle.source_references[0].url) == url

    evidence_by_type = {item.fact_type: item for item in bundle.evidence}
    assert "B012345678" in evidence_by_type[
        AmazonEvidenceFactType.LISTING_IDENTITY
    ].claim
    assert "third-party marketplace seller Fixture Deals" in evidence_by_type[
        AmazonEvidenceFactType.MARKETPLACE_WARNING
    ].claim
    assert "unavailable for delivery to PH" in evidence_by_type[
        AmazonEvidenceFactType.REGIONAL_AVAILABILITY
    ].claim
    review_evidence = evidence_by_type[AmazonEvidenceFactType.REVIEW_SUMMARY]
    assert "multiple Amazon variants" in " ".join(
        review_evidence.evidence_quality_warnings
    )
    assert "not independently authenticated" in evidence_by_type[
        AmazonEvidenceFactType.REVIEW_QUALITY_WARNING
    ].claim


def test_amazon_evidence_records_missing_product_review_and_shipping_access_as_gaps() -> None:
    product = CanonicalProduct(name="Fixture Product")
    source_id = new_id()
    listing_id = new_id()
    url = "https://www.amazon.com/dp/B087654321"

    bundle = AmazonProductEvidenceCreator().create(
        (
            AmazonProductEvidenceInput(
                product_id=product.product_id,
                listing_id=listing_id,
                source_reference=SourceReference(source_id=source_id, url=url),
                listing_context=AmazonListingContext(
                    source_id=source_id,
                    marketplace_name="Amazon",
                    marketplace_domain="amazon.com",
                    listing_url=url,
                    asin="B087654321",
                    product_title=product.name,
                    ships_to_region_code="US",
                ),
                source_quality=SourceQuality(
                    level=SourceQualityLevel.MIXED,
                    score=0.6,
                ),
            ),
        )
    )

    fact_types = {item.fact_type for item in bundle.evidence}
    assert AmazonEvidenceFactType.PRODUCT_PAGE_FACT not in fact_types
    assert AmazonEvidenceFactType.REVIEW_SUMMARY not in fact_types
    summaries = {gap.summary for gap in bundle.evidence_gaps}
    assert "Amazon product-page facts were unavailable." in summaries
    assert "Amazon review signals were unavailable." in summaries
    assert "Amazon shipping to US could not be confirmed." in summaries
    assert "Amazon seller and fulfillment details were unavailable." in summaries


def test_amazon_evidence_rejects_affiliate_or_tracking_listing_urls() -> None:
    source_id = new_id()
    product = CanonicalProduct(name="Fixture Product")
    tracked_url = "https://www.amazon.com/dp/B012345678?tag=affiliate-20"
    evidence_input = AmazonProductEvidenceInput(
        product_id=product.product_id,
        listing_id=new_id(),
        source_reference=SourceReference(source_id=source_id, url=tracked_url),
        listing_context=AmazonListingContext(
            source_id=source_id,
            marketplace_name="Amazon",
            marketplace_domain="amazon.com",
            listing_url=tracked_url,
            asin="B012345678",
            product_title=product.name,
        ),
        source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE),
    )

    with pytest.raises(
        AmazonEvidenceCreationError,
        match="neutral marketplace listing URL",
    ):
        AmazonProductEvidenceCreator().create((evidence_input,))
