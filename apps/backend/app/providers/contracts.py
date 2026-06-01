from enum import StrEnum
from typing import Protocol

from pydantic import AnyHttpUrl, Field, model_validator

from app.schemas.base import CartCartBaseModel
from app.schemas.products import CanonicalProduct, ProductListing
from app.schemas.regions import RegionCode
from app.schemas.search_sources import (
    SearchQuery,
    SearchResult,
    SourceEvidence,
    SourceSnapshot,
    SourceType,
    TranscriptAvailability,
    VideoReviewEvidenceBundle,
    VideoSource,
    VideoTranscriptSegment,
)


class SourcePolicyAction(StrEnum):
    ALLOW = "allow"
    AVOID = "avoid"


class ProviderRunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"


class ProviderCapabilityFlags(CartCartBaseModel):
    provider_name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    uses_official_api: bool = False
    requires_user_authorization: bool = False
    supports_video_search: bool = False
    supports_transcripts: bool = False
    supports_marketplace_availability: bool = False
    supports_official_store_lookup: bool = False
    permits_transcript_text: bool = False
    compliance_notes: tuple[str, ...] = Field(default_factory=tuple)


class SourcePolicyRule(CartCartBaseModel):
    action: SourcePolicyAction
    reason: str = Field(min_length=1, max_length=500)
    domain: str | None = Field(default=None, min_length=1, max_length=253)
    source_type: SourceType | None = None

    @model_validator(mode="after")
    def _requires_a_selector(self) -> "SourcePolicyRule":
        if self.domain is None and self.source_type is None:
            raise ValueError("source policy rules require domain or source_type.")
        return self


class SourceAllowAvoidPolicy(CartCartBaseModel):
    allow: tuple[SourcePolicyRule, ...] = Field(default_factory=tuple)
    avoid: tuple[SourcePolicyRule, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _rules_must_match_their_bucket(self) -> "SourceAllowAvoidPolicy":
        if any(rule.action != SourcePolicyAction.ALLOW for rule in self.allow):
            raise ValueError("allow policy rules must use action='allow'.")
        if any(rule.action != SourcePolicyAction.AVOID for rule in self.avoid):
            raise ValueError("avoid policy rules must use action='avoid'.")
        return self


class SearchProviderOptions(CartCartBaseModel):
    region_code: RegionCode | None = None
    category: str | None = Field(default=None, min_length=1, max_length=200)
    max_results: int = Field(default=10, ge=1, le=50)
    source_policy: SourceAllowAvoidPolicy = Field(
        default_factory=SourceAllowAvoidPolicy
    )


class ExtractionProviderOptions(CartCartBaseModel):
    source_policy: SourceAllowAvoidPolicy = Field(
        default_factory=SourceAllowAvoidPolicy
    )


class ShoppingProviderOptions(CartCartBaseModel):
    region_code: RegionCode | None = None
    category: str | None = Field(default=None, min_length=1, max_length=200)
    max_results: int = Field(default=10, ge=1, le=50)
    source_policy: SourceAllowAvoidPolicy = Field(
        default_factory=SourceAllowAvoidPolicy
    )


class VideoSearchProviderOptions(CartCartBaseModel):
    region_code: RegionCode | None = None
    max_results: int = Field(default=10, ge=1, le=50)
    source_policy: SourceAllowAvoidPolicy = Field(
        default_factory=SourceAllowAvoidPolicy
    )


class TranscriptProviderOptions(CartCartBaseModel):
    language: str | None = Field(default=None, min_length=2, max_length=35)
    source_policy: SourceAllowAvoidPolicy = Field(
        default_factory=SourceAllowAvoidPolicy
    )


class MarketplaceAvailabilityProviderOptions(CartCartBaseModel):
    region_code: RegionCode | None = None
    source_policy: SourceAllowAvoidPolicy = Field(
        default_factory=SourceAllowAvoidPolicy
    )


class OfficialStoreProviderOptions(CartCartBaseModel):
    region_code: RegionCode | None = None
    source_policy: SourceAllowAvoidPolicy = Field(
        default_factory=SourceAllowAvoidPolicy
    )


class VideoSearchProviderResult(CartCartBaseModel):
    status: ProviderRunStatus
    capabilities: ProviderCapabilityFlags
    bundle: VideoReviewEvidenceBundle | None = None
    notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _succeeded_requires_bundle(self) -> "VideoSearchProviderResult":
        if self.status == ProviderRunStatus.SUCCEEDED and self.bundle is None:
            raise ValueError("successful video search results require a bundle.")
        if self.status != ProviderRunStatus.SUCCEEDED and self.bundle is not None:
            raise ValueError(
                "disabled or unavailable video search results cannot include a bundle."
            )
        return self


class TranscriptProviderResult(CartCartBaseModel):
    status: ProviderRunStatus
    capabilities: ProviderCapabilityFlags
    video: VideoSource
    availability: TranscriptAvailability
    segments: tuple[VideoTranscriptSegment, ...] = Field(default_factory=tuple)
    gap_notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _availability_matches_segments(self) -> "TranscriptProviderResult":
        if self.status == ProviderRunStatus.SUCCEEDED:
            if self.availability in (
                TranscriptAvailability.AVAILABLE,
                TranscriptAvailability.PARTIAL,
            ) and not self.segments:
                raise ValueError("available transcript results require segments.")
            if (
                self.availability == TranscriptAvailability.UNAVAILABLE
                and not self.gap_notes
            ):
                raise ValueError("unavailable transcript results require gap notes.")
        return self


class MarketplaceAvailabilityProviderResult(CartCartBaseModel):
    status: ProviderRunStatus
    capabilities: ProviderCapabilityFlags
    listings: tuple[ProductListing, ...] = Field(default_factory=tuple)
    evidence: tuple[SourceEvidence, ...] = Field(default_factory=tuple)
    notes: tuple[str, ...] = Field(default_factory=tuple)


class OfficialStoreProviderResult(CartCartBaseModel):
    status: ProviderRunStatus
    capabilities: ProviderCapabilityFlags
    source_snapshots: tuple[SourceSnapshot, ...] = Field(default_factory=tuple)
    listings: tuple[ProductListing, ...] = Field(default_factory=tuple)
    evidence: tuple[SourceEvidence, ...] = Field(default_factory=tuple)
    notes: tuple[str, ...] = Field(default_factory=tuple)


class SearchProvider(Protocol):
    async def search(
        self,
        query: SearchQuery,
        options: SearchProviderOptions | None = None,
    ) -> tuple[SearchResult, ...]:
        """Return source candidates for a planned search query."""


class ExtractionProvider(Protocol):
    async def extract(
        self,
        url: AnyHttpUrl,
        options: ExtractionProviderOptions | None = None,
    ) -> SourceSnapshot:
        """Extract a durable source snapshot from a URL."""


class ShoppingProvider(Protocol):
    async def search_products(
        self,
        query: str,
        options: ShoppingProviderOptions | None = None,
    ) -> tuple[ProductListing, ...]:
        """Return shopping listings from an optional shopping-specific provider."""


class VideoSearchProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        """Describe enabled state and compliance boundaries for video search."""

    async def search_videos(
        self,
        query: str,
        options: VideoSearchProviderOptions | None = None,
    ) -> VideoSearchProviderResult:
        """Return video metadata and any metadata-only evidence."""


class TranscriptProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        """Describe enabled state and transcript access compliance boundaries."""

    async def fetch_transcript(
        self,
        video: VideoSource,
        options: TranscriptProviderOptions | None = None,
    ) -> TranscriptProviderResult:
        """Return available transcript segments or explicit transcript gaps."""


class MarketplaceAvailabilityProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        """Describe marketplace lookup capability and compliance boundaries."""

    async def check_availability(
        self,
        product: CanonicalProduct,
        listings: tuple[ProductListing, ...] = (),
        options: MarketplaceAvailabilityProviderOptions | None = None,
    ) -> MarketplaceAvailabilityProviderResult:
        """Return marketplace availability and listing-trust evidence."""


class OfficialStoreProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        """Describe official-store lookup capability and compliance boundaries."""

    async def find_official_sources(
        self,
        product: CanonicalProduct,
        options: OfficialStoreProviderOptions | None = None,
    ) -> OfficialStoreProviderResult:
        """Return official brand/store source snapshots and evidence."""
