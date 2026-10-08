import pytest

from app.agents.context_management import CONTEXT_RESEARCH_LIMITATION
from app.agents.contracts import VerificationAgentInput
from app.agents.live_verifier_critic import verify_recommendation_guardrails
from app.schemas.analysis import ComparisonMatrix, RecommendationBundle
from app.schemas.ids import new_id
from app.schemas.intake import ShoppingBrief


def limited_input(reason: str) -> VerificationAgentInput:
    return VerificationAgentInput(
        run_id=new_id(),
        brief=ShoppingBrief(original_query="Help me choose a lamp."),
        recommendation_bundle=RecommendationBundle(
            no_strong_buy=True,
            no_strong_buy_reason=reason,
            warnings=(reason,),
            comparison_matrix=ComparisonMatrix(),
        ),
    )


def test_process_limitation_keeps_missing_checks_without_claiming_product_facts():
    reason = (
        CONTEXT_RESEARCH_LIMITATION
        + " Research was shortened before enough independent support could be checked. "
        + "Local warranty and seller details still need checking."
    )
    report = verify_recommendation_guardrails(limited_input(reason))
    assert report.approved is True
    assert report.recommendation_bundle.no_strong_buy_reason == reason
    assert report.recommendation_bundle.warnings == (reason,)


@pytest.mark.parametrize(
    "claim",
    [
        "This lamp has a local warranty.",
        "This lamp supports 120Hz.",
        "The seller is genuine.",
        "This lamp costs PHP 2000.",
    ],
)
def test_process_limitation_cannot_authorize_unsupported_claims(claim: str):
    report = verify_recommendation_guardrails(
        limited_input(CONTEXT_RESEARCH_LIMITATION + " " + claim)
    )
    assert report.approved is False
    assert report.blocking_issues == (
        "no-strong-buy reason needs source evidence before it can be shown.",
        "warning 1 needs source evidence before it can be shown.",
    )
