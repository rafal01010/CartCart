from decimal import Decimal

import pytest

from app.schemas import (
    CanonicalProduct,
    IKEAEvidenceFactType,
    IKEAStoreContext,
    Money,
    RegionalStoreAvailability,
    SourceQuality,
    SourceQualityLevel,
    new_id,
)
from app.schemas.source_references import SourceReference
from app.services.ikea_evidence_creation import (
    IKEAStoreEvidenceCreationError,
    IKEAStoreEvidenceCreator,
    IKEAStoreEvidenceInput,
)


def test_ikea_evidence_preserves_regional_official_store_context() -> None:
    product = CanonicalProduct(name="MICKE desk", brand="IKEA", model="MICKE")
    source_id = new_id()
    url = "https://www.ikea.com/ph/en/p/micke-desk-white-90214308/"

    bundle = IKEAStoreEvidenceCreator().create(
        (
            IKEAStoreEvidenceInput(
                product_id=product.product_id,
                source_reference=SourceReference(
                    source_id=source_id,
                    url=url,
                    title="MICKE desk, white - IKEA",
                ),
                store_context=IKEAStoreContext(
                    source_id=source_id,
                    country_code="PH",
                    official_url=url,
                    product_code="902.143.08",
                    product_name="MICKE desk, white",
                    store_name="IKEA Pasay City",
                    delivery_area="Available for delivery in Metro Manila.",
                    price=Money(amount=Decimal("3990"), currency="PHP"),
                    availability=RegionalStoreAvailability.AVAILABLE,
                ),
                source_quality=SourceQuality(
                    level=SourceQualityLevel.STRONG,
                    score=0.95,
                ),
                product_page_claim=(
                    "Official IKEA product page: MICKE desk, white. "
                    "Product number: 902.143.08."
                ),
            ),
        )
    )

    assert str(bundle.source_references[0].url) == url
    context = bundle.store_contexts[0]
    assert context.country_code == "PH"
    assert context.price is not None
    assert context.price.currency == "PHP"
    assert context.store_name == "IKEA Pasay City"
    assert context.delivery_area == "Available for delivery in Metro Manila."

    evidence_by_type = {item.fact_type: item for item in bundle.evidence}
    assert set(evidence_by_type) == {
        IKEAEvidenceFactType.OFFICIAL_PRODUCT_FACT,
        IKEAEvidenceFactType.REGIONAL_PRICE,
        IKEAEvidenceFactType.REGIONAL_AVAILABILITY,
        IKEAEvidenceFactType.STORE_DELIVERY_CONTEXT,
    }
    assert (
        evidence_by_type[IKEAEvidenceFactType.REGIONAL_AVAILABILITY].target.region_code
        == "PH"
    )
    assert (
        "IKEA Pasay City"
        in evidence_by_type[IKEAEvidenceFactType.STORE_DELIVERY_CONTEXT].claim
    )
    assert all("global" not in item.claim.casefold() for item in bundle.evidence)
    assert all(
        "shipping elsewhere" in " ".join(item.evidence_quality_warnings)
        for item in bundle.evidence
    )


def test_ikea_evidence_preserves_unavailable_product_as_evidence_and_gap() -> None:
    product = CanonicalProduct(name="KALLAX shelf unit", brand="IKEA")
    source_id = new_id()
    url = "https://www.ikea.com/us/en/p/kallax-shelf-unit-white-80275887/"

    bundle = IKEAStoreEvidenceCreator().create(
        (
            IKEAStoreEvidenceInput(
                product_id=product.product_id,
                source_reference=SourceReference(source_id=source_id, url=url),
                store_context=IKEAStoreContext(
                    source_id=source_id,
                    country_code="US",
                    official_url=url,
                    product_name=product.name,
                    delivery_area="Not available for delivery in this ZIP code.",
                    price=Money(amount=Decimal("89.99"), currency="USD"),
                    availability=RegionalStoreAvailability.OUT_OF_STOCK,
                ),
                source_quality=SourceQuality(
                    level=SourceQualityLevel.STRONG,
                    score=0.92,
                ),
                product_page_claim="Official IKEA product page: KALLAX shelf unit.",
            ),
        )
    )

    availability = next(
        item
        for item in bundle.evidence
        if item.fact_type == IKEAEvidenceFactType.REGIONAL_AVAILABILITY
    )
    assert "out_of_stock" in availability.claim
    assert any("out of stock" in gap.summary.casefold() for gap in bundle.evidence_gaps)


def test_ikea_evidence_records_missing_fields_as_gaps() -> None:
    product = CanonicalProduct(name="Fixture shelf")
    source_id = new_id()
    url = "https://www.ikea.com/ca/en/p/fixture-shelf-12345678/"

    bundle = IKEAStoreEvidenceCreator().create(
        (
            IKEAStoreEvidenceInput(
                product_id=product.product_id,
                source_reference=SourceReference(source_id=source_id, url=url),
                store_context=IKEAStoreContext(
                    source_id=source_id,
                    country_code="CA",
                    official_url=url,
                    product_name=product.name,
                ),
                source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE),
            ),
        )
    )

    summaries = {gap.summary for gap in bundle.evidence_gaps}
    assert "Official IKEA product-page facts were unavailable." in summaries
    assert "A regional IKEA price was unavailable." in summaries
    assert "Regional IKEA availability was not confirmed." in summaries
    assert "IKEA store, pickup, or delivery context was unavailable." in summaries
    assert bundle.evidence == ()


@pytest.mark.parametrize(
    "url",
    (
        "https://www.ikea.com/us/en/p/micke-desk-white-90214308/",
        "https://www.ikea.com/ph/en/p/micke-desk-white-90214308/?ref=campaign",
    ),
)
def test_ikea_evidence_rejects_cross_region_or_tracked_official_urls(url: str) -> None:
    product = CanonicalProduct(name="MICKE desk")
    source_id = new_id()
    evidence_input = IKEAStoreEvidenceInput(
        product_id=product.product_id,
        source_reference=SourceReference(source_id=source_id, url=url),
        store_context=IKEAStoreContext(
            source_id=source_id,
            country_code="PH",
            official_url=url,
            product_name=product.name,
        ),
        source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE),
    )

    with pytest.raises(
        IKEAStoreEvidenceCreationError,
        match="neutral official URL for the declared region",
    ):
        IKEAStoreEvidenceCreator().create((evidence_input,))
