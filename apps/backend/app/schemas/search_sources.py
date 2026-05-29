from enum import StrEnum
from typing import Any

from pydantic import AnyHttpUrl, Field, model_validator

from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.confidence import Confidence, ConfidenceScore
from app.schemas.ids import SourceId, new_id
from app.schemas.regions import RegionCode
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


class SourceQualityLevel(StrEnum):
    WEAK = "weak"
    MIXED = "mixed"
    ADEQUATE = "adequate"
    STRONG = "strong"
    UNKNOWN = "unknown"


class TranscriptAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_CHECKED = "not_checked"
    RESTRICTED = "restricted"
    NOT_APPLICABLE = "not_applicable"


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


class TimestampReference(CartCartBaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    label: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _end_must_not_precede_start(self) -> "TimestampReference":
        if self.end_seconds is not None and self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds cannot be earlier than start_seconds.")
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
    evidence_type: EvidenceType
    claim: str = Field(min_length=1, max_length=2000)
    confidence: Confidence
    source_quality: SourceQuality
    timestamp_references: tuple[TimestampReference, ...] = Field(default_factory=tuple)
    video: VideoSource | None = None

    @model_validator(mode="after")
    def _video_evidence_requires_video_context(self) -> "SourceEvidence":
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
