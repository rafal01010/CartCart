from enum import StrEnum
from typing import Any

from pydantic import AnyHttpUrl, Field, model_validator

from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.confidence import Confidence, ConfidenceScore
from app.schemas.ids import CandidateId, ListingId, ProductId, SourceId, new_id
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
    WARRANTY = "warranty"
    WARNING = "warning"
    OTHER = "other"


class EvidenceTargetType(StrEnum):
    PRODUCT = "product"
    LISTING = "listing"
    SELLER = "seller"
    CANDIDATE = "candidate"
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


class EvidenceTarget(CartCartBaseModel):
    target_type: EvidenceTargetType
    product_id: ProductId | None = None
    listing_id: ListingId | None = None
    candidate_id: CandidateId | None = None
    seller_name: str | None = Field(default=None, min_length=1, max_length=200)
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
        if (
            self.target_type == EvidenceTargetType.CANDIDATE
            and self.candidate_id is None
        ):
            raise ValueError("candidate evidence targets require candidate_id.")
        if self.target_type == EvidenceTargetType.SOURCE_METADATA:
            if self.source_id is None:
                raise ValueError("source metadata evidence targets require source_id.")
            if any(
                (
                    self.product_id,
                    self.listing_id,
                    self.candidate_id,
                    self.seller_name,
                )
            ):
                raise ValueError(
                    "source metadata evidence targets cannot identify products, "
                    "listings, sellers, or candidates."
                )
        return self


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
    channel_id: str | None = Field(default=None, min_length=1, max_length=128)
    channel_name: str | None = Field(default=None, min_length=1, max_length=200)
    published_at: Timestamp | None = None
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


class SourceSnapshot(VersionedSchema):
    source_id: SourceId = Field(default_factory=new_id)
    url: AnyHttpUrl
    source_type: SourceType
    provider: ProviderMetadata
    title: str | None = Field(default=None, min_length=1, max_length=300)
    captured_at: Timestamp = Field(default_factory=utc_now)
    extraction_status: ExtractionStatus = ExtractionStatus.NOT_ATTEMPTED
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
                segment = segment_by_id.get(segment_id)
                if segment is None:
                    raise ValueError(
                        "video review evidence must reference bundled transcript segments."
                    )
                if segment.video_id != item.video_id:
                    raise ValueError(
                        "video review evidence cannot cite another video's transcript segment."
                    )
        return self
