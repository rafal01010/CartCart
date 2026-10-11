from app.schemas.analysis import ListingTrustAssessment, RecommendationBundle


def integrate_trust_analysis_into_recommendation(
    recommendation: RecommendationBundle,
    trust_assessments: tuple[ListingTrustAssessment, ...],
) -> RecommendationBundle:
    """Preserve the owning model's advice after advisory trust analysis."""
    return recommendation
