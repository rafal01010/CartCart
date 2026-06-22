import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from agents import Agent, ModelSettings, RunConfig, Runner
from pydantic import ValidationError

from app.agents.contracts import ComparisonDecisionAgentInput
from app.agents.openai_config import build_openai_agent_run_configuration
from app.core.settings import Settings
from app.schemas.analysis import (
    CategoryAnalysis,
    ComparisonCriterion,
    ComparisonMatrix,
    ComparisonRow,
    ListingTrustAssessment,
    ListingTrustLevel,
    RecommendationBundle,
    RecommendationMode,
    RecommendationModeResult,
    RejectedItem,
    RejectionSeverity,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import ListingId, ProductId, SourceId, new_id
from app.schemas.intake import BudgetMode
from app.schemas.products import CanonicalProduct, ProductListing
from app.schemas.search_sources import SourceQualityLevel


_REQUIRED_PICK_MODES = frozenset(
    {
        RecommendationMode.BEST_OVERALL,
        RecommendationMode.BEST_VALUE,
    }
)
_BLOCKING_TRUST_LEVELS = frozenset({ListingTrustLevel.SUSPICIOUS})
_WEAK_TRUST_LEVELS = frozenset(
    {
        ListingTrustLevel.WEAK,
        ListingTrustLevel.UNKNOWN,
    }
)


class ComparisonDecisionModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        """Run the SDK comparison decision agent and return its raw run result."""


@dataclass
class OpenAIAgentsSDKComparisonDecisionModelRunner:
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        return await Runner.run(
            agent,
            model_input,
            run_config=run_config,
            max_turns=max_turns,
        )


@dataclass
class MockComparisonDecisionModelRunner:
    output: RecommendationBundle | dict[str, Any] | None = None
    error: BaseException | None = None
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        del agent, run_config, max_turns
        self.calls += 1
        if self.error is not None:
            raise self.error
        output = self.output or _mock_bundle_from_model_input(model_input)
        return _MockRunResult(final_output=output)


@dataclass
class LiveComparisonDecisionAgent:
    settings: Settings
    model_runner: ComparisonDecisionModelRunner = field(
        default_factory=OpenAIAgentsSDKComparisonDecisionModelRunner,
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    async def run(self, input_data: ComparisonDecisionAgentInput) -> RecommendationBundle:
        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name="ComparisonDecisionAgent",
            run_id=str(input_data.run_id),
        )
        agent = _build_comparison_decision_agent(configuration.model)
        run_config = RunConfig(
            model=configuration.model,
            model_settings=ModelSettings(
                temperature=0,
                max_tokens=1700,
                include_usage=True,
            ),
            tracing_disabled=not configuration.tracing_enabled,
            trace_include_sensitive_data=configuration.trace_include_sensitive_data,
            workflow_name=configuration.trace_workflow_name,
            trace_metadata=configuration.trace_metadata,
        )

        try:
            raw_result = await asyncio.wait_for(
                self.model_runner.run(
                    agent,
                    _model_input(input_data),
                    run_config=run_config,
                    max_turns=configuration.max_turns,
                ),
                timeout=configuration.timeout_seconds,
            )
            bundle = _coerce_recommendation_bundle_result(
                getattr(raw_result, "final_output", raw_result),
                input_data,
            )
        except TimeoutError:
            bundle = _fallback_recommendation_bundle(input_data)
            self._set_activity("timeout_fallback", input_data, bundle)
            return bundle
        except (ValidationError, ValueError, TypeError):
            bundle = _fallback_recommendation_bundle(input_data)
            self._set_activity("schema_invalid_fallback", input_data, bundle)
            return bundle
        except Exception:
            bundle = _fallback_recommendation_bundle(input_data)
            self._set_activity("error_fallback", input_data, bundle)
            return bundle

        self._set_activity("model_comparison_decision_completed", input_data, bundle)
        return bundle

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    def _set_activity(
        self,
        status: str,
        input_data: ComparisonDecisionAgentInput,
        bundle: RecommendationBundle,
    ) -> None:
        self._workbench_activity = (
            {
                "tool_name": "openai_agents_structured_output",
                "status": status,
                "input": {
                    "agent": "ComparisonDecisionAgent",
                    "allowed_tools": [],
                    "product_count": len(input_data.products),
                    "listing_count": len(input_data.listings),
                    "analysis_count": len(input_data.category_analyses),
                    "trust_assessment_count": len(input_data.trust_assessments),
                    "evidence_count": len(input_data.evidence),
                    "has_budget": input_data.brief.budget is not None,
                },
                "output": bundle.model_dump(mode="json"),
            },
        )


@dataclass
class _MockRunResult:
    final_output: Any


@dataclass(frozen=True)
class _CandidateDecision:
    product: CanonicalProduct
    listing: ProductListing | None
    analysis: CategoryAnalysis | None
    trust: ListingTrustAssessment | None
    fit_score: float
    value_score: float
    trust_score: float
    evidence_score: float
    total_score: float
    within_budget: bool
    over_budget: bool
    hard_over_budget: bool
    unsafe_listing: bool
    evidence_ids: tuple[SourceId, ...]
    source_ids: tuple[SourceId, ...]

    @property
    def listing_id(self) -> ListingId | None:
        return self.listing.listing_id if self.listing is not None else None


@dataclass(frozen=True)
class _BudgetStatus:
    comparable: bool = False
    within: bool = False
    over: bool = False
    hard_over: bool = False
    soft_over: bool = False
    ratio: Decimal | None = None


def _build_comparison_decision_agent(model: str) -> Agent[Any]:
    return Agent(
        name="CartCartComparisonDecisionAgent",
        model=model,
        model_settings=ModelSettings(
            temperature=0,
            max_tokens=1700,
            include_usage=True,
        ),
        instructions=(
            "Compare the supplied assessed shopping candidates and return only "
            "a structured RecommendationBundle. Generate a comparison matrix, "
            "one best overall pick or an explicit no-strong-buy outcome, best "
            "value, within-budget pick when budget evidence exists, stretch "
            "pick only when justified, runner-ups, warnings, and rejected items "
            "only for meaningful reasons such as suspicious listing, hard-budget "
            "miss, poor fit, weak evidence, or missing critical requirements. "
            "Use only the supplied brief, products, listings, category analyses, "
            "listing trust assessments, dedupe decisions, and evidence. Preserve "
            "known product_id, listing_id, evidence_id, and source_id values; do "
            "not invent candidate IDs, product facts, specs, seller facts, prices, "
            "warranty facts, review claims, or source claims. Keep product quality "
            "separate from listing trust. Do not recommend a suspicious listing "
            "unless the output blocks or excludes it with a clear warning. Respect "
            "hard budget caps; with a preferred budget, include a within-budget "
            "alternative or explicit no-strong-buy reasoning if a stretch pick is "
            "mentioned. Do not search, browse, call tools, or expose agents, "
            "providers, prompts, traces, policies, or schemas to shoppers."
        ),
        tools=[],
        output_type=RecommendationBundle,
    )


def _model_input(input_data: ComparisonDecisionAgentInput) -> str:
    return json.dumps(
        {
            "run_id": str(input_data.run_id),
            "brief": input_data.brief.model_dump(mode="json"),
            "products": [
                product.model_dump(mode="json") for product in input_data.products
            ],
            "listings": [
                listing.model_dump(mode="json") for listing in input_data.listings
            ],
            "category_analyses": [
                analysis.model_dump(mode="json")
                for analysis in input_data.category_analyses
            ],
            "trust_assessments": [
                assessment.model_dump(mode="json")
                for assessment in input_data.trust_assessments
            ],
            "deduplication_decisions": [
                decision.model_dump(mode="json")
                for decision in input_data.deduplication_decisions
            ],
            "evidence": [
                evidence.model_dump(mode="json") for evidence in input_data.evidence
            ],
            "user_added_products": [
                item.model_dump(mode="json") for item in input_data.user_added_products
            ],
        },
        sort_keys=True,
    )


def _coerce_recommendation_bundle_result(
    value: Any,
    input_data: ComparisonDecisionAgentInput,
) -> RecommendationBundle:
    bundle = (
        value
        if isinstance(value, RecommendationBundle)
        else RecommendationBundle.model_validate(value)
    )
    bundle = _normalize_recommendation_bundle(bundle, input_data)
    _validate_recommendation_policy(bundle, input_data)
    return bundle


def _normalize_recommendation_bundle(
    bundle: RecommendationBundle,
    input_data: ComparisonDecisionAgentInput,
) -> RecommendationBundle:
    _validate_known_product_id(bundle.final_product_id, input_data)
    _validate_known_listing_id(bundle.final_listing_id, input_data)
    if bundle.final_product_id is not None and bundle.final_listing_id is not None:
        _validate_listing_matches_product(
            bundle.final_listing_id,
            bundle.final_product_id,
            input_data,
        )

    matrix = _normalize_comparison_matrix(bundle.comparison_matrix, input_data)
    mode_results = tuple(
        _normalize_mode_result(result, input_data) for result in bundle.mode_results
    )
    rejected_items = tuple(
        _normalize_rejected_item(item, input_data) for item in bundle.rejected_items
    )
    for product_id in bundle.runner_up_product_ids:
        _validate_known_product_id(product_id, input_data)

    evidence_ids = _dedupe_source_ids(
        (*bundle.evidence_ids, *_evidence_ids_from_modes(mode_results))
    )
    _validate_known_evidence_ids(evidence_ids, input_data)
    source_ids = _normalize_source_ids(bundle.source_ids, evidence_ids, input_data)

    return bundle.model_copy(
        update={
            "mode_results": mode_results,
            "comparison_matrix": matrix,
            "rejected_items": rejected_items,
            "evidence_ids": evidence_ids,
            "source_ids": source_ids,
        }
    )


def _normalize_comparison_matrix(
    matrix: ComparisonMatrix,
    input_data: ComparisonDecisionAgentInput,
) -> ComparisonMatrix:
    rows = []
    for row in matrix.rows:
        _validate_known_product_id(row.product_id, input_data)
        _validate_known_listing_id(row.listing_id, input_data)
        if row.listing_id is not None:
            _validate_listing_matches_product(row.listing_id, row.product_id, input_data)
        _validate_known_evidence_ids(row.evidence_ids, input_data)
        rows.append(row)
    return matrix.model_copy(update={"rows": tuple(rows)})


def _normalize_mode_result(
    result: RecommendationModeResult,
    input_data: ComparisonDecisionAgentInput,
) -> RecommendationModeResult:
    _validate_known_product_id(result.product_id, input_data)
    _validate_known_listing_id(result.listing_id, input_data)
    if result.listing_id is not None:
        _validate_listing_matches_product(result.listing_id, result.product_id, input_data)
    _validate_known_evidence_ids(result.evidence_ids, input_data)
    source_ids = _normalize_source_ids(result.source_ids, result.evidence_ids, input_data)
    return result.model_copy(update={"source_ids": source_ids})


def _normalize_rejected_item(
    item: RejectedItem,
    input_data: ComparisonDecisionAgentInput,
) -> RejectedItem:
    _validate_known_product_id(item.product_id, input_data)
    _validate_known_listing_id(item.listing_id, input_data)
    if item.product_id is not None and item.listing_id is not None:
        _validate_listing_matches_product(item.listing_id, item.product_id, input_data)
    _validate_known_evidence_ids(item.evidence_ids, input_data)
    source_ids = _normalize_source_ids(item.source_ids, item.evidence_ids, input_data)
    return item.model_copy(update={"source_ids": source_ids})


def _validate_recommendation_policy(
    bundle: RecommendationBundle,
    input_data: ComparisonDecisionAgentInput,
) -> None:
    if bundle.no_strong_buy:
        return

    decisions = _candidate_decisions(input_data)
    mode_set = {result.mode for result in bundle.mode_results}
    if not _REQUIRED_PICK_MODES.issubset(mode_set):
        raise ValueError("comparison output must include best overall and best value.")
    if bundle.final_rationale is None:
        raise ValueError("comparison output with a final pick requires rationale.")

    _validate_budget_semantics(bundle, input_data)

    if input_data.brief.budget is not None and _has_within_budget_candidate(decisions):
        if RecommendationMode.WITHIN_BUDGET not in mode_set:
            raise ValueError("budgeted comparison output requires a within-budget mode.")

    if _has_soft_budget_stretch_candidate(decisions, input_data):
        if RecommendationMode.STRETCH_PICK not in mode_set:
            raise ValueError("soft-budget stretch candidates require a stretch mode.")

    if bundle.final_listing_id is not None:
        assessment = _trust_by_listing_id(input_data).get(bundle.final_listing_id)
        if assessment is not None and assessment.level in _BLOCKING_TRUST_LEVELS:
            if not _has_blocking_listing_warning(bundle, bundle.final_listing_id):
                raise ValueError(
                    "suspicious final listings require blocking warning or exclusion."
                )


def _validate_budget_semantics(
    bundle: RecommendationBundle,
    input_data: ComparisonDecisionAgentInput,
) -> None:
    budget = input_data.brief.budget
    if budget is None:
        budget_modes = {
            RecommendationMode.WITHIN_BUDGET,
            RecommendationMode.STRETCH_PICK,
        }
        if any(result.mode in budget_modes for result in bundle.mode_results):
            raise ValueError("budget recommendation modes require a stated budget.")
        return

    if budget.mode == BudgetMode.HARD_CAP:
        for label, listing_id in _recommendation_listing_surfaces(bundle):
            if _budget_status_for_listing_id(listing_id, input_data).hard_over:
                raise ValueError(
                    f"{label} is above the user's hard budget cap."
                )
        if any(
            result.mode == RecommendationMode.STRETCH_PICK
            for result in bundle.mode_results
        ):
            raise ValueError("stretch picks are not valid under a hard budget cap.")

    within_budget_results = tuple(
        result
        for result in bundle.mode_results
        if result.mode == RecommendationMode.WITHIN_BUDGET
    )
    for result in within_budget_results:
        if not _budget_status_for_listing_id(result.listing_id, input_data).within:
            raise ValueError(
                "within-budget mode must use a listing at or below the stated budget."
            )

    stretch_results = tuple(
        result
        for result in bundle.mode_results
        if result.mode == RecommendationMode.STRETCH_PICK
    )
    if stretch_results and budget.mode != BudgetMode.PREFERRED:
        raise ValueError("stretch picks require a preferred budget.")
    for result in stretch_results:
        if not _budget_status_for_listing_id(result.listing_id, input_data).soft_over:
            raise ValueError(
                "stretch pick must be above a preferred budget, not within budget."
            )
        if not _has_budget_tradeoff_text(result.rationale):
            raise ValueError("stretch pick rationale must explain the budget tradeoff.")

    if budget.mode != BudgetMode.PREFERRED:
        return

    soft_over_surfaces = tuple(
        (label, listing_id)
        for label, listing_id in _recommendation_listing_surfaces(bundle)
        if _budget_status_for_listing_id(listing_id, input_data).soft_over
    )
    if not soft_over_surfaces:
        return

    if not within_budget_results:
        raise ValueError(
            "preferred-budget stretch recommendations require a within-budget mode."
        )
    if not stretch_results:
        raise ValueError(
            "preferred-budget over-budget recommendations require a stretch mode."
        )
    if not _has_budget_tradeoff_text(
        " ".join(
            (
                bundle.final_rationale or "",
                *bundle.warnings,
                *(result.rationale for result in bundle.mode_results),
            )
        )
    ):
        raise ValueError(
            "preferred-budget stretch recommendations must explain the tradeoff."
        )


def _recommendation_listing_surfaces(
    bundle: RecommendationBundle,
) -> tuple[tuple[str, ListingId | None], ...]:
    return (
        (("final pick", bundle.final_listing_id),)
        + tuple((result.mode.value, result.listing_id) for result in bundle.mode_results)
    )


def _budget_status_for_listing_id(
    listing_id: ListingId | None,
    input_data: ComparisonDecisionAgentInput,
) -> _BudgetStatus:
    if listing_id is None:
        return _BudgetStatus()
    listing = _listings_by_id(input_data).get(listing_id)
    return _budget_status(listing, input_data.brief.budget)


def _budget_status(
    listing: ProductListing | None,
    budget: Any,
) -> _BudgetStatus:
    if listing is None or listing.price is None or budget is None:
        return _BudgetStatus()
    if listing.price.currency != budget.amount.currency:
        return _BudgetStatus()

    try:
        price = Decimal(listing.price.amount)
        amount = Decimal(budget.amount.amount)
    except (InvalidOperation, ValueError):
        return _BudgetStatus()
    if amount <= 0:
        return _BudgetStatus()

    ratio = price / amount
    within = ratio <= 1
    over = ratio > 1
    return _BudgetStatus(
        comparable=True,
        within=within,
        over=over,
        hard_over=over and budget.mode == BudgetMode.HARD_CAP,
        soft_over=over and budget.mode == BudgetMode.PREFERRED,
        ratio=ratio,
    )


def _has_budget_tradeoff_text(text: str) -> bool:
    normalized = text.casefold()
    return "budget" in normalized and any(
        marker in normalized
        for marker in (
            "stretch",
            "flexible",
            "tradeoff",
            "costs more",
            "above",
            "over",
            "spend",
        )
    )


def _fallback_recommendation_bundle(
    input_data: ComparisonDecisionAgentInput,
) -> RecommendationBundle:
    decisions = _candidate_decisions(input_data)
    matrix = _comparison_matrix(decisions)
    rejected_items = _rejected_items(decisions)
    recommendable = tuple(
        decision
        for decision in sorted(decisions, key=lambda item: item.total_score, reverse=True)
        if _is_recommendable(decision)
    )

    if not recommendable or _soft_budget_needs_no_strong_buy(decisions, input_data):
        evidence_ids = _bundle_evidence_ids(decisions, input_data)
        return RecommendationBundle(
            no_strong_buy=True,
            no_strong_buy_reason=_no_strong_buy_reason(decisions, input_data),
            comparison_matrix=matrix,
            rejected_items=rejected_items,
            warnings=("No candidate clears the fit, budget, evidence, and listing-trust bar.",),
            evidence_ids=evidence_ids,
            source_ids=_source_ids_for_evidence_ids(input_data, evidence_ids),
        )

    best = recommendable[0]
    runner_ups = recommendable[1:3]
    mode_results = _mode_results(best, runner_ups, recommendable, decisions, input_data)
    evidence_ids = _dedupe_source_ids(
        (
            *_bundle_evidence_ids(decisions, input_data),
            *_evidence_ids_from_modes(mode_results),
            *(item.evidence_id for item in input_data.evidence),
        )
    )
    return RecommendationBundle(
        final_product_id=best.product.product_id,
        final_listing_id=best.listing_id,
        final_rationale=_final_rationale(best),
        runner_up_product_ids=tuple(item.product.product_id for item in runner_ups),
        mode_results=mode_results,
        comparison_matrix=matrix,
        rejected_items=rejected_items,
        warnings=_bundle_warnings(decisions),
        evidence_ids=evidence_ids,
        source_ids=_source_ids_for_evidence_ids(input_data, evidence_ids),
    )


def _candidate_decisions(
    input_data: ComparisonDecisionAgentInput,
) -> tuple[_CandidateDecision, ...]:
    analyses = _analysis_by_product_id(input_data)
    trust = _trust_by_listing_id(input_data)
    listings_by_product = _listings_by_product_id(input_data)
    decisions = []
    for product in input_data.products:
        listing_options = listings_by_product.get(product.product_id) or (None,)
        listing_decisions = tuple(
            _candidate_decision(
                product,
                listing,
                analyses.get(product.product_id),
                trust,
                input_data,
            )
            for listing in listing_options
        )
        decisions.append(
            max(
                listing_decisions,
                key=lambda item: (
                    not item.unsafe_listing,
                    not item.hard_over_budget,
                    item.total_score,
                ),
            )
        )
    return tuple(decisions)


def _candidate_decision(
    product: CanonicalProduct,
    listing: ProductListing | None,
    analysis: CategoryAnalysis | None,
    trust_by_listing: dict[ListingId, ListingTrustAssessment],
    input_data: ComparisonDecisionAgentInput,
) -> _CandidateDecision:
    assessment = trust_by_listing.get(listing.listing_id) if listing else None
    fit_score = _fit_score(analysis)
    value_score, within_budget, over_budget, hard_over_budget = _value_score(
        listing,
        input_data,
    )
    trust_score = _trust_score(assessment, listing)
    evidence_score = _evidence_score(product, listing, analysis, assessment, input_data)
    unsafe_listing = assessment is not None and assessment.level in _BLOCKING_TRUST_LEVELS
    total_score = (
        fit_score * 0.42
        + value_score * 0.24
        + trust_score * 0.22
        + evidence_score * 0.12
    )
    if unsafe_listing:
        total_score = min(total_score, 0.34)
    if hard_over_budget:
        total_score = min(total_score, 0.45)
    evidence_ids = _candidate_evidence_ids(
        product,
        listing,
        analysis,
        assessment,
        input_data,
    )
    return _CandidateDecision(
        product=product,
        listing=listing,
        analysis=analysis,
        trust=assessment,
        fit_score=round(_clamp(fit_score), 3),
        value_score=round(_clamp(value_score), 3),
        trust_score=round(_clamp(trust_score), 3),
        evidence_score=round(_clamp(evidence_score), 3),
        total_score=round(_clamp(total_score), 3),
        within_budget=within_budget,
        over_budget=over_budget,
        hard_over_budget=hard_over_budget,
        unsafe_listing=unsafe_listing,
        evidence_ids=evidence_ids,
        source_ids=_candidate_source_ids(
            product,
            listing,
            analysis,
            assessment,
            input_data,
        ),
    )


def _fit_score(analysis: CategoryAnalysis | None) -> float:
    if analysis is None:
        return 0.42
    score = analysis.confidence.score
    score += min(len(analysis.strengths), 3) * 0.05
    score -= min(len(analysis.weaknesses), 3) * 0.03
    score -= min(len(analysis.warnings), 2) * 0.05
    return _clamp(score)


def _value_score(
    listing: ProductListing | None,
    input_data: ComparisonDecisionAgentInput,
) -> tuple[float, bool, bool, bool]:
    if listing is None or listing.price is None:
        return 0.45, False, False, False
    status = _budget_status(listing, input_data.brief.budget)
    if not status.comparable or status.ratio is None:
        return 0.56, False, False, False

    ratio = status.ratio
    if status.within:
        return float(_clamp(1 - (ratio * Decimal("0.35")))), True, False, False
    if status.hard_over:
        return 0.2, False, True, True
    stretch_score = max(0.25, 0.58 - float(min(ratio - 1, Decimal("1.0"))) * 0.5)
    return stretch_score, False, True, False


def _trust_score(
    assessment: ListingTrustAssessment | None,
    listing: ProductListing | None,
) -> float:
    if assessment is None:
        if listing is None:
            return 0.5
        if listing.seller.is_marketplace_seller is False:
            return 0.6
        return 0.42
    return {
        ListingTrustLevel.STRONG: 0.92,
        ListingTrustLevel.REASONABLE: 0.76,
        ListingTrustLevel.MIXED: 0.55,
        ListingTrustLevel.UNKNOWN: 0.38,
        ListingTrustLevel.WEAK: 0.25,
        ListingTrustLevel.SUSPICIOUS: 0.05,
    }[assessment.level]


def _evidence_score(
    product: CanonicalProduct,
    listing: ProductListing | None,
    analysis: CategoryAnalysis | None,
    assessment: ListingTrustAssessment | None,
    input_data: ComparisonDecisionAgentInput,
) -> float:
    source_ids = set(_candidate_source_ids(product, listing, analysis, assessment, input_data))
    evidence = [
        item
        for item in input_data.evidence
        if item.source_id in source_ids
        or item.target.product_id == product.product_id
        or (listing is not None and item.target.listing_id == listing.listing_id)
    ]
    if not evidence:
        return analysis.confidence.score * 0.8 if analysis is not None else 0.35
    quality_scores = []
    for item in evidence:
        if item.source_quality.score is not None:
            quality_scores.append(item.source_quality.score)
            continue
        quality_scores.append(
            {
                SourceQualityLevel.STRONG: 0.9,
                SourceQualityLevel.ADEQUATE: 0.68,
                SourceQualityLevel.MIXED: 0.46,
                SourceQualityLevel.WEAK: 0.25,
                SourceQualityLevel.UNKNOWN: 0.35,
            }[item.source_quality.level]
        )
    confidence_score = sum(item.confidence.score for item in evidence) / len(evidence)
    quality_score = sum(quality_scores) / len(quality_scores)
    return _clamp((confidence_score + quality_score) / 2)


def _comparison_matrix(decisions: tuple[_CandidateDecision, ...]) -> ComparisonMatrix:
    criteria = (
        ComparisonCriterion(name="fit", weight=0.35),
        ComparisonCriterion(name="value", weight=0.25),
        ComparisonCriterion(name="listing_trust", weight=0.25),
        ComparisonCriterion(name="evidence", weight=0.15),
    )
    rows = tuple(
        ComparisonRow(
            product_id=decision.product.product_id,
            listing_id=decision.listing_id,
            scores={
                "fit": decision.fit_score,
                "value": decision.value_score,
                "listing_trust": decision.trust_score,
                "evidence": decision.evidence_score,
            },
            evidence_ids=decision.evidence_ids,
            summary=_row_summary(decision),
        )
        for decision in decisions
    )
    return ComparisonMatrix(criteria=criteria, rows=rows)


def _mode_results(
    best: _CandidateDecision,
    runner_ups: tuple[_CandidateDecision, ...],
    recommendable: tuple[_CandidateDecision, ...],
    decisions: tuple[_CandidateDecision, ...],
    input_data: ComparisonDecisionAgentInput,
) -> tuple[RecommendationModeResult, ...]:
    results = [
        _mode_result(
            RecommendationMode.BEST_OVERALL,
            best,
            "Best overall",
            _final_rationale(best),
        )
    ]

    best_value = max(recommendable, key=lambda item: (item.value_score, item.total_score))
    results.append(
        _mode_result(
            RecommendationMode.BEST_VALUE,
            best_value,
            "Best value",
            "Best balance of price, fit, listing trust, and source-backed confidence.",
        )
    )

    within_budget = tuple(
        decision
        for decision in recommendable
        if decision.within_budget or input_data.brief.budget is None
    )
    if input_data.brief.budget is not None and within_budget:
        pick = max(within_budget, key=lambda item: item.total_score)
        results.append(
            _mode_result(
                RecommendationMode.WITHIN_BUDGET,
                pick,
                "Within budget",
                "Best candidate that stays within the stated budget.",
            )
        )

    stretch_candidates = tuple(
        decision
        for decision in decisions
        if decision.over_budget and _is_soft_budget_stretch(decision, input_data)
    )
    if stretch_candidates:
        pick = max(stretch_candidates, key=lambda item: item.total_score)
        results.append(
            _mode_result(
                RecommendationMode.STRETCH_PICK,
                pick,
                "Stretch pick",
                "Worth considering only if the budget is flexible and the tradeoff is acceptable.",
            )
        )

    for runner_up in runner_ups:
        results.append(
            _mode_result(
                RecommendationMode.RUNNER_UP,
                runner_up,
                "Runner-up",
                "A credible alternative, but not the strongest overall balance.",
            )
        )
    return tuple(results)


def _mode_result(
    mode: RecommendationMode,
    decision: _CandidateDecision,
    title: str,
    rationale: str,
) -> RecommendationModeResult:
    return RecommendationModeResult(
        mode=mode,
        product_id=decision.product.product_id,
        listing_id=decision.listing_id,
        title=title,
        rationale=rationale,
        confidence=_confidence(
            min(0.9, max(0.42, decision.total_score)),
            "Confidence combines supplied fit analysis, price/budget fit, listing trust, and evidence quality.",
        ),
        evidence_ids=decision.evidence_ids,
        source_ids=decision.source_ids,
    )


def _rejected_items(decisions: tuple[_CandidateDecision, ...]) -> tuple[RejectedItem, ...]:
    items = []
    for decision in decisions:
        if decision.unsafe_listing:
            items.append(
                RejectedItem(
                    product_id=decision.product.product_id,
                    listing_id=decision.listing_id,
                    reason="Listing trust is suspicious, so it should not be treated as a safe buy.",
                    severity=RejectionSeverity.BLOCKING,
                    evidence_ids=decision.evidence_ids,
                    source_ids=decision.source_ids,
                )
            )
        elif decision.hard_over_budget:
            items.append(
                RejectedItem(
                    product_id=decision.product.product_id,
                    listing_id=decision.listing_id,
                    reason="Price is above the hard budget cap.",
                    severity=RejectionSeverity.HIGH,
                    evidence_ids=decision.evidence_ids,
                    source_ids=decision.source_ids,
                )
            )
        elif decision.evidence_score < 0.28:
            items.append(
                RejectedItem(
                    product_id=decision.product.product_id,
                    listing_id=decision.listing_id,
                    reason="Source evidence is too weak to support a recommendation.",
                    severity=RejectionSeverity.MEDIUM,
                    evidence_ids=decision.evidence_ids,
                    source_ids=decision.source_ids,
                )
            )
    return tuple(items)


def _is_recommendable(decision: _CandidateDecision) -> bool:
    if decision.unsafe_listing or decision.hard_over_budget:
        return False
    if decision.trust is not None and decision.trust.level in _WEAK_TRUST_LEVELS:
        return False
    return decision.total_score >= 0.56 and decision.evidence_score >= 0.35


def _is_soft_budget_stretch(
    decision: _CandidateDecision,
    input_data: ComparisonDecisionAgentInput,
) -> bool:
    budget = input_data.brief.budget
    if budget is None or budget.mode != BudgetMode.PREFERRED:
        return False
    return decision.over_budget and not decision.hard_over_budget and not decision.unsafe_listing


def _soft_budget_needs_no_strong_buy(
    decisions: tuple[_CandidateDecision, ...],
    input_data: ComparisonDecisionAgentInput,
) -> bool:
    return _has_soft_budget_stretch_candidate(
        decisions,
        input_data,
    ) and not _has_within_budget_candidate(decisions)


def _mock_bundle_from_model_input(model_input: str) -> RecommendationBundle:
    payload = json.loads(model_input)
    input_data = ComparisonDecisionAgentInput.model_validate(
        {
            "run_id": payload["run_id"],
            "brief": payload["brief"],
            "products": payload["products"],
            "listings": payload["listings"],
            "category_analyses": payload["category_analyses"],
            "trust_assessments": payload["trust_assessments"],
            "deduplication_decisions": payload["deduplication_decisions"],
            "evidence": payload["evidence"],
            "user_added_products": payload["user_added_products"],
        }
    )
    return _fallback_recommendation_bundle(input_data)


def _analysis_by_product_id(
    input_data: ComparisonDecisionAgentInput,
) -> dict[ProductId, CategoryAnalysis]:
    analyses: dict[ProductId, CategoryAnalysis] = {}
    for analysis in input_data.category_analyses:
        current = analyses.get(analysis.product_id)
        if current is None or analysis.confidence.score > current.confidence.score:
            analyses[analysis.product_id] = analysis
    return analyses


def _trust_by_listing_id(
    input_data: ComparisonDecisionAgentInput,
) -> dict[ListingId, ListingTrustAssessment]:
    return {assessment.listing_id: assessment for assessment in input_data.trust_assessments}


def _listings_by_product_id(
    input_data: ComparisonDecisionAgentInput,
) -> dict[ProductId, tuple[ProductListing, ...]]:
    grouped: dict[ProductId, list[ProductListing]] = {}
    for listing in input_data.listings:
        grouped.setdefault(listing.product_id, []).append(listing)
    return {product_id: tuple(items) for product_id, items in grouped.items()}


def _listings_by_id(
    input_data: ComparisonDecisionAgentInput,
) -> dict[ListingId, ProductListing]:
    return {listing.listing_id: listing for listing in input_data.listings}


def _candidate_evidence_ids(
    product: CanonicalProduct,
    listing: ProductListing | None,
    analysis: CategoryAnalysis | None,
    assessment: ListingTrustAssessment | None,
    input_data: ComparisonDecisionAgentInput,
) -> tuple[SourceId, ...]:
    evidence_ids: list[SourceId] = []
    if analysis is not None:
        evidence_ids.extend(analysis.evidence_ids)
    if assessment is not None:
        evidence_ids.extend(assessment.evidence_ids)
    for evidence in input_data.evidence:
        if evidence.target.product_id == product.product_id:
            evidence_ids.append(evidence.evidence_id)
        if listing is not None and evidence.target.listing_id == listing.listing_id:
            evidence_ids.append(evidence.evidence_id)
    return _dedupe_source_ids(evidence_ids) or _fallback_evidence_ids(input_data)


def _candidate_source_ids(
    product: CanonicalProduct,
    listing: ProductListing | None,
    analysis: CategoryAnalysis | None,
    assessment: ListingTrustAssessment | None,
    input_data: ComparisonDecisionAgentInput,
) -> tuple[SourceId, ...]:
    source_ids: list[SourceId] = [*product.source_ids]
    if listing is not None:
        source_ids.extend(listing.source_ids)
        source_ids.extend(listing.seller.source_ids)
    if analysis is not None:
        source_ids.extend(analysis.source_ids)
    if assessment is not None:
        source_ids.extend(assessment.source_ids)
    for evidence in input_data.evidence:
        if evidence.target.product_id == product.product_id:
            source_ids.append(evidence.source_id)
        if listing is not None and evidence.target.listing_id == listing.listing_id:
            source_ids.append(evidence.source_id)
    return _dedupe_source_ids(source_ids)


def _bundle_evidence_ids(
    decisions: tuple[_CandidateDecision, ...],
    input_data: ComparisonDecisionAgentInput,
) -> tuple[SourceId, ...]:
    evidence_ids = _dedupe_source_ids(
        evidence_id for decision in decisions for evidence_id in decision.evidence_ids
    )
    return evidence_ids or _fallback_evidence_ids(input_data)


def _fallback_evidence_ids(input_data: ComparisonDecisionAgentInput) -> tuple[SourceId, ...]:
    evidence_ids = [item.evidence_id for item in input_data.evidence]
    for analysis in input_data.category_analyses:
        evidence_ids.extend(analysis.evidence_ids)
    for assessment in input_data.trust_assessments:
        evidence_ids.extend(assessment.evidence_ids)
    for decision in input_data.deduplication_decisions:
        evidence_ids.extend(decision.evidence_ids)
    if evidence_ids:
        return _dedupe_source_ids(evidence_ids)

    source_ids = _fallback_source_ids(input_data)
    return source_ids or (new_id(),)


def _fallback_source_ids(input_data: ComparisonDecisionAgentInput) -> tuple[SourceId, ...]:
    source_ids = [item.source_id for item in input_data.evidence]
    for product in input_data.products:
        source_ids.extend(product.source_ids)
    for listing in input_data.listings:
        source_ids.extend(listing.source_ids)
        source_ids.extend(listing.seller.source_ids)
    for analysis in input_data.category_analyses:
        source_ids.extend(analysis.source_ids)
    for assessment in input_data.trust_assessments:
        source_ids.extend(assessment.source_ids)
    for decision in input_data.deduplication_decisions:
        source_ids.extend(decision.source_ids)
    return _dedupe_source_ids(source_ids)


def _known_evidence_ids(input_data: ComparisonDecisionAgentInput) -> set[SourceId]:
    return set(_fallback_evidence_ids(input_data))


def _known_source_ids(input_data: ComparisonDecisionAgentInput) -> set[SourceId]:
    return set(_fallback_source_ids(input_data))


def _source_ids_for_evidence_ids(
    input_data: ComparisonDecisionAgentInput,
    evidence_ids: Iterable[SourceId],
) -> tuple[SourceId, ...]:
    by_evidence: dict[SourceId, list[SourceId]] = {}
    for item in input_data.evidence:
        by_evidence.setdefault(item.evidence_id, []).append(item.source_id)
    for analysis in input_data.category_analyses:
        for evidence_id in analysis.evidence_ids:
            by_evidence.setdefault(evidence_id, []).extend(analysis.source_ids)
    for assessment in input_data.trust_assessments:
        for evidence_id in assessment.evidence_ids:
            by_evidence.setdefault(evidence_id, []).extend(assessment.source_ids)
    for decision in input_data.deduplication_decisions:
        for evidence_id in decision.evidence_ids:
            by_evidence.setdefault(evidence_id, []).extend(decision.source_ids)

    source_ids: list[SourceId] = []
    for evidence_id in evidence_ids:
        source_ids.extend(by_evidence.get(evidence_id, ()))
        if evidence_id in _known_source_ids(input_data):
            source_ids.append(evidence_id)
    return _dedupe_source_ids(source_ids)


def _normalize_source_ids(
    source_ids: tuple[SourceId, ...],
    evidence_ids: tuple[SourceId, ...],
    input_data: ComparisonDecisionAgentInput,
) -> tuple[SourceId, ...]:
    known_source_ids = _known_source_ids(input_data)
    if known_source_ids and set(source_ids) - known_source_ids:
        raise ValueError("comparison output used unknown source IDs.")
    normalized = _dedupe_source_ids(
        (*source_ids, *_source_ids_for_evidence_ids(input_data, evidence_ids))
    )
    if known_source_ids and not normalized:
        raise ValueError("comparison output did not preserve source IDs.")
    return normalized


def _validate_known_product_id(
    product_id: ProductId | None,
    input_data: ComparisonDecisionAgentInput,
) -> None:
    if product_id is None:
        return
    if product_id not in {product.product_id for product in input_data.products}:
        raise ValueError("comparison output used an unknown product ID.")


def _validate_known_listing_id(
    listing_id: ListingId | None,
    input_data: ComparisonDecisionAgentInput,
) -> None:
    if listing_id is None:
        return
    if listing_id not in {listing.listing_id for listing in input_data.listings}:
        raise ValueError("comparison output used an unknown listing ID.")


def _validate_listing_matches_product(
    listing_id: ListingId,
    product_id: ProductId,
    input_data: ComparisonDecisionAgentInput,
) -> None:
    listing = next(
        item for item in input_data.listings if item.listing_id == listing_id
    )
    if listing.product_id != product_id:
        raise ValueError("comparison output mismatched product and listing IDs.")


def _validate_known_evidence_ids(
    evidence_ids: Iterable[SourceId],
    input_data: ComparisonDecisionAgentInput,
) -> None:
    unknown = set(evidence_ids) - _known_evidence_ids(input_data)
    if unknown:
        raise ValueError("comparison output used unknown evidence IDs.")


def _has_within_budget_candidate(
    decisions: tuple[_CandidateDecision, ...],
) -> bool:
    return any(
        decision.within_budget and _is_recommendable(decision)
        for decision in decisions
    )


def _has_soft_budget_stretch_candidate(
    decisions: tuple[_CandidateDecision, ...],
    input_data: ComparisonDecisionAgentInput,
) -> bool:
    budget = input_data.brief.budget
    if budget is None or budget.mode != BudgetMode.PREFERRED:
        return False
    return any(
        _is_soft_budget_stretch(decision, input_data) and _is_recommendable(decision)
        for decision in decisions
    )


def _has_blocking_listing_warning(
    bundle: RecommendationBundle,
    listing_id: ListingId,
) -> bool:
    warning_text = " ".join((*bundle.warnings, bundle.final_rationale or "")).casefold()
    has_warning = any(
        marker in warning_text
        for marker in ("suspicious", "unsafe", "avoid", "block", "listing trust", "seller")
    )
    has_rejection = any(item.listing_id == listing_id for item in bundle.rejected_items)
    return has_warning or has_rejection


def _evidence_ids_from_modes(
    mode_results: Iterable[RecommendationModeResult],
) -> tuple[SourceId, ...]:
    return _dedupe_source_ids(
        evidence_id for result in mode_results for evidence_id in result.evidence_ids
    )


def _row_summary(decision: _CandidateDecision) -> str:
    if decision.unsafe_listing:
        return "Rejected as a risky listing despite any product fit signals."
    if decision.hard_over_budget:
        return "Above the hard budget cap."
    if decision.trust is not None and decision.trust.level in _WEAK_TRUST_LEVELS:
        return "Listing trust is too weak for a confident recommendation."
    return "Compared on fit, value, listing trust, and evidence quality."


def _final_rationale(decision: _CandidateDecision) -> str:
    return (
        "Best overall balance of shopper fit, price/value, listing trust, and "
        "source-backed confidence among the supplied candidates."
    )


def _bundle_warnings(decisions: tuple[_CandidateDecision, ...]) -> tuple[str, ...]:
    warnings = []
    if any(decision.over_budget for decision in decisions):
        warnings.append("At least one candidate is over the stated budget.")
    if any(
        decision.trust is not None and decision.trust.level in _WEAK_TRUST_LEVELS
        for decision in decisions
    ):
        warnings.append("Some listings have weak or unknown seller/listing trust.")
    if any(decision.unsafe_listing for decision in decisions):
        warnings.append("Suspicious listings were excluded rather than recommended.")
    return tuple(warnings)


def _no_strong_buy_reason(
    decisions: tuple[_CandidateDecision, ...],
    input_data: ComparisonDecisionAgentInput,
) -> str:
    if any(decision.unsafe_listing for decision in decisions):
        return (
            "No candidate is a strong buy because the viable-looking options have "
            "suspicious listing trust or unsafe seller signals."
        )
    if any(decision.hard_over_budget for decision in decisions):
        return "No candidate is a strong buy within the hard budget cap."
    if _soft_budget_needs_no_strong_buy(decisions, input_data):
        return (
            "No candidate is a strong buy because the credible options are stretch "
            "buys above the preferred budget without a solid within-budget alternative."
        )
    return (
        "No candidate has enough combined fit, value, evidence quality, and "
        "listing trust to recommend confidently."
    )


def _confidence(score: float, rationale: str) -> Confidence:
    if score < 0.5:
        level = ConfidenceLevel.LOW
    elif score < 0.75:
        level = ConfidenceLevel.MEDIUM
    else:
        level = ConfidenceLevel.HIGH
    return Confidence(score=round(_clamp(score), 3), level=level, rationale=rationale)


def _dedupe_source_ids(source_ids: Iterable[SourceId]) -> tuple[SourceId, ...]:
    return tuple(dict.fromkeys(source_ids))


def _clamp(value: Decimal | float) -> float:
    numeric = float(value)
    if numeric < 0:
        return 0.0
    if numeric > 1:
        return 1.0
    return numeric
