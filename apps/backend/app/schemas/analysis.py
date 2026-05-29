from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.confidence import Confidence, ConfidenceScore
from app.schemas.ids import CandidateId, ListingId, ProductId, SourceId, new_id
from app.schemas.timestamps import Timestamp, utc_now


class DeduplicationOutcome(StrEnum):
    DUPLICATE = "duplicate"
    DISTINCT = "distinct"
    UNCERTAIN = "uncertain"


class ListingTrustLevel(StrEnum):
    STRONG = "strong"
    REASONABLE = "reasonable"
    MIXED = "mixed"
    WEAK = "weak"
    SUSPICIOUS = "suspicious"
    UNKNOWN = "unknown"


class RecommendationMode(StrEnum):
    BEST_OVERALL = "best_overall"
    BEST_VALUE = "best_value"
    WITHIN_BUDGET = "within_budget"
    STRETCH_PICK = "stretch_pick"
    RUNNER_UP = "runner_up"


class RejectionSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKING = "blocking"


class DeduplicationDecision(VersionedSchema):
    decision_id: CandidateId = Field(default_factory=new_id)
    candidate_ids: tuple[CandidateId, ...] = Field(min_length=2)
    outcome: DeduplicationOutcome
    canonical_product_id: ProductId | None = None
    confidence: Confidence
    rationale: str = Field(min_length=1, max_length=1000)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _duplicate_requires_canonical_product(self) -> "DeduplicationDecision":
        if (
            self.outcome == DeduplicationOutcome.DUPLICATE
            and self.canonical_product_id is None
        ):
            raise ValueError("duplicate decisions require a canonical_product_id.")
        return self


class ListingTrustAssessment(VersionedSchema):
    listing_id: ListingId
    level: ListingTrustLevel
    confidence: Confidence
    summary: str = Field(min_length=1, max_length=1000)
    red_flags: tuple[str, ...] = Field(default_factory=tuple)
    positive_signals: tuple[str, ...] = Field(default_factory=tuple)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    assessed_at: Timestamp = Field(default_factory=utc_now)


class CategoryAnalysis(VersionedSchema):
    product_id: ProductId
    listing_ids: tuple[ListingId, ...] = Field(default_factory=tuple)
    category: str = Field(min_length=1, max_length=200)
    fit_summary: str = Field(min_length=1, max_length=1500)
    strengths: tuple[str, ...] = Field(default_factory=tuple)
    weaknesses: tuple[str, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    confidence: Confidence
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)


class ComparisonCriterion(CartCartBaseModel):
    name: str = Field(min_length=1, max_length=120)
    weight: ConfidenceScore | None = None
    higher_is_better: bool = True


class ComparisonRow(CartCartBaseModel):
    product_id: ProductId
    listing_id: ListingId | None = None
    scores: dict[str, ConfidenceScore] = Field(default_factory=dict)
    summary: str | None = Field(default=None, min_length=1, max_length=1000)


class ComparisonMatrix(VersionedSchema):
    criteria: tuple[ComparisonCriterion, ...] = Field(min_length=1)
    rows: tuple[ComparisonRow, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _rows_must_use_known_criteria(self) -> "ComparisonMatrix":
        criterion_names = {criterion.name for criterion in self.criteria}
        if len(criterion_names) != len(self.criteria):
            raise ValueError("comparison criteria names must be unique.")
        for row in self.rows:
            unknown_scores = set(row.scores) - criterion_names
            if unknown_scores:
                raise ValueError("comparison row scores must use declared criteria.")
        return self


class RecommendationModeResult(CartCartBaseModel):
    mode: RecommendationMode
    product_id: ProductId
    listing_id: ListingId | None = None
    title: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=1500)
    confidence: Confidence
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)


class RejectedItem(CartCartBaseModel):
    product_id: ProductId | None = None
    listing_id: ListingId | None = None
    reason: str = Field(min_length=1, max_length=1000)
    severity: RejectionSeverity = RejectionSeverity.MEDIUM
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _requires_rejected_target(self) -> "RejectedItem":
        if self.product_id is None and self.listing_id is None:
            raise ValueError("rejected items require a product_id or listing_id.")
        return self


class RecommendationBundle(VersionedSchema):
    bundle_id: CandidateId = Field(default_factory=new_id)
    final_product_id: ProductId | None = None
    final_listing_id: ListingId | None = None
    no_strong_buy: bool = False
    no_strong_buy_reason: str | None = Field(
        default=None, min_length=1, max_length=1500
    )
    final_rationale: str | None = Field(default=None, min_length=1, max_length=1500)
    runner_up_product_ids: tuple[ProductId, ...] = Field(default_factory=tuple)
    mode_results: tuple[RecommendationModeResult, ...] = Field(default_factory=tuple)
    comparison_matrix: ComparisonMatrix
    rejected_items: tuple[RejectedItem, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _requires_best_pick_or_no_strong_buy(self) -> "RecommendationBundle":
        has_best_pick = self.final_product_id is not None
        if self.no_strong_buy and has_best_pick:
            raise ValueError(
                "recommendation bundles cannot have both a final pick and no_strong_buy."
            )
        if self.no_strong_buy:
            if self.final_listing_id is not None:
                raise ValueError(
                    "no_strong_buy bundles cannot include a final_listing_id."
                )
            if self.no_strong_buy_reason is None:
                raise ValueError("no_strong_buy bundles require a reason.")
            return self
        if not has_best_pick:
            raise ValueError(
                "recommendation bundles require one final best pick or no_strong_buy=true."
            )
        if self.no_strong_buy_reason is not None:
            raise ValueError(
                "no_strong_buy_reason is only valid when no_strong_buy is true."
            )
        return self
