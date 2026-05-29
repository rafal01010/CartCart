from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas import (
    BudgetConstraint,
    BudgetMode,
    CreateSessionRequest,
    FieldSource,
    Money,
    PreferenceConstraint,
    PreferenceMode,
    Region,
    RegionPreference,
    ShoppingBrief,
    ShoppingSession,
)


def test_budget_constraint_distinguishes_hard_cap_from_soft_preference() -> None:
    hard_budget = BudgetConstraint(
        amount=Money(amount="500.00", currency="USD"),
        mode=BudgetMode.HARD_CAP,
    )
    soft_budget = BudgetConstraint(
        amount=Money(amount="650.00", currency="USD"),
        mode=BudgetMode.PREFERRED,
    )

    assert hard_budget.is_hard_cap is True
    assert soft_budget.is_hard_cap is False


@pytest.mark.parametrize("mode", ["strict", "soft", ""])
def test_budget_constraint_rejects_unknown_budget_modes(mode: str) -> None:
    with pytest.raises(ValidationError):
        BudgetConstraint(amount={"amount": "500.00", "currency": "USD"}, mode=mode)


def test_create_session_request_allows_missing_region() -> None:
    request = CreateSessionRequest(
        query="quiet mechanical keyboard under 100 dollars",
        budget={
            "amount": {"amount": "100.00", "currency": "USD"},
            "mode": "preferred",
        },
    )

    assert request.region is None
    assert request.budget is not None
    assert request.budget.mode == BudgetMode.PREFERRED


def test_create_session_request_rejects_blank_query() -> None:
    with pytest.raises(ValidationError):
        CreateSessionRequest(query="")


def test_shopping_brief_preserves_inferred_defaulted_and_user_provided_fields() -> None:
    brief = ShoppingBrief(
        original_query="Need a laptop for travel",
        category="laptop",
        category_source=FieldSource.INFERRED,
        region=RegionPreference(
            region=Region(country_code="US", currency="USD"),
            source=FieldSource.DEFAULTED,
        ),
        budget=BudgetConstraint(
            amount=Money(amount="1200.00", currency="USD"),
            mode=BudgetMode.HARD_CAP,
            source=FieldSource.USER_PROVIDED,
        ),
        constraints=(
            PreferenceConstraint(
                text="Must fit in an airplane tray table.",
                mode=PreferenceMode.HARD,
                source=FieldSource.USER_PROVIDED,
            ),
        ),
        preferences=(
            PreferenceConstraint(
                text="Prefer quiet fans.",
                mode=PreferenceMode.SOFT,
                source=FieldSource.INFERRED,
            ),
        ),
    )

    assert brief.category_source == FieldSource.INFERRED
    assert brief.region is not None
    assert brief.region.source == FieldSource.DEFAULTED
    assert brief.budget is not None
    assert brief.budget.source == FieldSource.USER_PROVIDED
    assert brief.constraints[0].is_hard is True
    assert brief.preferences[0].source == FieldSource.INFERRED


def test_shopping_brief_rejects_category_without_source() -> None:
    with pytest.raises(ValidationError):
        ShoppingBrief(original_query="Need headphones", category="headphones")


def test_shopping_brief_rejects_category_source_without_category() -> None:
    with pytest.raises(ValidationError):
        ShoppingBrief(
            original_query="Need headphones",
            category_source=FieldSource.INFERRED,
        )


def test_preference_constraint_rejects_blank_text() -> None:
    with pytest.raises(ValidationError):
        PreferenceConstraint(text="", mode=PreferenceMode.SOFT)


def test_shopping_session_accepts_request_brief_and_timestamps() -> None:
    request = CreateSessionRequest(query="Need a monitor")
    brief = ShoppingBrief(
        original_query=request.query,
        category="monitor",
        category_source=FieldSource.INFERRED,
    )
    session = ShoppingSession(
        original_input=request,
        current_brief=brief,
        created_at="2026-05-29T00:00:00Z",
        updated_at="2026-05-29T00:05:00Z",
    )

    assert isinstance(session.session_id, UUID)
    assert session.original_input.query == "Need a monitor"
    assert session.current_brief.category == "monitor"
    assert session.created_at == datetime(2026, 5, 29, 0, 0, tzinfo=UTC)


def test_shopping_session_rejects_updated_at_before_created_at() -> None:
    request = CreateSessionRequest(query="Need a monitor")
    brief = ShoppingBrief(original_query=request.query)

    with pytest.raises(ValidationError):
        ShoppingSession(
            original_input=request,
            current_brief=brief,
            created_at="2026-05-29T00:05:00Z",
            updated_at="2026-05-29T00:00:00Z",
        )
