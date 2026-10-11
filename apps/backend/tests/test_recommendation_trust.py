import pytest

from app.schemas.analysis import (
    ListingTrustAssessment,
    ListingTrustLevel,
    RecommendationBundle,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import new_id
from app.services.recommendation_trust import (
    integrate_trust_analysis_into_recommendation,
)


@pytest.mark.parametrize("level", list(ListingTrustLevel))
def test_advisory_trust_preserves_model_selections_and_scoped_warning(
    level: ListingTrustLevel,
) -> None:
    product_id, listing_id = new_id(), new_id()
    advice = RecommendationBundle(
        final_product_id=product_id,
        final_listing_id=listing_id,
        final_rationale="Consider the product from this seller with care.",
        warnings=("This offer has conflicting seller details.",),
    )
    assessment = ListingTrustAssessment(
        listing_id=listing_id,
        level=level,
        confidence=Confidence(
            score=0.5, level=ConfidenceLevel.MEDIUM, rationale="Advisory."
        ),
        summary="Seller context.",
    )
    result = integrate_trust_analysis_into_recommendation(advice, (assessment,))
    assert result == advice
    assert result.final_listing_id == listing_id
    assert result.warnings == ("This offer has conflicting seller details.",)
