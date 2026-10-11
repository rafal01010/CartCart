from app.agents.recommendation_offers import recommendation_listing_surfaces
from app.agents.live_verifier_critic import verify_recommendation_guardrails
from app.schemas.intake import BudgetMode
from test_live_verifier_critic_agent import _verification_input


def test_known_over_budget_offer_is_context_for_the_model() -> None:
    request = _verification_input(
        budget_mode=BudgetMode.HARD_CAP, budget_amount="100", listing_price="249.99"
    )
    surfaces = recommendation_listing_surfaces(request.recommendation_bundle)
    assert surfaces == (("final pick", request.recommendation_bundle.final_listing_id),)
    report = verify_recommendation_guardrails(request)
    assert report.approved is True
    assert (
        report.recommendation_bundle.final_listing_id == request.listings[0].listing_id
    )
