import json

import pytest

from app.agents.contracts import ComparisonDecisionAgentInput
from app.agents.live_comparison_decision import (
    LiveComparisonDecisionAgent,
    MockComparisonDecisionModelRunner,
    _model_input,
)
from app.core.settings import Settings
from app.schemas.analysis import RecommendationBundle
from app.schemas.ids import new_id
from app.schemas.intake import BudgetConstraint, BudgetMode, ShoppingBrief
from app.schemas.money import Money
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile


def comparison_input() -> ComparisonDecisionAgentInput:
    product = CanonicalProduct(name="Compact kettle")
    listing = ProductListing(
        product_id=product.product_id,
        title="Compact kettle",
        source_ids=(new_id(),),
        url="https://shop.example/kettle",
        seller=SellerProfile(seller_name="Example store"),
        price=Money(amount="105", currency="USD"),
    )
    return ComparisonDecisionAgentInput(
        run_id=new_id(),
        brief=ShoppingBrief(
            original_query="A compact kettle under 100 dollars",
            budget=BudgetConstraint(
                amount=Money(amount="100", currency="USD"), mode=BudgetMode.HARD_CAP
            ),
        ),
        products=(product,),
        listings=(listing,),
    )


@pytest.mark.asyncio
async def test_comparison_preserves_uncited_over_budget_model_selection_without_modes() -> (
    None
):
    request = comparison_input()
    advice = RecommendationBundle(
        primary_product_ids=(request.products[0].product_id,),
        final_product_id=request.products[0].product_id,
        final_listing_id=request.listings[0].listing_id,
        final_rationale="This compact option costs five dollars more than your budget.",
    )
    agent = LiveComparisonDecisionAgent(
        settings=Settings(_env_file=None, environment="test"),
        model_runner=MockComparisonDecisionModelRunner(output=advice),
    )
    result = await agent.run(request)
    assert result == advice
    assert result.mode_results == ()
    assert result.evidence_ids == ()


def test_comparison_input_exposes_budget_difference_and_unknowns_as_advice() -> None:
    request = comparison_input()
    payload = json.loads(_model_input(request))
    assert payload["ranked_candidates"][0]["over_budget_amount"] == "5"
    assert payload["ranked_candidates"][0]["known_price"]["currency"] == "USD"
    assert payload["brief"]["budget"]["mode"] == "hard_cap"
    assert payload["advisory_score_references"] == {
        "fit": 0.25,
        "evidence": 0.2,
        "overall": 0.35,
        "trust": 0.2,
    }
    unknown = request.model_copy(
        update={"listings": (request.listings[0].model_copy(update={"price": None}),)}
    )
    candidate = json.loads(_model_input(unknown))["ranked_candidates"][0]
    assert candidate["known_price"] is None
    assert candidate["over_budget_amount"] is None


@pytest.mark.asyncio
async def test_comparison_failure_is_retryable_instead_of_a_buying_judgment() -> None:
    agent = LiveComparisonDecisionAgent(
        settings=Settings(_env_file=None, environment="test"),
        model_runner=MockComparisonDecisionModelRunner(
            error=RuntimeError("unavailable")
        ),
    )
    with pytest.raises(RuntimeError, match="gathered information is saved"):
        await agent.run(comparison_input())
