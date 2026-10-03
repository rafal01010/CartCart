from types import SimpleNamespace
from typing import cast

from app.db.repositories.results import SavedResultBundle
from app.schemas.analysis import RecommendationMode
from app.schemas.ids import new_id
from app.schemas.intake import BudgetConstraint, ShoppingBrief
from app.schemas.runs import ArtifactDisposition, RecomputeStage, RefinementRequest
from app.services.refinement_planning import build_recompute_plan


def _plan(*, evidence: bool = True, **changes: object):
    session_id, old_run_id, new_run_id = new_id(), new_id(), new_id()
    prior_version_id = new_id()
    prior_result = cast(
        SavedResultBundle,
        SimpleNamespace(
            result_version=SimpleNamespace(
                run_id=old_run_id, result_version_id=prior_version_id
            )
        ),
    )
    request = RefinementRequest(
        session_id=session_id,
        instruction="Change this decision.",
        **changes,
    )
    plan = build_recompute_plan(
        session_id=session_id,
        run_id=new_run_id,
        refinement=request,
        prior_result=prior_result,
        base_brief=ShoppingBrief(
            original_query="Find headphones",
            category="headphones",
            category_source="user_provided",
        ),
        has_candidate_evidence=evidence,
    )
    assert plan.prior_run_id == old_run_id
    assert plan.prior_result_version_id == prior_version_id
    return plan


def _dispositions(plan) -> dict[str, ArtifactDisposition]:
    return {
        decision.artifact.value: decision.disposition for decision in plan.artifacts
    }


def test_budget_and_mode_reuse_valid_candidate_evidence() -> None:
    budget = _plan(
        budget=BudgetConstraint.model_validate(
            {"amount": {"amount": "150", "currency": "USD"}, "mode": "hard_cap"}
        )
    )
    assert budget.stages == (RecomputeStage.ANALYSIS, RecomputeStage.RESULT_MODE)
    assert _dispositions(budget)["source_evidence"] == ArtifactDisposition.REUSED
    assert _dispositions(budget)["candidate_products"] == ArtifactDisposition.REUSED
    assert _dispositions(budget)["comparison"] == ArtifactDisposition.INVALIDATED
    assert budget.target_brief.budget is not None
    assert budget.base_brief.budget is None

    mode = _plan(result_mode=RecommendationMode.BEST_VALUE)
    assert mode.stages == (RecomputeStage.RESULT_MODE,)
    assert _dispositions(mode)["comparison"] == ArtifactDisposition.REUSED
    assert _dispositions(mode)["recommendation"] == ArtifactDisposition.INVALIDATED


def test_category_and_region_invalidate_affected_research() -> None:
    category = _plan(category="office chairs")
    assert category.stages == (
        RecomputeStage.SEARCH,
        RecomputeStage.EXTRACTION,
        RecomputeStage.ANALYSIS,
        RecomputeStage.RESULT_MODE,
    )
    assert category.target_brief.category == "office chairs"
    assert _dispositions(category)["source_evidence"] == ArtifactDisposition.INVALIDATED

    region = _plan(
        region={
            "region": {"country_code": "CA", "currency": "CAD"},
            "source": "user_provided",
        }
    )
    assert RecomputeStage.SEARCH in region.stages
    assert _dispositions(region)["product_listings"] == ArtifactDisposition.INVALIDATED
    assert "region" in region.artifacts[1].reason.lower()


def test_missing_evidence_or_unstructured_change_fails_closed() -> None:
    budget = _plan(
        evidence=False,
        budget={"amount": {"amount": "150", "currency": "USD"}, "mode": "hard_cap"},
    )
    assert RecomputeStage.SEARCH in budget.stages
    assert (
        _dispositions(budget)["candidate_products"] == ArtifactDisposition.INVALIDATED
    )

    ambiguous = _plan()
    assert ambiguous.stages[0] == RecomputeStage.RE_INTAKE
    assert _dispositions(ambiguous)["shopping_brief"] == ArtifactDisposition.INVALIDATED
