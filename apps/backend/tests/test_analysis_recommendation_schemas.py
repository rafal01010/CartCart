from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import (
    CategoryAnalysis,
    ComparisonCriterion,
    ComparisonMatrix,
    ComparisonRow,
    Confidence,
    ConfidenceLevel,
    DeduplicationDecision,
    DeduplicationOutcome,
    ListingTrustAssessment,
    ListingTrustLevel,
    RecommendationBundle,
    RecommendationMode,
    RecommendationModeResult,
    RejectedItem,
    RejectionReason,
    RejectionSeverity,
    new_id,
)


def make_confidence(score: float = 0.8) -> Confidence:
    return Confidence(
        score=score,
        level=ConfidenceLevel.HIGH if score >= 0.75 else ConfidenceLevel.MEDIUM,
        rationale="Fixture confidence.",
    )


def make_comparison_matrix(product_id=None, evidence_id=None) -> ComparisonMatrix:
    product_id = product_id or new_id()
    evidence_id = evidence_id or new_id()
    return ComparisonMatrix(
        criteria=(
            ComparisonCriterion(name="fit", weight=0.5),
            ComparisonCriterion(name="value", weight=0.5),
        ),
        rows=(
            ComparisonRow(
                product_id=product_id,
                scores={"fit": 0.9, "value": 0.72},
                evidence_ids=(evidence_id,),
                summary="Strong fit and fair value.",
            ),
        ),
    )


def test_recommendation_bundle_accepts_one_final_best_pick() -> None:
    product_id = new_id()
    listing_id = new_id()
    evidence_id = new_id()
    bundle = RecommendationBundle(
        final_product_id=product_id,
        final_listing_id=listing_id,
        final_rationale="Best balance of fit, price, source quality, and seller trust.",
        runner_up_product_ids=(new_id(),),
        mode_results=(
            RecommendationModeResult(
                mode=RecommendationMode.BEST_OVERALL,
                product_id=product_id,
                listing_id=listing_id,
                title="Best overall",
                rationale="It best matches the stated priorities.",
                confidence=make_confidence(),
                evidence_ids=(evidence_id,),
                source_ids=(new_id(),),
            ),
        ),
        comparison_matrix=make_comparison_matrix(product_id, evidence_id),
        rejected_items=(
            RejectedItem(
                product_id=new_id(),
                reason_code=RejectionReason.SUSPICIOUS_LISTING,
                reason="Suspicious marketplace listing with weak seller signals.",
                severity=RejectionSeverity.BLOCKING,
                evidence_ids=(evidence_id,),
                source_ids=(new_id(),),
            ),
        ),
        evidence_ids=(evidence_id,),
        source_ids=(new_id(),),
    )

    assert bundle.final_product_id == product_id
    assert bundle.no_strong_buy is False
    assert bundle.mode_results[0].evidence_ids == (evidence_id,)
    assert bundle.comparison_matrix.rows[0].evidence_ids == (evidence_id,)
    assert bundle.rejected_items[0].severity == RejectionSeverity.BLOCKING


def test_recommendation_bundle_accepts_explicit_no_strong_buy() -> None:
    evidence_id = new_id()
    bundle = RecommendationBundle(
        no_strong_buy=True,
        no_strong_buy_reason="All available listings have weak evidence or trust issues.",
        comparison_matrix=make_comparison_matrix(evidence_id=evidence_id),
        warnings=("No candidate clears the evidence and seller-trust bar.",),
        evidence_ids=(evidence_id,),
    )

    assert bundle.no_strong_buy is True
    assert bundle.final_product_id is None
    assert bundle.no_strong_buy_reason is not None


def test_recommendation_bundle_rejects_missing_or_conflicting_final_outcomes() -> None:
    product_id = new_id()
    listing_id = new_id()

    with pytest.raises(ValidationError):
        RecommendationBundle(comparison_matrix=make_comparison_matrix())

    with pytest.raises(ValidationError):
        RecommendationBundle(
            final_product_id=product_id,
            no_strong_buy=True,
            no_strong_buy_reason="Cannot also have a best pick.",
            comparison_matrix=make_comparison_matrix(product_id),
        )

    with pytest.raises(ValidationError):
        RecommendationBundle(
            no_strong_buy=True,
            final_listing_id=listing_id,
            no_strong_buy_reason="No strong buy cannot include final listing.",
            comparison_matrix=make_comparison_matrix(product_id),
        )

    with pytest.raises(ValidationError):
        RecommendationBundle(
            no_strong_buy=True,
            comparison_matrix=make_comparison_matrix(product_id),
        )

    with pytest.raises(ValidationError):
        RecommendationBundle(
            final_product_id=product_id,
            no_strong_buy_reason="Only valid for no-strong-buy.",
            comparison_matrix=make_comparison_matrix(product_id),
        )


def test_deduplication_decision_requires_canonical_product_for_duplicates() -> None:
    first = new_id()
    second = new_id()
    decision = DeduplicationDecision(
        candidate_ids=(first, second),
        outcome=DeduplicationOutcome.DUPLICATE,
        canonical_product_id=new_id(),
        confidence=make_confidence(),
        rationale="The model number, brand, and specs match.",
        source_ids=(new_id(),),
    )

    assert decision.outcome == DeduplicationOutcome.DUPLICATE

    with pytest.raises(ValidationError):
        DeduplicationDecision(
            candidate_ids=(first, second),
            outcome=DeduplicationOutcome.DUPLICATE,
            confidence=make_confidence(),
            rationale="Duplicate without canonical product.",
        )


def test_listing_trust_and_category_analysis_preserve_separate_dimensions() -> None:
    product_id = new_id()
    listing_id = new_id()
    trust_evidence_id = new_id()
    product_evidence_id = new_id()
    trust = ListingTrustAssessment(
        listing_id=listing_id,
        level=ListingTrustLevel.SUSPICIOUS,
        confidence=make_confidence(0.68),
        summary="Seller identity and fulfillment details are unclear.",
        red_flags=("Unusually low price.",),
        evidence_ids=(trust_evidence_id,),
        source_ids=(new_id(),),
        assessed_at="2026-05-30T00:00:00Z",
    )
    analysis = CategoryAnalysis(
        product_id=product_id,
        listing_ids=(listing_id,),
        category="laptop",
        fit_summary="The product is a good fit, but this listing is risky.",
        strengths=("Portable form factor.",),
        warnings=("Do not treat the suspicious listing as a safe buy.",),
        confidence=make_confidence(),
        evidence_ids=(product_evidence_id,),
        source_ids=(new_id(),),
    )

    assert trust.level == ListingTrustLevel.SUSPICIOUS
    assert trust.evidence_ids == (trust_evidence_id,)
    assert analysis.product_id == product_id
    assert analysis.evidence_ids == (product_evidence_id,)
    assert analysis.listing_ids == (listing_id,)
    assert trust.assessed_at == datetime(2026, 5, 30, 0, 0, tzinfo=UTC)


def test_comparison_matrix_rejects_scores_for_undeclared_criteria() -> None:
    with pytest.raises(ValidationError):
        ComparisonMatrix(
            criteria=(ComparisonCriterion(name="fit"),),
            rows=(ComparisonRow(product_id=new_id(), scores={"price": 0.8}),),
        )


def test_rejected_item_requires_product_or_listing_target() -> None:
    with pytest.raises(ValidationError):
        RejectedItem(
            reason_code=RejectionReason.POOR_FIT,
            reason="A rejected item must identify what was rejected.",
            severity=RejectionSeverity.MEDIUM,
            evidence_ids=(new_id(),),
        )


def test_rejected_item_infers_legacy_reason_code() -> None:
    item = RejectedItem(
        product_id=new_id(),
        reason="Sparse product evidence is not enough for a confident recommendation.",
        severity=RejectionSeverity.MEDIUM,
        evidence_ids=(new_id(),),
    )

    assert item.reason_code == RejectionReason.WEAK_EVIDENCE


def test_source_backed_recommendation_claims_require_evidence_ids() -> None:
    product_id = new_id()

    with pytest.raises(ValidationError):
        RecommendationModeResult(
            mode=RecommendationMode.BEST_OVERALL,
            product_id=product_id,
            title="Best overall",
            rationale="A recommendation claim without evidence IDs.",
            confidence=make_confidence(),
        )

    with pytest.raises(ValidationError):
        RecommendationBundle(
            final_product_id=product_id,
            final_rationale="A final recommendation without evidence IDs.",
            comparison_matrix=make_comparison_matrix(product_id),
        )
