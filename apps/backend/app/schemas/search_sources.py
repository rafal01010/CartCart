from enum import StrEnum
from typing import Any

from pydantic import AnyHttpUrl, Field, model_validator

from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.confidence import Confidence, ConfidenceScore
from app.schemas.ids import CandidateId, ListingId, ProductId, SourceId, new_id
from app.schemas.intake import ShoppingBrief
from app.schemas.money import Money
from app.schemas.regions import RegionCode
from app.schemas.source_references import SourceReference
from app.schemas.timestamps import Timestamp, utc_now


class SearchIntent(StrEnum):
    DISCOVERY = "discovery"
    PRICE_CHECK = "price_check"
    REVIEW = "review"
    OFFICIAL_SOURCE = "official_source"
    VIDEO_REVIEW = "video_review"
    TRUST_CHECK = "trust_check"


class SourceType(StrEnum):
    PRODUCT_PAGE = "product_page"
    RETAILER_LISTING = "retailer_listing"
    OFFICIAL_BRAND_PAGE = "official_brand_page"
    PROFESSIONAL_REVIEW = "professional_review"
    COMMUNITY_DISCUSSION = "community_discussion"
    VIDEO = "video"
    SEARCH_RESULT = "search_result"
    OTHER = "other"


class ExtractionStatus(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    EXCLUDED = "excluded"


class EvidenceType(StrEnum):
    PRODUCT_SPEC = "product_spec"
    PRICE = "price"
    AVAILABILITY = "availability"
    SELLER_TRUST = "seller_trust"
    REVIEW_CLAIM = "review_claim"
    VIDEO_CLAIM = "video_claim"
    COMMUNITY_CLAIM = "community_claim"
    MARKETPLACE_PRODUCT_FACT = "marketplace_product_fact"
    LISTING_IDENTITY = "listing_identity"
    REVIEW_SUMMARY = "review_summary"
    OFFICIAL_STORE_FACT = "official_store_fact"
    REGION_AVAILABILITY = "region_availability"
    WARRANTY = "warranty"
    WARNING = "warning"
    OTHER = "other"


class EvidenceTargetType(StrEnum):
    PRODUCT = "product"
    LISTING = "listing"
    SELLER = "seller"
    REVIEW = "review"
    CANDIDATE = "candidate"
    REGION = "region"
    SOURCE_METADATA = "source_metadata"


class SourceQualityLevel(StrEnum):
    WEAK = "weak"
    MIXED = "mixed"
    ADEQUATE = "adequate"
    STRONG = "strong"
    UNKNOWN = "unknown"


class TranscriptAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    NOT_CHECKED = "not_checked"
    RESTRICTED = "restricted"
    NOT_APPLICABLE = "not_applicable"


class ChannelSignal(StrEnum):
    REVIEW_FOCUSED = "review_focused"
    BRAND_OWNED = "brand_owned"
    RETAILER_OWNED = "retailer_owned"
    SPONSORSHIP_DISCLOSED = "sponsorship_disclosed"
    AFFILIATE_LINKS_DISCLOSED = "affiliate_links_disclosed"
    FREQUENT_SPONSORED_CONTENT = "frequent_sponsored_content"
    LOW_DISCLOSURE_CLARITY = "low_disclosure_clarity"
    UNKNOWN = "unknown"


class SourceIntelligenceCapability(StrEnum):
    VIDEO_REVIEW = "video_review"
    COMMUNITY_DISCUSSION = "community_discussion"
    AMAZON_PRODUCT_LISTING_REVIEW = "amazon_product_listing_review"
    IKEA_REGIONAL_OFFICIAL_STORE = "ikea_regional_official_store"


class AmazonEvidenceFactType(StrEnum):
    PRODUCT_PAGE_FACT = "product_page_fact"
    LISTING_IDENTITY = "listing_identity"
    SELLER_FULFILLMENT = "seller_fulfillment"
    REVIEW_SUMMARY = "review_summary"
    REVIEW_QUALITY_WARNING = "review_quality_warning"
    REGIONAL_AVAILABILITY = "regional_availability"
    PRICE = "price"
    WARRANTY_OR_RETURN = "warranty_or_return"
    MARKETPLACE_WARNING = "marketplace_warning"


class IKEAEvidenceFactType(StrEnum):
    OFFICIAL_PRODUCT_FACT = "official_product_fact"
    REGIONAL_PRICE = "regional_price"
    REGIONAL_AVAILABILITY = "regional_availability"
    STORE_DELIVERY_CONTEXT = "store_delivery_context"


class RegionalStoreAvailability(StrEnum):
    AVAILABLE = "available"
    OUT_OF_STOCK = "out_of_stock"
    DELIVERY_UNAVAILABLE = "delivery_unavailable"
    PICKUP_ONLY = "pickup_only"
    REGION_UNSUPPORTED = "region_unsupported"
    UNKNOWN = "unknown"


class ConflictSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MATERIAL = "material"


class ProviderMetadata(CartCartBaseModel):
    provider_name: str = Field(min_length=1, max_length=120)
    provider_result_id: str | None = Field(default=None, min_length=1, max_length=300)
    query_id: str | None = Field(default=None, min_length=1, max_length=300)
    raw: dict[str, Any] = Field(default_factory=dict)


class SourceQuality(CartCartBaseModel):
    level: SourceQualityLevel
    score: ConfidenceScore | None = None
    rationale: str | None = Field(default=None, min_length=1, max_length=500)


class RawSourceSnapshotArtifact(CartCartBaseModel):
    path: str = Field(min_length=1, max_length=2048)
    content_type: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExtractedPageContent(CartCartBaseModel):
    text: str = Field(min_length=1)
    extractor: str = Field(min_length=1, max_length=120)
    author: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    site_name: str | None = Field(default=None, min_length=1, max_length=300)
    published_date: str | None = Field(default=None, min_length=1, max_length=35)
    language: str | None = Field(default=None, min_length=2, max_length=35)
    word_count: int = Field(ge=1)


class EvidenceTarget(CartCartBaseModel):
    target_type: EvidenceTargetType
    product_id: ProductId | None = None
    listing_id: ListingId | None = None
    candidate_id: CandidateId | None = None
    seller_name: str | None = Field(default=None, min_length=1, max_length=200)
    review_id: str | None = Field(default=None, min_length=1, max_length=200)
    region_code: RegionCode | None = None
    source_id: SourceId | None = None

    @model_validator(mode="after")
    def _target_must_identify_declared_entity(self) -> "EvidenceTarget":
        if (
            self.target_type == EvidenceTargetType.PRODUCT
            and self.product_id is None
        ):
            raise ValueError("product evidence targets require product_id.")
        if (
            self.target_type == EvidenceTargetType.LISTING
            and self.listing_id is None
        ):
            raise ValueError("listing evidence targets require listing_id.")
        if self.target_type == EvidenceTargetType.SELLER and not (
            self.listing_id or self.seller_name
        ):
            raise ValueError(
                "seller evidence targets require listing_id or seller_name."
            )
        if self.target_type == EvidenceTargetType.REVIEW and self.review_id is None:
            raise ValueError("review evidence targets require review_id.")
        if (
            self.target_type == EvidenceTargetType.CANDIDATE
            and self.candidate_id is None
        ):
            raise ValueError("candidate evidence targets require candidate_id.")
        if self.target_type == EvidenceTargetType.REGION and self.region_code is None:
            raise ValueError("region evidence targets require region_code.")
        if self.target_type == EvidenceTargetType.SOURCE_METADATA:
            if self.source_id is None:
                raise ValueError("source metadata evidence targets require source_id.")
            if any(
                (
                    self.product_id,
                    self.listing_id,
                    self.candidate_id,
                    self.seller_name,
                    self.review_id,
                    self.region_code,
                )
            ):
                raise ValueError(
                    "source metadata evidence targets cannot identify products, "
                    "listings, sellers, reviews, regions, or candidates."
                )
        return self


class SourceIntelligenceCapabilityDescriptor(CartCartBaseModel):
    capability: SourceIntelligenceCapability
    provider_name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool = True
    official_access: bool | None = None
    user_authorized_access: bool | None = None
    domain_scoped_search: bool | None = None
    marketplace_product_support: bool | None = None
    marketplace_review_support: bool | None = None
    regional_official_store_support: bool | None = None
    compliance_notes: tuple[str, ...] = Field(default_factory=tuple)


class ReusableSourceIntelligenceRequest(VersionedSchema):
    request_id: SourceId = Field(default_factory=new_id)
    brief: ShoppingBrief
    target_region_code: RegionCode | None = None
    product_ids: tuple[ProductId, ...] = Field(default_factory=tuple)
    listing_ids: tuple[ListingId, ...] = Field(default_factory=tuple)
    candidate_ids: tuple[CandidateId, ...] = Field(default_factory=tuple)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    query_hints: tuple[str, ...] = Field(default_factory=tuple)
    requested_capabilities: tuple[SourceIntelligenceCapability, ...] = Field(
        min_length=1
    )
    allowed_capabilities: tuple[SourceIntelligenceCapabilityDescriptor, ...] = Field(
        default_factory=tuple
    )


class SearchQuery(CartCartBaseModel):
    query: str = Field(min_length=1, max_length=500)
    intent: SearchIntent
    region_code: RegionCode | None = None
    required_source_types: tuple[SourceType, ...] = Field(default_factory=tuple)


class SearchPlan(VersionedSchema):
    queries: tuple[SearchQuery, ...] = Field(min_length=1)
    rationale: str | None = Field(default=None, min_length=1, max_length=1000)


class SearchResult(CartCartBaseModel):
    source_id: SourceId = Field(default_factory=new_id)
    query: SearchQuery
    url: AnyHttpUrl
    title: str = Field(min_length=1, max_length=300)
    snippet: str | None = Field(default=None, min_length=1, max_length=1000)
    source_type: SourceType = SourceType.SEARCH_RESULT
    provider: ProviderMetadata
    quality: SourceQuality = Field(
        default_factory=lambda: SourceQuality(level=SourceQualityLevel.UNKNOWN)
    )


class VideoSource(CartCartBaseModel):
    video_id: str = Field(min_length=1, max_length=128)
    url: AnyHttpUrl
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, min_length=1, max_length=5000)
    channel_id: str | None = Field(default=None, min_length=1, max_length=128)
    channel_name: str | None = Field(default=None, min_length=1, max_length=200)
    published_at: Timestamp | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    transcript_availability: TranscriptAvailability = TranscriptAvailability.NOT_CHECKED
    channel_signals: tuple[ChannelSignal, ...] = Field(default_factory=tuple)
    sponsorship_disclosed: bool | None = None
    affiliate_links_disclosed: bool | None = None
    affiliate_bias_risk: Confidence | None = None
    bias_notes: str | None = Field(default=None, min_length=1, max_length=1000)


class TimestampReference(CartCartBaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    label: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _end_must_not_precede_start(self) -> "TimestampReference":
        if self.end_seconds is not None and self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds cannot be earlier than start_seconds.")
        return self


class VideoTranscriptSegment(CartCartBaseModel):
    segment_id: SourceId = Field(default_factory=new_id)
    video_id: str = Field(min_length=1, max_length=128)
    start_seconds: float = Field(ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    language: str | None = Field(default=None, min_length=2, max_length=35)
    text: str | None = Field(default=None, min_length=1, max_length=5000)
    availability: TranscriptAvailability = TranscriptAvailability.AVAILABLE
    gap_reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def _validate_segment_timing_and_gap(self) -> "VideoTranscriptSegment":
        if self.end_seconds is not None and self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds cannot be earlier than start_seconds.")
        if self.text is None:
            if self.availability == TranscriptAvailability.AVAILABLE:
                raise ValueError("available transcript segments require text.")
            if self.gap_reason is None:
                raise ValueError("transcript gaps require a gap_reason.")
        if self.text is not None and self.gap_reason is not None:
            raise ValueError(
                "transcript segments cannot have both text and gap_reason."
            )
        return self


class VideoReviewEvidence(CartCartBaseModel):
    evidence_id: SourceId = Field(default_factory=new_id)
    source_id: SourceId
    target: EvidenceTarget
    video_id: str = Field(min_length=1, max_length=128)
    claim: str = Field(min_length=1, max_length=2000)
    confidence: Confidence
    source_quality: SourceQuality
    timestamp_references: tuple[TimestampReference, ...] = Field(default_factory=tuple)
    transcript_segment_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    metadata_only: bool = False
    transcript_gap: str | None = Field(default=None, min_length=1, max_length=1000)
    sponsorship_disclosed: bool | None = None
    affiliate_links_disclosed: bool | None = None
    affiliate_bias_risk: Confidence | None = None

    @model_validator(mode="after")
    def _validate_evidence_basis(self) -> "VideoReviewEvidence":
        if (
            self.target.target_type == EvidenceTargetType.SOURCE_METADATA
            and self.target.source_id != self.source_id
        ):
            raise ValueError("source metadata evidence target must match source_id.")
        if (
            self.metadata_only
            and self.target.target_type != EvidenceTargetType.SOURCE_METADATA
        ):
            raise ValueError("metadata-only video evidence must target source metadata.")
        if self.metadata_only and (
            self.timestamp_references or self.transcript_segment_ids
        ):
            raise ValueError(
                "metadata-only video evidence cannot cite timestamps or transcript segments."
            )
        if not self.metadata_only and not (
            self.timestamp_references
            or self.transcript_segment_ids
            or self.transcript_gap
        ):
            raise ValueError(
                "video evidence requires timestamps, transcript segment IDs, "
                "a transcript gap, or metadata_only=true."
            )
        return self


class SourceEvidenceGap(CartCartBaseModel):
    gap_id: SourceId = Field(default_factory=new_id)
    capability: SourceIntelligenceCapability
    target: EvidenceTarget | None = None
    source_id: SourceId | None = None
    summary: str = Field(min_length=1, max_length=1000)
    reason: str | None = Field(default=None, min_length=1, max_length=1000)
    source_quality: SourceQuality = Field(
        default_factory=lambda: SourceQuality(level=SourceQualityLevel.UNKNOWN)
    )
    confidence: Confidence | None = None


class CommunityDiscussionContext(CartCartBaseModel):
    source_id: SourceId
    url: AnyHttpUrl
    platform: str = Field(default="reddit", min_length=1, max_length=80)
    community_name: str | None = Field(default=None, min_length=1, max_length=120)
    thread_id: str | None = Field(default=None, min_length=1, max_length=200)
    thread_title: str | None = Field(default=None, min_length=1, max_length=300)
    comment_id: str | None = Field(default=None, min_length=1, max_length=200)
    posted_at: Timestamp | None = None
    engagement_score: int | None = Field(default=None, ge=0)
    comment_count: int | None = Field(default=None, ge=0)
    extracted_public_summary: str | None = Field(
        default=None,
        min_length=1,
        max_length=2000,
    )


class CommunityDiscussionEvidence(CartCartBaseModel):
    evidence_id: SourceId = Field(default_factory=new_id)
    source_id: SourceId
    target: EvidenceTarget
    claim: str = Field(min_length=1, max_length=2000)
    confidence: Confidence
    source_quality: SourceQuality
    context_source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    recurring_signal: bool = False
    qualitative_signal: bool = True
    evidence_quality_warnings: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_source_metadata_target(self) -> "CommunityDiscussionEvidence":
        if (
            self.target.target_type == EvidenceTargetType.SOURCE_METADATA
            and self.target.source_id != self.source_id
        ):
            raise ValueError("source metadata evidence target must match source_id.")
        return self


class AmazonListingContext(CartCartBaseModel):
    source_id: SourceId
    marketplace_name: str = Field(min_length=1, max_length=120)
    marketplace_domain: str = Field(min_length=1, max_length=200)
    marketplace_country_code: RegionCode | None = None
    listing_url: AnyHttpUrl
    asin: str | None = Field(default=None, min_length=1, max_length=20)
    external_listing_id: str | None = Field(default=None, min_length=1, max_length=200)
    product_title: str | None = Field(default=None, min_length=1, max_length=300)
    variant_label: str | None = Field(default=None, min_length=1, max_length=200)
    seller_name: str | None = Field(default=None, min_length=1, max_length=200)
    fulfillment: str | None = Field(default=None, min_length=1, max_length=200)
    ships_to_region_code: RegionCode | None = None
    ships_to_region: bool | None = None
    review_count: int | None = Field(default=None, ge=0)
    average_rating: float | None = Field(default=None, ge=0, le=5)


class AmazonProductEvidence(CartCartBaseModel):
    evidence_id: SourceId = Field(default_factory=new_id)
    source_id: SourceId
    target: EvidenceTarget
    fact_type: AmazonEvidenceFactType
    claim: str = Field(min_length=1, max_length=2000)
    confidence: Confidence
    source_quality: SourceQuality
    listing_context_source_id: SourceId | None = None
    evidence_quality_warnings: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_fact_target_boundary(self) -> "AmazonProductEvidence":
        if (
            self.target.target_type == EvidenceTargetType.SOURCE_METADATA
            and self.target.source_id != self.source_id
        ):
            raise ValueError("source metadata evidence target must match source_id.")
        if (
            self.fact_type == AmazonEvidenceFactType.PRODUCT_PAGE_FACT
            and self.target.target_type != EvidenceTargetType.PRODUCT
        ):
            raise ValueError("Amazon product-page facts must target a product.")
        if (
            self.fact_type == AmazonEvidenceFactType.LISTING_IDENTITY
            and self.target.target_type != EvidenceTargetType.LISTING
        ):
            raise ValueError("Amazon listing identity facts must target a listing.")
        if (
            self.fact_type == AmazonEvidenceFactType.SELLER_FULFILLMENT
            and self.target.target_type != EvidenceTargetType.SELLER
        ):
            raise ValueError("Amazon seller/fulfillment facts must target a seller.")
        if self.fact_type in (
            AmazonEvidenceFactType.REVIEW_SUMMARY,
            AmazonEvidenceFactType.REVIEW_QUALITY_WARNING,
        ) and self.target.target_type != EvidenceTargetType.REVIEW:
            raise ValueError("Amazon review facts must target review evidence.")
        if (
            self.fact_type == AmazonEvidenceFactType.REGIONAL_AVAILABILITY
            and self.target.target_type != EvidenceTargetType.REGION
        ):
            raise ValueError("Amazon regional availability facts must target a region.")
        return self


class IKEAStoreContext(CartCartBaseModel):
    source_id: SourceId
    country_code: RegionCode
    official_url: AnyHttpUrl
    product_code: str | None = Field(default=None, min_length=1, max_length=120)
    product_name: str | None = Field(default=None, min_length=1, max_length=300)
    store_name: str | None = Field(default=None, min_length=1, max_length=200)
    delivery_area: str | None = Field(default=None, min_length=1, max_length=200)
    price: Money | None = None
    availability: RegionalStoreAvailability = RegionalStoreAvailability.UNKNOWN


class IKEAStoreEvidence(CartCartBaseModel):
    evidence_id: SourceId = Field(default_factory=new_id)
    source_id: SourceId
    target: EvidenceTarget
    fact_type: IKEAEvidenceFactType
    claim: str = Field(min_length=1, max_length=2000)
    confidence: Confidence
    source_quality: SourceQuality
    store_context_source_id: SourceId | None = None
    evidence_quality_warnings: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_fact_target_boundary(self) -> "IKEAStoreEvidence":
        if (
            self.target.target_type == EvidenceTargetType.SOURCE_METADATA
            and self.target.source_id != self.source_id
        ):
            raise ValueError("source metadata evidence target must match source_id.")
        if (
            self.fact_type == IKEAEvidenceFactType.OFFICIAL_PRODUCT_FACT
            and self.target.target_type != EvidenceTargetType.PRODUCT
        ):
            raise ValueError("IKEA official product facts must target a product.")
        if self.fact_type in (
            IKEAEvidenceFactType.REGIONAL_PRICE,
            IKEAEvidenceFactType.REGIONAL_AVAILABILITY,
            IKEAEvidenceFactType.STORE_DELIVERY_CONTEXT,
        ) and self.target.target_type != EvidenceTargetType.REGION:
            raise ValueError("IKEA regional store facts must target a region.")
        return self


class SourceSnapshot(VersionedSchema):
    source_id: SourceId = Field(default_factory=new_id)
    url: AnyHttpUrl
    source_type: SourceType
    provider: ProviderMetadata
    title: str | None = Field(default=None, min_length=1, max_length=300)
    captured_at: Timestamp = Field(default_factory=utc_now)
    extraction_status: ExtractionStatus = ExtractionStatus.NOT_ATTEMPTED
    http_status_code: int | None = Field(default=None, ge=100, le=599)
    raw_artifact: RawSourceSnapshotArtifact | None = None
    extracted_content: ExtractedPageContent | None = None
    quality: SourceQuality = Field(
        default_factory=lambda: SourceQuality(level=SourceQualityLevel.UNKNOWN)
    )
    video: VideoSource | None = None

    @model_validator(mode="after")
    def _video_source_type_requires_video_details(self) -> "SourceSnapshot":
        if self.source_type == SourceType.VIDEO and self.video is None:
            raise ValueError("video details are required for video source snapshots.")
        return self


class SourceEvidence(CartCartBaseModel):
    evidence_id: SourceId = Field(default_factory=new_id)
    source_id: SourceId
    target: EvidenceTarget
    evidence_type: EvidenceType
    claim: str = Field(min_length=1, max_length=2000)
    confidence: Confidence
    source_quality: SourceQuality
    timestamp_references: tuple[TimestampReference, ...] = Field(default_factory=tuple)
    video: VideoSource | None = None

    @model_validator(mode="after")
    def _video_evidence_requires_video_context(self) -> "SourceEvidence":
        if (
            self.target.target_type == EvidenceTargetType.SOURCE_METADATA
            and self.target.source_id != self.source_id
        ):
            raise ValueError("source metadata evidence target must match source_id.")
        if (
            self.evidence_type == EvidenceType.VIDEO_CLAIM
            or self.timestamp_references
        ) and self.video is None:
            raise ValueError("video context is required for video or timestamped evidence.")
        return self


class EvidenceConflict(CartCartBaseModel):
    conflict_id: SourceId = Field(default_factory=new_id)
    evidence_ids: tuple[SourceId, ...] = Field(min_length=2)
    summary: str = Field(min_length=1, max_length=1000)
    severity: ConflictSeverity
    affects_decision: bool = False


class VideoReviewEvidenceBundle(VersionedSchema):
    bundle_id: SourceId = Field(default_factory=new_id)
    videos: tuple[VideoSource, ...] = Field(min_length=1)
    source_references: tuple[SourceReference, ...] = Field(min_length=1)
    transcript_segments: tuple[VideoTranscriptSegment, ...] = Field(
        default_factory=tuple
    )
    evidence: tuple[VideoReviewEvidence, ...] = Field(default_factory=tuple)
    transcript_gap_notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_bundle_relationships(self) -> "VideoReviewEvidenceBundle":
        video_ids = {video.video_id for video in self.videos}
        if len(video_ids) != len(self.videos):
            raise ValueError("video IDs must be unique within a video evidence bundle.")

        source_ids = {reference.source_id for reference in self.source_references}
        if len(source_ids) != len(self.source_references):
            raise ValueError(
                "source reference IDs must be unique within a video evidence bundle."
            )

        segment_by_id = {
            segment.segment_id: segment for segment in self.transcript_segments
        }
        if len(segment_by_id) != len(self.transcript_segments):
            raise ValueError(
                "transcript segment IDs must be unique within a video evidence bundle."
            )

        for segment in self.transcript_segments:
            if segment.video_id not in video_ids:
                raise ValueError("transcript segments must reference bundled videos.")

        for item in self.evidence:
            if item.video_id not in video_ids:
                raise ValueError("video review evidence must reference a bundled video.")
            if item.source_id not in source_ids:
                raise ValueError("video review evidence must reference a bundled source.")
            for segment_id in item.transcript_segment_ids:
                referenced_segment = segment_by_id.get(segment_id)
                if referenced_segment is None:
                    raise ValueError(
                        "video review evidence must reference bundled transcript segments."
                    )
                if referenced_segment.video_id != item.video_id:
                    raise ValueError(
                        "video review evidence cannot cite another video's transcript segment."
                    )
        return self


class CommunityDiscussionEvidenceBundle(VersionedSchema):
    bundle_id: SourceId = Field(default_factory=new_id)
    source_references: tuple[SourceReference, ...] = Field(default_factory=tuple)
    discussions: tuple[CommunityDiscussionContext, ...] = Field(default_factory=tuple)
    evidence: tuple[CommunityDiscussionEvidence, ...] = Field(default_factory=tuple)
    evidence_gaps: tuple[SourceEvidenceGap, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_bundle_relationships(self) -> "CommunityDiscussionEvidenceBundle":
        source_ids = {reference.source_id for reference in self.source_references}
        if len(source_ids) != len(self.source_references):
            raise ValueError(
                "source reference IDs must be unique within a community evidence bundle."
            )

        discussion_source_ids = {discussion.source_id for discussion in self.discussions}
        if len(discussion_source_ids) != len(self.discussions):
            raise ValueError(
                "discussion source IDs must be unique within a community evidence bundle."
            )
        if not discussion_source_ids.issubset(source_ids):
            raise ValueError("community discussions must reference bundled sources.")

        for item in self.evidence:
            if item.source_id not in source_ids:
                raise ValueError(
                    "community evidence must reference a bundled source."
                )
            for context_source_id in item.context_source_ids:
                if context_source_id not in discussion_source_ids:
                    raise ValueError(
                        "community evidence must reference bundled discussion context."
                    )
        for gap in self.evidence_gaps:
            if gap.source_id is not None and gap.source_id not in source_ids:
                raise ValueError("evidence gaps can only cite bundled sources.")
        return self


class AmazonProductEvidenceBundle(VersionedSchema):
    bundle_id: SourceId = Field(default_factory=new_id)
    source_references: tuple[SourceReference, ...] = Field(default_factory=tuple)
    listing_contexts: tuple[AmazonListingContext, ...] = Field(default_factory=tuple)
    evidence: tuple[AmazonProductEvidence, ...] = Field(default_factory=tuple)
    evidence_gaps: tuple[SourceEvidenceGap, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_bundle_relationships(self) -> "AmazonProductEvidenceBundle":
        source_ids = {reference.source_id for reference in self.source_references}
        if len(source_ids) != len(self.source_references):
            raise ValueError(
                "source reference IDs must be unique within an Amazon evidence bundle."
            )

        context_source_ids = {context.source_id for context in self.listing_contexts}
        if len(context_source_ids) != len(self.listing_contexts):
            raise ValueError(
                "listing context source IDs must be unique within an Amazon evidence bundle."
            )
        if not context_source_ids.issubset(source_ids):
            raise ValueError("Amazon listing contexts must reference bundled sources.")

        for item in self.evidence:
            if item.source_id not in source_ids:
                raise ValueError("Amazon evidence must reference a bundled source.")
            if (
                item.listing_context_source_id is not None
                and item.listing_context_source_id not in context_source_ids
            ):
                raise ValueError(
                    "Amazon evidence must reference bundled listing context."
                )
        for gap in self.evidence_gaps:
            if gap.source_id is not None and gap.source_id not in source_ids:
                raise ValueError("evidence gaps can only cite bundled sources.")
        return self


class IKEAStoreEvidenceBundle(VersionedSchema):
    bundle_id: SourceId = Field(default_factory=new_id)
    source_references: tuple[SourceReference, ...] = Field(default_factory=tuple)
    store_contexts: tuple[IKEAStoreContext, ...] = Field(default_factory=tuple)
    evidence: tuple[IKEAStoreEvidence, ...] = Field(default_factory=tuple)
    evidence_gaps: tuple[SourceEvidenceGap, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_bundle_relationships(self) -> "IKEAStoreEvidenceBundle":
        source_ids = {reference.source_id for reference in self.source_references}
        if len(source_ids) != len(self.source_references):
            raise ValueError(
                "source reference IDs must be unique within an IKEA evidence bundle."
            )

        context_source_ids = {context.source_id for context in self.store_contexts}
        if len(context_source_ids) != len(self.store_contexts):
            raise ValueError(
                "store context source IDs must be unique within an IKEA evidence bundle."
            )
        if not context_source_ids.issubset(source_ids):
            raise ValueError("IKEA store contexts must reference bundled sources.")

        for item in self.evidence:
            if item.source_id not in source_ids:
                raise ValueError("IKEA evidence must reference a bundled source.")
            if (
                item.store_context_source_id is not None
                and item.store_context_source_id not in context_source_ids
            ):
                raise ValueError("IKEA evidence must reference bundled store context.")
        for gap in self.evidence_gaps:
            if gap.source_id is not None and gap.source_id not in source_ids:
                raise ValueError("evidence gaps can only cite bundled sources.")
        return self
