from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.confidence import Confidence, ConfidenceScore
from app.schemas.ids import CandidateId, ListingId, ProductId, SourceId, new_id
from app.schemas.timestamps import Timestamp, utc_now


RecommendationChoiceGroup = Literal["primary", "runner_up"]


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


class ListingTrustSignalKind(StrEnum):
    SELLER_IDENTITY = "seller_identity"
    ESTABLISHED_RETAILER_SOURCE_TYPE = "established_retailer_source_type"
    REVIEW_COUNT = "review_count"
    RETURN_WARRANTY_CLARITY = "return_warranty_clarity"
    SUSPICIOUS_PRICE = "suspicious_price"
    MISSING_METADATA = "missing_metadata"
    CONTRADICTORY_LISTING_DATA = "contradictory_listing_data"


class ListingTrustSignalPolarity(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"


class ListingTrustSignal(CartCartBaseModel):
    kind: ListingTrustSignalKind
    polarity: ListingTrustSignalPolarity
    strength: ConfidenceScore = 0.5
    summary: str = Field(min_length=1, max_length=1000)
    evidence_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)


class RecommendationMode(StrEnum):
    BEST_OVERALL = "best_overall"
    BEST_VALUE = "best_value"
    WITHIN_BUDGET = "within_budget"
    STRETCH_PICK = "stretch_pick"
    RUNNER_UP = "runner_up"


class RejectionReason(StrEnum):
    SUSPICIOUS_LISTING = "suspicious_listing"
    POOR_FIT = "poor_fit"
    OVERPAYING = "overpaying"
    MISSING_CRITICAL_FEATURE = "missing_critical_feature"
    WEAK_EVIDENCE = "weak_evidence"


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
    evidence_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
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
    trust_signals: tuple[ListingTrustSignal, ...] = Field(default_factory=tuple)
    red_flags: tuple[str, ...] = Field(default_factory=tuple)
    positive_signals: tuple[str, ...] = Field(default_factory=tuple)
    evidence_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
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
    evidence_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)


class ComparisonCriterion(CartCartBaseModel):
    name: str = Field(min_length=1, max_length=120)
    weight: ConfidenceScore | None = None
    higher_is_better: bool = True


class ComparisonRow(CartCartBaseModel):
    product_id: ProductId
    listing_id: ListingId | None = None
    scores: dict[str, ConfidenceScore] = Field(default_factory=dict)
    evidence_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    summary: str | None = Field(default=None, min_length=1, max_length=1000)


class ComparisonMatrix(VersionedSchema):
    criteria: tuple[ComparisonCriterion, ...] = Field(default_factory=tuple)
    rows: tuple[ComparisonRow, ...] = Field(default_factory=tuple)

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
    tradeoffs: tuple[str, ...] = Field(default_factory=tuple)
    unknowns: tuple[str, ...] = Field(default_factory=tuple)
    product_id: ProductId
    listing_id: ListingId | None = None
    title: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=1500)
    confidence: Confidence
    evidence_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)


class RejectedItem(CartCartBaseModel):
    product_id: ProductId | None = None
    listing_id: ListingId | None = None
    reason_code: RejectionReason
    reason: str = Field(min_length=1, max_length=1000)
    severity: RejectionSeverity = RejectionSeverity.MEDIUM
    evidence_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)

    @model_validator(mode="before")
    @classmethod
    def _infer_legacy_reason_code(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if data.get("reason_code"):
            return data
        reason = data.get("reason")
        if not isinstance(reason, str):
            return data
        return {**data, "reason_code": _infer_rejection_reason_code(reason)}

    @model_validator(mode="after")
    def _requires_rejected_target(self) -> "RejectedItem":
        if self.product_id is None and self.listing_id is None:
            raise ValueError("rejected items require a product_id or listing_id.")
        return self


class RecommendationBundle(VersionedSchema):
    bundle_id: CandidateId = Field(default_factory=new_id)
    # Internal provenance is persisted with the versioned bundle, never used as shopper copy.
    result_author: str | None = None
    handoff_chain: tuple[str, ...] = Field(default_factory=tuple)
    verification_action: str | None = None
    verification_changes: tuple[str, ...] = Field(default_factory=tuple)
    final_product_id: ProductId | None = Field(default=None, description="Optional preferred winner among primary_product_ids. Null is valid, and other useful primaries remain selected in their authored order.")
    final_listing_id: ListingId | None = None
    no_strong_buy: bool = False
    no_strong_buy_reason: str | None = Field(
        default=None, min_length=1, max_length=1500
    )
    final_rationale: str | None = Field(default=None, min_length=1, max_length=1500)
    primary_product_ids: tuple[ProductId, ...] | None = Field(default=None, max_length=3, description="The selected strong suitable options in authored order. Choose the useful set before an optional preferred winner.")
    runner_up_product_ids: tuple[ProductId, ...] = Field(default_factory=tuple, description="Worthwhile secondary alternatives considered after strong primaries, up to two. Do not demote equally strong primaries to fill this group.")
    mode_results: tuple[RecommendationModeResult, ...] = Field(default_factory=tuple)
    comparison_matrix: ComparisonMatrix = Field(default_factory=ComparisonMatrix)
    rejected_items: tuple[RejectedItem, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    evidence_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _requires_best_pick_or_no_strong_buy(self) -> "RecommendationBundle":
        if self.primary_product_ids is not None:
            primary = self.primary_product_ids
            runners = self.runner_up_product_ids
            if len(primary) > 3 or len(runners) > 2:
                raise ValueError("recommendations allow at most three primary choices and two runners-up.")
            if len(set(primary)) != len(primary) or len(set(runners)) != len(runners):
                raise ValueError("recommendation choice IDs must be unique.")
            if set(primary).intersection(runners):
                raise ValueError("primary choices and runners-up must be disjoint.")
            if self.no_strong_buy:
                if primary or runners:
                    raise ValueError("no_strong_buy bundles cannot include choice groups.")
            elif not primary:
                raise ValueError("recommendations require at least one primary choice.")
            if self.final_product_id is not None and self.final_product_id not in primary:
                raise ValueError("the final pick must belong to the primary choices.")
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
        if not (has_best_pick or self.primary_product_ids or self.mode_results or self.runner_up_product_ids):
            raise ValueError(
                "recommendation bundles require an option or no_strong_buy=true."
            )
        if self.no_strong_buy_reason is not None:
            raise ValueError(
                "no_strong_buy_reason is only valid when no_strong_buy is true."
            )
        return self


def _infer_rejection_reason_code(reason: str) -> RejectionReason:
    normalized = reason.casefold()
    if any(
        marker in normalized
        for marker in (
            "suspicious",
            "unsafe",
            "seller",
            "listing trust",
            "risky listing",
            "marketplace",
        )
    ):
        return RejectionReason.SUSPICIOUS_LISTING
    if any(marker in normalized for marker in ("budget", "price", "overpay")):
        return RejectionReason.OVERPAYING
    if any(
        marker in normalized
        for marker in ("missing", "lacks", "without", "required", "critical")
    ):
        return RejectionReason.MISSING_CRITICAL_FEATURE
    if any(
        marker in normalized
        for marker in (
            "weak evidence",
            "sparse evidence",
            "sparse product evidence",
            "not enough evidence",
            "source evidence",
        )
    ):
        return RejectionReason.WEAK_EVIDENCE
    return RejectionReason.POOR_FIT
