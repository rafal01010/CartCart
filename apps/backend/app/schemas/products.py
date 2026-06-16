from enum import StrEnum

from pydantic import AnyHttpUrl, Field, model_validator

from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.confidence import Confidence
from app.schemas.ids import CandidateId, ListingId, ProductId, SourceId, new_id
from app.schemas.money import Money
from app.schemas.regions import RegionCode
from app.schemas.timestamps import Timestamp, utc_now


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
    category: str | None = Field(default=None, min_length=1, max_length=200)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    listing_ids: tuple[ListingId, ...] = Field(default_factory=tuple)


class ProductListing(VersionedSchema):
    listing_id: ListingId = Field(default_factory=new_id)
    product_id: ProductId
    title: str = Field(min_length=1, max_length=300)
    url: AnyHttpUrl
    seller: SellerProfile
    price: Money | None = None
    region_availability: tuple[RegionAvailability, ...] = Field(default_factory=tuple)
    source_ids: tuple[SourceId, ...] = Field(min_length=1)
    captured_at: Timestamp = Field(default_factory=utc_now)


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
    notes: str | None = Field(default=None, min_length=1, max_length=1000)
    created_at: Timestamp = Field(default_factory=utc_now)

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
        return self
