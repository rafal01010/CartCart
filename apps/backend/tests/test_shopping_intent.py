import pytest

from app.schemas.intake import BudgetConstraint, BudgetMode, ShoppingBrief
from app.schemas.money import Money
from app.services.shopping_intent import (
    brief_has_unconstrained_budget,
    search_intent_text,
)


@pytest.mark.parametrize(
    "query",
    (
        "I need a phone, budget is not a problem",
        "Money is no object. Find a laptop.",
        "Budget isn't an issue for this desk",
        "I have an unlimited budget for a TV",
        "There is no budget limit for these headphones",
    ),
)
def test_explicit_unlimited_budget_is_distinct_from_missing_budget(query: str) -> None:
    assert brief_has_unconstrained_budget(ShoppingBrief(original_query=query))
    assert "budget" not in search_intent_text(query).casefold()


@pytest.mark.parametrize(
    "query",
    (
        "I need a phone",
        "I need a budget phone",
        "I have no budget",
        "Find a cheap laptop",
        "Keep the budget under $500",
    ),
)
def test_missing_or_constrained_budget_does_not_become_unlimited(query: str) -> None:
    assert not brief_has_unconstrained_budget(ShoppingBrief(original_query=query))


def test_explicit_budget_control_wins_over_original_unlimited_wording() -> None:
    brief = ShoppingBrief(
        original_query="I need a phone, budget is not a problem",
        budget=BudgetConstraint(
            amount=Money(amount="500", currency="USD"), mode=BudgetMode.HARD_CAP
        ),
    )
    assert not brief_has_unconstrained_budget(brief)
