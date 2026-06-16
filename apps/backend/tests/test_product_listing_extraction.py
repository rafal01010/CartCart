import json
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from app.schemas import (
    ConfidenceLevel,
    ListingExtractionMissingField,
    ProviderMetadata,
    RawSourceSnapshotArtifact,
    SearchQuery,
    SearchResult,
    SourceSnapshot,
    SourceType,
)
from app.services.product_listing_extraction import (
    ProductListingExtractionError,
    ProductListingExtractor,
)
from app.services.source_extraction import StaticPageTextExtractor


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "extraction"


def test_search_result_fixture_produces_complete_confident_listing() -> None:
    payload = json.loads((FIXTURE_DIR / "search_product_listing.json").read_text())

    extracted = ProductListingExtractor().extract_search_result(
        SearchResult.model_validate(payload)
    )

    assert extracted.product.brand == "Northstar"
    assert extracted.listing.title == "Northstar Arc 27 USB-C Monitor"
    assert extracted.listing.price is not None
    assert extracted.listing.price.amount == 18990
    assert extracted.listing.price.currency == "PHP"
    assert extracted.listing.seller.seller_name == "Metro Office"
    assert extracted.listing.region_availability[0].region_code == "PH"
    assert extracted.missing_data_flags == ()
    assert extracted.confidence.score == 1.0
    assert extracted.confidence.level == ConfidenceLevel.HIGH


def test_static_page_fixture_produces_complete_confident_listing(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot_from_fixture(tmp_path, "product_listing_page.html")
    page = StaticPageTextExtractor(snapshot_dir=tmp_path).extract(snapshot)

    extracted = ProductListingExtractor().extract_source_snapshot(page)

    assert extracted.product.brand == "Northstar"
    assert extracted.listing.price is not None
    assert extracted.listing.price.amount == Decimal("329.99")
    assert extracted.listing.price.currency == "USD"
    assert extracted.listing.seller.seller_name == "Metro Office"
    assert extracted.listing.region_availability[0].region_code == "US"
    assert extracted.missing_data_flags == ()
    assert extracted.confidence.score == 1.0


def test_partial_search_result_records_missing_fields_and_lower_confidence() -> None:
    result = SearchResult(
        query=SearchQuery(query="portable monitor", intent="discovery"),
        url="https://shop.example/products/portable-monitor",
        title="Portable USB-C Monitor",
        provider=ProviderMetadata(provider_name="fixture"),
    )

    extracted = ProductListingExtractor().extract_search_result(result)

    assert extracted.listing.seller.seller_name == "shop.example"
    assert extracted.listing.price is None
    assert extracted.missing_data_flags == (
        ListingExtractionMissingField.BRAND,
        ListingExtractionMissingField.PRICE,
        ListingExtractionMissingField.CURRENCY,
        ListingExtractionMissingField.SELLER_STORE,
        ListingExtractionMissingField.REGION,
    )
    assert extracted.confidence.score == 0.4
    assert extracted.confidence.level == ConfidenceLevel.LOW


def test_product_spec_number_is_not_treated_as_a_price() -> None:
    result = SearchResult(
        query=SearchQuery(query="USB monitor", intent="discovery"),
        url="https://shop.example/products/usb-monitor",
        title="Portable Monitor with USB 3 input",
        provider=ProviderMetadata(provider_name="fixture"),
    )

    extracted = ProductListingExtractor().extract_search_result(result)

    assert extracted.listing.price is None
    assert ListingExtractionMissingField.PRICE in extracted.missing_data_flags


def test_extracted_review_page_is_not_normalized_as_a_listing() -> None:
    snapshot = SourceSnapshot(
        url="https://reviews.example/northstar",
        source_type=SourceType.PROFESSIONAL_REVIEW,
        provider=ProviderMetadata(provider_name="fixture"),
        title="Northstar monitor review",
    )

    with pytest.raises(ProductListingExtractionError):
        ProductListingExtractor().extract_source_snapshot(snapshot)


def _snapshot_from_fixture(tmp_path: Path, fixture_name: str) -> SourceSnapshot:
    content = (FIXTURE_DIR / fixture_name).read_bytes()
    stored_path = tmp_path / fixture_name
    stored_path.write_bytes(content)
    return SourceSnapshot(
        url=f"https://metro-office.example/{fixture_name}",
        source_type=SourceType.RETAILER_LISTING,
        provider=ProviderMetadata(provider_name="http-fetch"),
        http_status_code=200,
        raw_artifact=RawSourceSnapshotArtifact(
            path=fixture_name,
            content_type="text/html",
            size_bytes=len(content),
            sha256=sha256(content).hexdigest(),
        ),
    )
