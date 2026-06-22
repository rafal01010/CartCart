from app.schemas.analysis import (
    ComparisonCriterion,
    ComparisonMatrix,
    ComparisonRow,
    ListingTrustAssessment,
    ListingTrustLevel,
    RecommendationBundle,
    RecommendationMode,
    RecommendationModeResult,
    RejectedItem,
    RejectionReason,
    RejectionSeverity,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import ListingId, ProductId, SourceId, new_id
from app.services.recommendation_trust import (
    integrate_trust_analysis_into_recommendation,
)


def make_confidence(score: float = 0.82) -> Confidence:
    return Confidence(
        score=score,
        level=ConfidenceLevel.HIGH if score >= 0.75 else ConfidenceLevel.MEDIUM,
        rationale="Fixture confidence.",
    )


def make_recommendation(
    *,
    product_id: ProductId,
    final_listing_id: ListingId,
    evidence_id: SourceId,
    extra_listing_id: ListingId | None = None,
) -> RecommendationBundle:
    rows = [
        ComparisonRow(
            product_id=product_id,
            listing_id=final_listing_id,
            scores={"fit": 0.9, "seller_trust": 0.88},
            evidence_ids=(evidence_id,),
            summary="The product is a strong fit from the selected listing.",
        )
    ]
    if extra_listing_id is not None:
        rows.append(
            ComparisonRow(
                product_id=product_id,
                listing_id=extra_listing_id,
                scores={"fit": 0.9, "seller_trust": 0.1},
                evidence_ids=(evidence_id,),
                summary="Same product, worse listing safety.",
            )
        )

    matrix = ComparisonMatrix(
        criteria=(
            ComparisonCriterion(name="fit", weight=0.6),
            ComparisonCriterion(name="seller_trust", weight=0.4),
        ),
        rows=tuple(rows),
    )
    return RecommendationBundle(
        final_product_id=product_id,
        final_listing_id=final_listing_id,
        final_rationale="The product is a strong fit from the safe listing.",
        mode_results=(
            RecommendationModeResult(
                mode=RecommendationMode.BEST_OVERALL,
                product_id=product_id,
                listing_id=final_listing_id,
                title="Best overall",
                rationale="Strong fit and acceptable listing safety.",
                confidence=make_confidence(),
                evidence_ids=(evidence_id,),
                source_ids=(new_id(),),
            ),
        ),
        comparison_matrix=matrix,
        evidence_ids=(evidence_id,),
        source_ids=(new_id(),),
    )


def make_trust(
    listing_id: ListingId,
    level: ListingTrustLevel,
    summary: str,
) -> ListingTrustAssessment:
    return ListingTrustAssessment(
        listing_id=listing_id,
        level=level,
        confidence=make_confidence(0.68),
        summary=summary,
        red_flags=("Seller/listing details are risky.",),
        evidence_ids=(new_id(),),
        source_ids=(new_id(),),
    )


def test_suspicious_duplicate_listing_is_rejected_without_rejecting_product() -> None:
    product_id = new_id()
    safe_listing_id = new_id()
    suspicious_listing_id = new_id()
    recommendation = make_recommendation(
        product_id=product_id,
        final_listing_id=safe_listing_id,
        extra_listing_id=suspicious_listing_id,
        evidence_id=new_id(),
    )

    updated = integrate_trust_analysis_into_recommendation(
        recommendation,
        (
            make_trust(
                suspicious_listing_id,
                ListingTrustLevel.SUSPICIOUS,
                "Same product appears through a suspicious marketplace seller.",
            ),
        ),
    )

    assert updated.final_product_id == product_id
    assert updated.final_listing_id == safe_listing_id
    assert updated.no_strong_buy is False
    assert any(
        item.listing_id == suspicious_listing_id
        and item.product_id is None
        and item.reason_code == RejectionReason.SUSPICIOUS_LISTING
        and item.severity == RejectionSeverity.BLOCKING
        for item in updated.rejected_items
    )
    assert any(
        "product may still be worth considering" in item.reason
        for item in updated.rejected_items
    )
    assert any(
        "Blocked a suspicious listing" in warning for warning in updated.warnings
    )


def test_suspicious_final_listing_becomes_no_strong_buy() -> None:
    product_id = new_id()
    listing_id = new_id()
    recommendation = make_recommendation(
        product_id=product_id,
        final_listing_id=listing_id,
        evidence_id=new_id(),
    )

    updated = integrate_trust_analysis_into_recommendation(
        recommendation,
        (
            make_trust(
                listing_id,
                ListingTrustLevel.SUSPICIOUS,
                "The selected listing has a too-good-to-be-true price.",
            ),
        ),
    )

    assert updated.no_strong_buy is True
    assert updated.final_product_id is None
    assert updated.final_listing_id is None
    assert updated.no_strong_buy_reason is not None
    assert "no candidate is a strong buy" in updated.no_strong_buy_reason.casefold()
    assert "selected listing" in updated.no_strong_buy_reason
    assert "Next" in updated.no_strong_buy_reason
    assert updated.rejected_items[0].listing_id == listing_id
    assert updated.rejected_items[0].severity == RejectionSeverity.BLOCKING


def test_weak_listing_is_penalized_as_listing_risk() -> None:
    product_id = new_id()
    safe_listing_id = new_id()
    weak_listing_id = new_id()
    recommendation = make_recommendation(
        product_id=product_id,
        final_listing_id=safe_listing_id,
        extra_listing_id=weak_listing_id,
        evidence_id=new_id(),
    )

    updated = integrate_trust_analysis_into_recommendation(
        recommendation,
        (
            make_trust(
                weak_listing_id,
                ListingTrustLevel.WEAK,
                "Seller identity and return terms are unclear.",
            ),
        ),
    )

    assert updated.no_strong_buy is False
    weak_rejection = next(
        item for item in updated.rejected_items if item.listing_id == weak_listing_id
    )
    assert weak_rejection.severity == RejectionSeverity.HIGH
    assert weak_rejection.reason_code == RejectionReason.SUSPICIOUS_LISTING
    assert "seller/listing checks are weak" in weak_rejection.reason
    assert any(
        "Treat the product and this seller separately" in warning
        for warning in updated.warnings
    )


def test_weak_final_listing_is_not_presented_as_safe_best_buy() -> None:
    product_id = new_id()
    listing_id = new_id()
    recommendation = make_recommendation(
        product_id=product_id,
        final_listing_id=listing_id,
        evidence_id=new_id(),
    )

    updated = integrate_trust_analysis_into_recommendation(
        recommendation,
        (
            make_trust(
                listing_id,
                ListingTrustLevel.WEAK,
                "Return terms and seller identity are too unclear.",
            ),
        ),
    )

    assert updated.no_strong_buy is True
    assert updated.final_product_id is None
    assert updated.final_listing_id is None
    assert updated.rejected_items[0].severity == RejectionSeverity.HIGH


def test_existing_listing_rejection_is_not_duplicated() -> None:
    product_id = new_id()
    safe_listing_id = new_id()
    suspicious_listing_id = new_id()
    evidence_id = new_id()
    recommendation = make_recommendation(
        product_id=product_id,
        final_listing_id=safe_listing_id,
        extra_listing_id=suspicious_listing_id,
        evidence_id=evidence_id,
    ).model_copy(
        update={
            "rejected_items": (
                RejectedItem(
                    product_id=product_id,
                    listing_id=suspicious_listing_id,
                    reason_code=RejectionReason.SUSPICIOUS_LISTING,
                    reason="Already rejected as a risky listing.",
                    severity=RejectionSeverity.BLOCKING,
                    evidence_ids=(evidence_id,),
                ),
            )
        }
    )

    updated = integrate_trust_analysis_into_recommendation(
        recommendation,
        (
            make_trust(
                suspicious_listing_id,
                ListingTrustLevel.SUSPICIOUS,
                "Same product appears through a suspicious marketplace seller.",
            ),
        ),
    )

    assert (
        sum(item.listing_id == suspicious_listing_id for item in updated.rejected_items)
        == 1
    )
