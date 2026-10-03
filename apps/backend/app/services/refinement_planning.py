"""Pure, conservative invalidation rules for a saved shopping refinement."""

from app.db.repositories.results import SavedResultBundle
from app.schemas.ids import RunId, SessionId
from app.schemas.intake import FieldSource, ShoppingBrief
from app.schemas.runs import (
    ArtifactDecision,
    ArtifactDisposition,
    RecomputePlan,
    RecomputeStage,
    RefinementArtifact,
    RefinementRequest,
)


_RESEARCH = (
    RefinementArtifact.SEARCH_PLAN,
    RefinementArtifact.SEARCH_RESULTS,
    RefinementArtifact.SOURCE_SNAPSHOTS,
    RefinementArtifact.SOURCE_EVIDENCE,
    RefinementArtifact.CANDIDATE_PRODUCTS,
    RefinementArtifact.PRODUCT_LISTINGS,
    RefinementArtifact.SOURCE_INTELLIGENCE,
    RefinementArtifact.LISTING_TRUST,
)
_ANALYSIS = (
    RefinementArtifact.CATEGORY_ANALYSIS,
    RefinementArtifact.COMPARISON,
)
_DECISION = (
    RefinementArtifact.RECOMMENDATION,
    RefinementArtifact.VERIFICATION,
)


def build_recompute_plan(
    *,
    session_id: SessionId,
    run_id: RunId,
    refinement: RefinementRequest,
    prior_result: SavedResultBundle,
    base_brief: ShoppingBrief,
    has_candidate_evidence: bool,
) -> RecomputePlan:
    target_brief = base_brief.model_copy(
        update={
            "category": refinement.category
            if refinement.category is not None
            else base_brief.category,
            "category_source": (
                FieldSource.USER_PROVIDED
                if refinement.category is not None
                else base_brief.category_source
            ),
            "region": refinement.region or base_brief.region,
            "budget": refinement.budget or base_brief.budget,
            "constraints": (*base_brief.constraints, *refinement.constraints),
            "preferences": (*base_brief.preferences, *refinement.preferences),
        }
    )
    category_changed = (target_brief.category or "").strip().casefold() != (
        base_brief.category or ""
    ).strip().casefold()
    region_changed = (target_brief.region.region if target_brief.region else None) != (
        base_brief.region.region if base_brief.region else None
    )
    budget_changed = (
        (target_brief.budget.amount, target_brief.budget.mode)
        if target_brief.budget
        else None
    ) != (
        (base_brief.budget.amount, base_brief.budget.mode)
        if base_brief.budget
        else None
    )
    preference_changed = bool(refinement.preferences or refinement.constraints)
    currency_changed = (
        budget_changed
        and base_brief.budget is not None
        and target_brief.budget is not None
        and base_brief.budget.amount.currency != target_brief.budget.amount.currency
    )
    structured_change = any(
        (
            category_changed,
            region_changed,
            budget_changed,
            preference_changed,
            refinement.result_mode is not None,
        )
    )

    if not structured_change:
        stages = (
            RecomputeStage.RE_INTAKE,
            RecomputeStage.SEARCH,
            RecomputeStage.EXTRACTION,
            RecomputeStage.ANALYSIS,
            RecomputeStage.RESULT_MODE,
        )
        reason = "The free-text change needs intake before its research scope can be trusted."
    elif (
        category_changed
        or region_changed
        or currency_changed
        or preference_changed
        or (budget_changed and not has_candidate_evidence)
    ):
        stages = (
            RecomputeStage.SEARCH,
            RecomputeStage.EXTRACTION,
            RecomputeStage.ANALYSIS,
            RecomputeStage.RESULT_MODE,
        )
        if category_changed:
            reason = "A different product category needs new candidate research."
        elif region_changed or currency_changed:
            reason = "Regional or currency-sensitive listings need new research."
        elif preference_changed:
            reason = "The new requirement may need facts missing from saved research."
        else:
            reason = (
                "Prior candidate evidence is missing or no longer valid for this brief."
            )
    elif budget_changed:
        stages = (RecomputeStage.ANALYSIS, RecomputeStage.RESULT_MODE)
        reason = "The budget changes fit and ranking, while saved candidate evidence remains usable."
    else:
        stages = (RecomputeStage.RESULT_MODE,)
        reason = "Only the requested result mode changes; saved comparison evidence remains usable."

    research_invalid = RecomputeStage.SEARCH in stages
    analysis_invalid = RecomputeStage.ANALYSIS in stages
    decisions = (
        ArtifactDecision(
            artifact=RefinementArtifact.SHOPPING_BRIEF,
            disposition=(
                ArtifactDisposition.INVALIDATED
                if RecomputeStage.RE_INTAKE in stages
                else ArtifactDisposition.REUSED
            ),
            reason=(
                reason
                if RecomputeStage.RE_INTAKE in stages
                else "The saved brief is the base for the typed refinement changes."
            ),
        ),
        *(
            ArtifactDecision(
                artifact=artifact,
                disposition=(
                    ArtifactDisposition.INVALIDATED
                    if research_invalid
                    else ArtifactDisposition.REUSED
                ),
                reason=(
                    reason
                    if research_invalid
                    else "Prior run evidence may be reused after ID validation."
                ),
            )
            for artifact in _RESEARCH
        ),
        *(
            ArtifactDecision(
                artifact=artifact,
                disposition=(
                    ArtifactDisposition.INVALIDATED
                    if analysis_invalid
                    else ArtifactDisposition.REUSED
                ),
                reason=(
                    reason
                    if analysis_invalid
                    else "The saved comparison remains applicable."
                ),
            )
            for artifact in _ANALYSIS
        ),
        *(
            ArtifactDecision(
                artifact=artifact,
                disposition=ArtifactDisposition.INVALIDATED,
                reason="A new decision and independent verification are required for every refinement.",
            )
            for artifact in _DECISION
        ),
    )
    return RecomputePlan(
        refinement_id=refinement.refinement_id,
        session_id=session_id,
        run_id=run_id,
        prior_run_id=prior_result.result_version.run_id,
        prior_result_version_id=prior_result.result_version.result_version_id,
        base_brief=base_brief,
        target_brief=target_brief,
        requested_result_mode=refinement.result_mode,
        stages=stages,
        artifacts=decisions,
    )
