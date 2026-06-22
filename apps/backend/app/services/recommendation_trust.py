from app.schemas.analysis import (
    ListingTrustAssessment,
    ListingTrustLevel,
    RecommendationBundle,
    RejectedItem,
    RejectionReason,
    RejectionSeverity,
)
from app.schemas.ids import ListingId


_BLOCKING_LEVELS = {ListingTrustLevel.SUSPICIOUS, ListingTrustLevel.WEAK}
_REJECTED_LEVELS = {ListingTrustLevel.SUSPICIOUS, ListingTrustLevel.WEAK}
_WARNING_LEVELS = {
    ListingTrustLevel.SUSPICIOUS,
    ListingTrustLevel.WEAK,
    ListingTrustLevel.MIXED,
}


def integrate_trust_analysis_into_recommendation(
    recommendation: RecommendationBundle,
    trust_assessments: tuple[ListingTrustAssessment, ...],
) -> RecommendationBundle:
    """Surface listing trust without collapsing it into product fit."""

    if not trust_assessments:
        return recommendation

    rejected_items = list(recommendation.rejected_items)
    rejected_listing_ids = {
        item.listing_id for item in rejected_items if item.listing_id is not None
    }
    warnings = list(recommendation.warnings)

    for assessment in trust_assessments:
        if assessment.level in _WARNING_LEVELS:
            warnings.append(_warning_for_assessment(assessment))
        if assessment.level not in _REJECTED_LEVELS:
            continue
        if assessment.listing_id in rejected_listing_ids:
            continue
        rejected_items.append(_rejection_for_assessment(assessment))
        rejected_listing_ids.add(assessment.listing_id)

    final_assessment = _final_listing_assessment(
        recommendation.final_listing_id,
        trust_assessments,
    )
    update: dict[str, object] = {
        "warnings": _unique_text(warnings),
        "rejected_items": tuple(rejected_items),
    }
    if final_assessment is not None and final_assessment.level in _BLOCKING_LEVELS:
        update.update(
            {
                "final_product_id": None,
                "final_listing_id": None,
                "no_strong_buy": True,
                "no_strong_buy_reason": _no_strong_buy_reason(final_assessment),
                "final_rationale": None,
            }
        )

    return _validated_copy(recommendation, update)


def _final_listing_assessment(
    final_listing_id: ListingId | None,
    assessments: tuple[ListingTrustAssessment, ...],
) -> ListingTrustAssessment | None:
    if final_listing_id is None:
        return None
    for assessment in assessments:
        if assessment.listing_id == final_listing_id:
            return assessment
    return None


def _warning_for_assessment(assessment: ListingTrustAssessment) -> str:
    if assessment.level == ListingTrustLevel.SUSPICIOUS:
        return (
            "Blocked a suspicious listing: "
            f"{assessment.summary} The product may still be worth considering "
            "from a safer seller."
        )
    if assessment.level == ListingTrustLevel.WEAK:
        return (
            "Seller/listing checks are weak for one listing: "
            f"{assessment.summary} Treat the product and this seller separately."
        )
    return f"Seller/listing checks are mixed for one listing: {assessment.summary}"


def _rejection_for_assessment(assessment: ListingTrustAssessment) -> RejectedItem:
    if assessment.level == ListingTrustLevel.SUSPICIOUS:
        reason = (
            "Blocked this listing because seller/listing checks found: "
            f"{assessment.summary} The product may still be worth considering "
            "from a safer seller."
        )
        severity = RejectionSeverity.BLOCKING
    else:
        reason = (
            "Penalized this listing because seller/listing checks are weak: "
            f"{assessment.summary} The product may still be worth considering "
            "from a clearer seller."
        )
        severity = RejectionSeverity.HIGH

    return RejectedItem(
        listing_id=assessment.listing_id,
        reason_code=RejectionReason.SUSPICIOUS_LISTING,
        reason=reason,
        severity=severity,
        evidence_ids=assessment.evidence_ids,
        source_ids=assessment.source_ids,
    )


def _no_strong_buy_reason(assessment: ListingTrustAssessment) -> str:
    return (
        "No candidate is a strong buy from the selected listing because "
        f"seller/listing checks found: {assessment.summary} Next, look for the "
        "same product from a safer seller or use a runner-up with clearer trust "
        "signals."
    )


def _unique_text(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def _validated_copy(
    recommendation: RecommendationBundle,
    update: dict[str, object],
) -> RecommendationBundle:
    data = recommendation.model_dump(mode="python")
    data.update(update)
    return RecommendationBundle.model_validate(data)
