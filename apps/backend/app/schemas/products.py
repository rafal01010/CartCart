from enum import StrEnum
from typing import Any

from pydantic import AnyHttpUrl, Field, computed_field, field_validator, model_validator

from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.confidence import Confidence
from app.schemas.ids import CandidateId, ListingId, ProductId, SourceId, new_id
from app.schemas.money import Money
from app.schemas.regions import RegionCode
from app.schemas.search_sources import SourceQuality, SourceQualityLevel
from app.schemas.timestamps import Timestamp, utc_now


MANUAL_UNVERIFIED_SUMMARY = (
    "Added by you; product and buying details are not independently checked."
)


class ListingAvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    OUT_OF_STOCK = "out_of_stock"
    PREORDER = "preorder"
    REGION_RESTRICTED = "region_restricted"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class SellerTrustSignal(StrEnum):
    STRONG = "strong"
    REASONABLE = "reasonable"
    MIXED = "mixed"
    WEAK = "weak"
    SUSPICIOUS = "suspicious"
    UNKNOWN = "unknown"


class ListingExtractionMissingField(StrEnum):
    BRAND = "brand"
    PRICE = "price"
    CURRENCY = "currency"
    SELLER_STORE = "seller_store"
    REGION = "region"


class UserAddedMatchConfidence(StrEnum):
    CONFIRMED = "confirmed"
    POSSIBLE = "possible"


class ManualFallbackReason(StrEnum):
    RETRIEVAL_UNAVAILABLE = "retrieval_unavailable"
    RETRIEVAL_INSUFFICIENT = "retrieval_insufficient"
    USER_CORRECTION = "user_correction"


class ManualProductDetails(CartCartBaseModel):
    """Shopper reports, never independently verified product or offer evidence."""

    seller: str | None = Field(default=None, min_length=1, max_length=200)
    price: Money | None = None
    availability: str | None = Field(default=None, min_length=1, max_length=200)
    review: str | None = Field(default=None, min_length=1, max_length=1000)
    warranty: str | None = Field(default=None, min_length=1, max_length=500)
    specifications: str | None = Field(default=None, min_length=1, max_length=1000)


class UserAddedListingMatch(CartCartBaseModel):
    candidate_id: CandidateId
    source_id: SourceId
    confidence: UserAddedMatchConfidence


class RegionAvailability(CartCartBaseModel):
    region_code: RegionCode
    status: ListingAvailabilityStatus = ListingAvailabilityStatus.UNKNOWN
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    checked_at: Timestamp | None = None
    notes: str | None = Field(default=None, min_length=1, max_length=500)


class SellerProfile(CartCartBaseModel):
    seller_name: str = Field(min_length=1, max_length=200)
    seller_url: AnyHttpUrl | None = None
    marketplace_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_marketplace_seller: bool | None = None
    trust_signal: SellerTrustSignal = SellerTrustSignal.UNKNOWN
    trust_confidence: Confidence | None = None
    trust_notes: str | None = Field(default=None, min_length=1, max_length=1000)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)


class CanonicalProduct(VersionedSchema):
    product_id: ProductId = Field(default_factory=new_id)
    name: str = Field(min_length=1, max_length=300)
    brand: str | None = Field(default=None, min_length=1, max_length=200)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    sku: str | None = Field(default=None, min_length=1, max_length=120)
    upc: str | None = Field(default=None, min_length=1, max_length=14)
    ean: str | None = Field(default=None, min_length=1, max_length=14)
    category: str | None = Field(default=None, min_length=1, max_length=200)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    listing_ids: tuple[ListingId, ...] = Field(default_factory=tuple)

    @field_validator("sku", mode="before")
    @classmethod
    def _normalize_identifier(cls, value: Any) -> Any:
        return _normalize_identifier_value(value)

    @field_validator("upc", "ean", mode="before")
    @classmethod
    def _normalize_gtin(cls, value: Any) -> Any:
        return _normalize_gtin_value(value)


class ProductListing(VersionedSchema):
    listing_id: ListingId = Field(default_factory=new_id)
    product_id: ProductId
    title: str = Field(min_length=1, max_length=300)
    url: AnyHttpUrl
    canonical_url: AnyHttpUrl | None = None
    retailer_id: str | None = Field(default=None, min_length=1, max_length=160)
    sku: str | None = Field(default=None, min_length=1, max_length=120)
    upc: str | None = Field(default=None, min_length=1, max_length=14)
    ean: str | None = Field(default=None, min_length=1, max_length=14)
    seller: SellerProfile
    price: Money | None = None
    region_availability: tuple[RegionAvailability, ...] = Field(default_factory=tuple)
    source_quality: SourceQuality = Field(
        default_factory=lambda: SourceQuality(level=SourceQualityLevel.UNKNOWN)
    )
    source_ids: tuple[SourceId, ...] = Field(min_length=1)
    user_added_matches: tuple[UserAddedListingMatch, ...] = Field(default_factory=tuple)
    captured_at: Timestamp = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _user_added_matches_cite_listing(self) -> "ProductListing":
        if any(
            match.source_id not in self.source_ids for match in self.user_added_matches
        ):
            raise ValueError("user-added listing match must cite a listing source")
        return self

    @field_validator("retailer_id", "sku", mode="before")
    @classmethod
    def _normalize_identifier(cls, value: Any) -> Any:
        return _normalize_identifier_value(value)

    @field_validator("upc", "ean", mode="before")
    @classmethod
    def _normalize_gtin(cls, value: Any) -> Any:
        return _normalize_gtin_value(value)


class ProductListingExtraction(VersionedSchema):
    product: CanonicalProduct
    listing: ProductListing
    missing_data_flags: tuple[ListingExtractionMissingField, ...] = Field(
        default_factory=tuple
    )
    confidence: Confidence

    @model_validator(mode="after")
    def _product_and_listing_must_match(self) -> "ProductListingExtraction":
        if self.product.product_id != self.listing.product_id:
            raise ValueError(
                "extracted product and listing must reference the same product."
            )
        return self


class UserAddedProduct(VersionedSchema):
    candidate_id: CandidateId = Field(default_factory=new_id)
    input_text: str | None = Field(default=None, min_length=1, max_length=1000)
    url: AnyHttpUrl | None = None
    product: CanonicalProduct | None = None
    listing: ProductListing | None = None
    possible_product_ids: tuple[ProductId, ...] = Field(default_factory=tuple)
    research_attempted: bool = False
    manual_fallback_reason: ManualFallbackReason | None = None
    manual_details: ManualProductDetails | None = None
    notes: str | None = Field(default=None, min_length=1, max_length=1000)
    created_at: Timestamp = Field(default_factory=utc_now)

    @computed_field
    @property
    def manual_evidence_status(self) -> dict[str, str] | None:
        if self.manual_fallback_reason is None:
            return None
        product = self.product
        details = self.manual_details
        values = {
            "name": product.name if product else None,
            "brand": product.brand if product else None,
            "model": product.model if product else None,
            "category": product.category if product else None,
            "seller": details.seller if details else None,
            "price": details.price if details else None,
            "availability": details.availability if details else None,
            "review": details.review if details else None,
            "warranty": details.warranty if details else None,
            "specifications": details.specifications if details else None,
        }
        return {
            "source": "unknown",
            **{
                field: "user_reported" if value is not None else "unknown"
                for field, value in values.items()
            },
        }

    @model_validator(mode="after")
    def _requires_user_supplied_candidate_detail(self) -> "UserAddedProduct":
        if not (self.input_text or self.url or self.product or self.listing):
            raise ValueError(
                "user-added products require text, a URL, product details, or a listing."
            )
        if (
            self.product is not None
            and self.listing is not None
            and self.product.product_id != self.listing.product_id
        ):
            raise ValueError(
                "user-added product and listing must reference the same product."
            )
        if self.manual_fallback_reason is None and self.manual_details is not None:
            raise ValueError("manual details require a fallback reason.")
        if self.manual_fallback_reason is not None and self.product is None:
            raise ValueError("manual fallback requires a named product.")
        return self


def _normalize_identifier_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    normalized = " ".join(value.strip().split())
    return normalized.upper() if normalized else None


def _normalize_gtin_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    normalized = "".join(character for character in value if character.isdigit())
    return normalized or None
