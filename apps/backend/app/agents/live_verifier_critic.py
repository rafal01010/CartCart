import asyncio
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from agents import Agent, ModelSettings, RunConfig, Runner
from pydantic import ValidationError

from app.agents.contracts import VerificationAgentInput, VerificationReport
from app.agents.openai_config import build_openai_agent_run_configuration
from app.core.settings import Settings
from app.schemas.analysis import (
    DeduplicationOutcome,
    ListingTrustAssessment,
    ListingTrustLevel,
    RecommendationBundle,
    RecommendationMode,
    RejectionSeverity,
)
from app.schemas.ids import ListingId, ProductId, SourceId
from app.schemas.intake import BudgetMode
from app.schemas.search_sources import (
    EvidenceType,
    SourceQualityLevel,
)


_INTERNAL_LANGUAGE_PATTERNS = (
    r"\bagent\b",
    r"\bagents\b",
    r"\btool call\b",
    r"\bprovider\b",
    r"\bprompt\b",
    r"\btrace\b",
    r"\bschema\b",
    r"\bpydantic\b",
    r"\bjson\b",
    r"\btoken[s]?\b",
    r"\bmodel\b",
    r"\brun id\b",
    r"\brun_id\b",
)
_UNSAFE_PURCHASE_PATTERNS = (
    r"\bweapon\b",
    r"\bfirearm\b",
    r"\bammunition\b",
    r"\bexplosive\b",
    r"\billegal drug\b",
    r"\bcontrolled substance\b",
    r"\bcounterfeit\b",
    r"\bbypass safety\b",
    r"\bdisable safety\b",
)
_OVERCONFIDENT_PATTERNS = (
    r"\bguaranteed\b",
    r"\balways\b",
    r"\bnever fails\b",
    r"\bperfect\b",
    r"\bno risk\b",
    r"\bbest in every way\b",
)
_SUSPICIOUS_CAVEAT_PATTERNS = (
    r"\bsuspicious\b",
    r"\brisk[y]?\b",
    r"\bred flag\b",
    r"\bavoid\b",
    r"\bdo not buy\b",
    r"\bdo not recommend\b",
    r"\bnot a safe buy\b",
    r"\btrust\b",
    r"\bseller\b",
)
_CONFLICT_CAVEAT_PATTERNS = (
    r"\bconflict",
    r"\bmixed\b",
    r"\buncertain\b",
    r"\bweak evidence\b",
    r"\blimited evidence\b",
    r"\bgap\b",
    r"\btradeoff\b",
)
_FACTUAL_SPEC_PATTERNS = (
    r"\b\d+(?:\.\d+)?\s?(?:hz|mah|wh|w|gb|tb|inch|inches|ms|nits|k|fps)\b",
    r"\b\d{3,4}p\b",
    r"\b4k\b",
    r"\b8k\b",
    r"\buhd\b",
    r"\bqhd\b",
    r"\bfhd\b",
    r"\boled\b",
    r"\bmini[- ]?led\b",
    r"\bips\b",
    r"\bva panel\b",
    r"\busb[- ]?c\b",
    r"\bthunderbolt\b",
    r"\bwarranty\b",
    r"\breturn policy\b",
    r"\bshipping\b",
    r"\bships to\b",
    r"\bin stock\b",
    r"\bout of stock\b",
    r"\brating\b",
    r"\breviews?\b",
)
_STOPWORDS = frozenset(
    {
        "about",
        "again",
        "also",
        "because",
        "best",
        "better",
        "candidate",
        "cartcart",
        "clear",
        "from",
        "good",
        "into",
        "only",
        "overall",
        "pick",
        "price",
        "recommend",
        "recommendation",
        "selected",
        "should",
        "source",
        "strong",
        "synthetic",
        "than",
        "that",
        "this",
        "tradeoff",
        "value",
        "with",
        "workbench",
    }
)


class VerifierCriticModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        """Run the SDK verifier critic agent and return its raw run result."""


@dataclass
class OpenAIAgentsSDKVerifierCriticModelRunner:
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
class MockVerifierCriticModelRunner:
    output: VerificationReport | dict[str, Any] | None = None
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
        output = self.output or _mock_report_from_model_input(model_input)
        return _MockRunResult(final_output=output)


@dataclass
class LiveVerifierCriticAgent:
    settings: Settings
    model_runner: VerifierCriticModelRunner = field(
        default_factory=OpenAIAgentsSDKVerifierCriticModelRunner,
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    async def run(self, input_data: VerificationAgentInput) -> VerificationReport:
        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name="VerifierCriticAgent",
            run_id=str(input_data.run_id),
        )
        agent = _build_verifier_critic_agent(configuration.model)
        run_config = RunConfig(
            model=configuration.model,
            model_settings=ModelSettings(
                temperature=0,
                max_tokens=1500,
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
            report = _coerce_verification_report_result(
                getattr(raw_result, "final_output", raw_result),
                input_data,
            )
        except TimeoutError:
            report = _failure_report(
                input_data,
                "Verifier timed out; result output must not be shown until checked.",
            )
            self._set_activity("timeout_blocked", input_data, report)
            return report
        except (ValidationError, ValueError, TypeError):
            report = _failure_report(
                input_data,
                "Verifier output was invalid; result output must not be shown.",
            )
            self._set_activity("schema_invalid_blocked", input_data, report)
            return report
        except Exception:
            report = _failure_report(
                input_data,
                "Verifier failed; result output must not be shown until checked.",
            )
            self._set_activity("error_blocked", input_data, report)
            return report

        status = (
            "output_guardrail_blocked"
            if not report.approved
            else "model_verifier_critic_completed"
        )
        self._set_activity(status, input_data, report)
        return report

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    def _set_activity(
        self,
        status: str,
        input_data: VerificationAgentInput,
        report: VerificationReport,
    ) -> None:
        self._workbench_activity = (
            {
                "tool_name": "openai_agents_structured_output",
                "status": status,
                "input": {
                    "agent": "VerifierCriticAgent",
                    "allowed_tools": [],
                    "evidence_count": len(input_data.evidence),
                    "trust_assessment_count": len(input_data.trust_assessments),
                    "category_analysis_count": len(input_data.category_analyses),
                    "deduplication_decision_count": len(
                        input_data.deduplication_decisions
                    ),
                    "has_budget": input_data.brief.budget is not None,
                },
                "output": report.model_dump(mode="json"),
            },
        )


@dataclass
class _MockRunResult:
    final_output: Any


def _build_verifier_critic_agent(model: str) -> Agent[Any]:
    return Agent(
        name="CartCartVerifierCriticAgent",
        model=model,
        model_settings=ModelSettings(
            temperature=0,
            max_tokens=1500,
            include_usage=True,
        ),
        instructions=(
            "Verify the final shopping recommendation bundle and return only a "
            "structured VerificationReport. Use only the supplied brief, draft "
            "recommendation bundle, products, listings, source evidence, trust "
            "assessments, category analyses, and deduplication decisions. Check "
            "that factual product, listing, seller, price, region, review, and "
            "trust claims are backed by supplied evidence IDs; material conflicts "
            "or weak evidence are disclosed; hard budgets are respected; "
            "suspicious listings are rejected or clearly caveated; duplicate "
            "recommendation issues are not exposed; unsafe or off-scope purchase "
            "guidance is blocked; and shopper-facing copy does not mention agents, "
            "tools, providers, prompts, traces, schemas, tokens, JSON, or models. "
            "Do not search, browse, call tools, invent evidence IDs, invent source "
            "facts, or silently rewrite a failing result without listing blocking "
            "issues or notes. If the bundle cannot be safely approved, set "
            "approved=false and explain the blocking issues in regular-person "
            "language."
        ),
        tools=[],
        output_type=VerificationReport,
    )


def _model_input(input_data: VerificationAgentInput) -> str:
    return json.dumps(
        {
            "run_id": str(input_data.run_id),
            "brief": input_data.brief.model_dump(mode="json"),
            "recommendation_bundle": input_data.recommendation_bundle.model_dump(
                mode="json"
            ),
            "products": [
                product.model_dump(mode="json") for product in input_data.products
            ],
            "listings": [
                listing.model_dump(mode="json") for listing in input_data.listings
            ],
            "evidence": [
                evidence.model_dump(mode="json") for evidence in input_data.evidence
            ],
            "trust_assessments": [
                assessment.model_dump(mode="json")
                for assessment in input_data.trust_assessments
            ],
            "category_analyses": [
                analysis.model_dump(mode="json")
                for analysis in input_data.category_analyses
            ],
            "deduplication_decisions": [
                decision.model_dump(mode="json")
                for decision in input_data.deduplication_decisions
            ],
        },
        sort_keys=True,
    )


def _mock_report_from_model_input(model_input: str) -> VerificationReport:
    payload = json.loads(model_input)
    input_data = VerificationAgentInput.model_validate(
        {
            "run_id": payload["run_id"],
            "brief": payload["brief"],
            "recommendation_bundle": payload["recommendation_bundle"],
            "products": payload["products"],
            "listings": payload["listings"],
            "evidence": payload["evidence"],
            "trust_assessments": payload["trust_assessments"],
            "category_analyses": payload["category_analyses"],
            "deduplication_decisions": payload["deduplication_decisions"],
        }
    )
    return _deterministic_verification_report(input_data)


def _coerce_verification_report_result(
    value: Any,
    input_data: VerificationAgentInput,
) -> VerificationReport:
    report = (
        value
        if isinstance(value, VerificationReport)
        else VerificationReport.model_validate(value)
    )
    _validate_report_relationships(report, input_data)
    return _apply_output_guardrails(report, input_data)


def _deterministic_verification_report(
    input_data: VerificationAgentInput,
) -> VerificationReport:
    return _apply_output_guardrails(
        VerificationReport(
            approved=True,
            recommendation_bundle=input_data.recommendation_bundle,
            notes=("Verification checks completed.",),
        ),
        input_data,
    )


def _apply_output_guardrails(
    report: VerificationReport,
    input_data: VerificationAgentInput,
) -> VerificationReport:
    bundle = report.recommendation_bundle
    issues = _merge_strings(
        (
            *report.blocking_issues,
            *_bundle_guardrail_issues(bundle, input_data),
        )
    )
    if issues:
        return VerificationReport(
            approved=False,
            recommendation_bundle=_guardrail_safe_bundle(bundle, issues),
            blocking_issues=issues,
            notes=_merge_strings(
                (
                    *report.notes,
                    "Result output is blocked until the recommendation is revised.",
                )
            ),
        )
    if not report.approved:
        return report
    return report.model_copy(
        update={
            "approved": True,
            "blocking_issues": (),
            "notes": _merge_strings(
                (*report.notes, "Output guardrails found no blocking issues.")
            ),
        }
    )


def _validate_report_relationships(
    report: VerificationReport,
    input_data: VerificationAgentInput,
) -> None:
    if report.approved and report.blocking_issues:
        raise ValueError("approved verifier output cannot include blocking issues.")
    _validate_bundle_relationships(report.recommendation_bundle, input_data)


def _validate_bundle_relationships(
    bundle: RecommendationBundle,
    input_data: VerificationAgentInput,
) -> None:
    known_product_ids = {product.product_id for product in input_data.products}
    known_listing_ids = {listing.listing_id for listing in input_data.listings}
    known_evidence_ids = _known_evidence_ids(input_data)
    known_source_ids = _known_source_ids(input_data)

    _validate_product_id(bundle.final_product_id, known_product_ids)
    _validate_listing_id(bundle.final_listing_id, known_listing_ids)
    _validate_evidence_ids(bundle.evidence_ids, known_evidence_ids)
    _validate_source_ids(bundle.source_ids, known_source_ids)
    for product_id in bundle.runner_up_product_ids:
        _validate_product_id(product_id, known_product_ids)
    for result in bundle.mode_results:
        _validate_product_id(result.product_id, known_product_ids)
        _validate_listing_id(result.listing_id, known_listing_ids)
        _validate_evidence_ids(result.evidence_ids, known_evidence_ids)
        _validate_source_ids(result.source_ids, known_source_ids)
    for row in bundle.comparison_matrix.rows:
        _validate_product_id(row.product_id, known_product_ids)
        _validate_listing_id(row.listing_id, known_listing_ids)
        _validate_evidence_ids(row.evidence_ids, known_evidence_ids)
    for item in bundle.rejected_items:
        _validate_product_id(item.product_id, known_product_ids)
        _validate_listing_id(item.listing_id, known_listing_ids)
        _validate_evidence_ids(item.evidence_ids, known_evidence_ids)
        _validate_source_ids(item.source_ids, known_source_ids)


def _bundle_guardrail_issues(
    bundle: RecommendationBundle,
    input_data: VerificationAgentInput,
) -> tuple[str, ...]:
    issues: list[str] = []
    issues.extend(_relationship_issues(bundle, input_data))
    issues.extend(_citation_issues(bundle, input_data))
    issues.extend(_budget_issues(bundle, input_data))
    issues.extend(_suspicious_listing_issues(bundle, input_data))
    issues.extend(_duplicate_issues(bundle, input_data))
    issues.extend(_conflict_and_weak_evidence_issues(bundle, input_data))
    issues.extend(_copy_safety_issues(bundle, input_data))
    return _merge_strings(issues)


def _relationship_issues(
    bundle: RecommendationBundle,
    input_data: VerificationAgentInput,
) -> tuple[str, ...]:
    try:
        _validate_bundle_relationships(bundle, input_data)
    except ValueError as exc:
        return (str(exc),)
    return ()


def _citation_issues(
    bundle: RecommendationBundle,
    input_data: VerificationAgentInput,
) -> tuple[str, ...]:
    issues: list[str] = []
    corpus = _evidence_corpus(input_data)
    for label, text, evidence_ids in _cited_text_surfaces(bundle):
        if not text:
            continue
        if not evidence_ids:
            issues.append(f"{label} needs source evidence before it can be shown.")
            continue
        if not _surface_supported_by_evidence(text, evidence_ids, corpus):
            issues.append(f"{label} includes a factual claim not backed by its evidence.")
    return tuple(issues)


def _budget_issues(
    bundle: RecommendationBundle,
    input_data: VerificationAgentInput,
) -> tuple[str, ...]:
    budget = input_data.brief.budget
    if budget is None or budget.mode != BudgetMode.HARD_CAP:
        return ()
    if bundle.no_strong_buy or bundle.final_listing_id is None:
        return ()
    listing = _listings_by_id(input_data).get(bundle.final_listing_id)
    if listing is None or listing.price is None:
        return ()
    if listing.price.currency != budget.amount.currency:
        return ()
    try:
        price = Decimal(listing.price.amount)
        cap = Decimal(budget.amount.amount)
    except InvalidOperation:
        return ()
    if price > cap:
        return (
            "The final pick is above the user's hard budget cap and cannot be approved.",
        )
    return ()


def _suspicious_listing_issues(
    bundle: RecommendationBundle,
    input_data: VerificationAgentInput,
) -> tuple[str, ...]:
    if bundle.no_strong_buy or bundle.final_listing_id is None:
        return ()
    assessment = _trust_by_listing_id(input_data).get(bundle.final_listing_id)
    if assessment is None or assessment.level != ListingTrustLevel.SUSPICIOUS:
        return ()
    if _has_suspicious_listing_caveat(bundle, bundle.final_listing_id):
        return ()
    return (
        "The final listing is marked suspicious but the result does not clearly warn the shopper.",
    )


def _duplicate_issues(
    bundle: RecommendationBundle,
    input_data: VerificationAgentInput,
) -> tuple[str, ...]:
    issues: list[str] = []
    if bundle.final_product_id in set(bundle.runner_up_product_ids):
        issues.append("The final pick is also listed as a runner-up.")

    non_runner_modes: set[RecommendationMode] = set()
    for result in bundle.mode_results:
        if result.mode == RecommendationMode.RUNNER_UP:
            continue
        if result.mode in non_runner_modes:
            issues.append(f"The {result.mode.value} mode appears more than once.")
        non_runner_modes.add(result.mode)

    rejected_targets = {
        (item.product_id, item.listing_id)
        for item in bundle.rejected_items
        if item.severity in (RejectionSeverity.HIGH, RejectionSeverity.BLOCKING)
    }
    if (bundle.final_product_id, bundle.final_listing_id) in rejected_targets:
        issues.append("The final pick is also rejected for a high-severity reason.")

    if any(
        decision.outcome == DeduplicationOutcome.UNCERTAIN
        for decision in input_data.deduplication_decisions
    ) and not _texts_match_any_pattern(_bundle_warning_text(bundle), (r"\bduplicate",)):
        issues.append("Uncertain duplicate evidence needs a visible duplicate caveat.")
    return tuple(issues)


def _conflict_and_weak_evidence_issues(
    bundle: RecommendationBundle,
    input_data: VerificationAgentInput,
) -> tuple[str, ...]:
    if bundle.no_strong_buy or bundle.final_product_id is None:
        return ()
    if not _has_final_candidate_conflict_or_weak_evidence(bundle, input_data):
        return ()
    if _has_conflict_or_weak_evidence_caveat(bundle):
        return ()
    return (
        "Material conflict or weak evidence affects the final pick but is not disclosed.",
    )


def _copy_safety_issues(
    bundle: RecommendationBundle,
    input_data: VerificationAgentInput,
) -> tuple[str, ...]:
    del input_data
    issues: list[str] = []
    text = _all_user_facing_text(bundle)
    if _texts_match_any_pattern(text, _INTERNAL_LANGUAGE_PATTERNS):
        issues.append("Result copy exposes internal process details to the shopper.")
    if _texts_match_any_pattern(text, _UNSAFE_PURCHASE_PATTERNS):
        issues.append("Result copy includes unsafe or off-scope purchase guidance.")
    if _texts_match_any_pattern(text, _OVERCONFIDENT_PATTERNS):
        issues.append("Result copy is overconfident for source-backed shopping advice.")
    return tuple(issues)


def _guardrail_safe_bundle(
    bundle: RecommendationBundle,
    issues: tuple[str, ...],
) -> RecommendationBundle:
    guardrail_warning = "Result blocked for review: " + " ".join(issues)
    return bundle.model_copy(
        update={
            "warnings": _merge_strings((*bundle.warnings, guardrail_warning)),
        }
    )


def _failure_report(input_data: VerificationAgentInput, issue: str) -> VerificationReport:
    return VerificationReport(
        approved=False,
        recommendation_bundle=_guardrail_safe_bundle(
            input_data.recommendation_bundle,
            (issue,),
        ),
        blocking_issues=(issue,),
        notes=("Result output is blocked until verification can complete.",),
    )


def _cited_text_surfaces(
    bundle: RecommendationBundle,
) -> tuple[tuple[str, str | None, tuple[SourceId, ...]], ...]:
    surfaces: list[tuple[str, str | None, tuple[SourceId, ...]]] = [
        ("final rationale", bundle.final_rationale, bundle.evidence_ids),
        ("no-strong-buy reason", bundle.no_strong_buy_reason, bundle.evidence_ids),
    ]
    for result in bundle.mode_results:
        surfaces.append(
            (
                f"{result.mode.value} rationale",
                result.rationale,
                result.evidence_ids,
            )
        )
    for index, row in enumerate(bundle.comparison_matrix.rows, start=1):
        surfaces.append((f"comparison row {index}", row.summary, row.evidence_ids))
    for index, item in enumerate(bundle.rejected_items, start=1):
        surfaces.append((f"rejected item {index}", item.reason, item.evidence_ids))
    for index, warning in enumerate(bundle.warnings, start=1):
        surfaces.append((f"warning {index}", warning, bundle.evidence_ids))
    return tuple(surfaces)


def _surface_supported_by_evidence(
    text: str,
    evidence_ids: Sequence[SourceId],
    corpus: dict[SourceId, str],
) -> bool:
    supported_text = " ".join(corpus.get(evidence_id, "") for evidence_id in evidence_ids)
    if not supported_text.strip():
        return False

    normalized_text = _normalize_text(text)
    normalized_supported = _normalize_text(supported_text)
    missing_facts = [
        match.group(0)
        for pattern in _FACTUAL_SPEC_PATTERNS
        for match in re.finditer(pattern, normalized_text)
        if match.group(0) not in normalized_supported
    ]
    if missing_facts:
        return False

    text_terms = _significant_terms(normalized_text)
    if not text_terms:
        return True
    supported_terms = _significant_terms(normalized_supported)
    if not supported_terms:
        return False
    overlap = text_terms & supported_terms
    return bool(overlap) or len(text_terms) <= 2


def _significant_terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9+-]{3,}", text.casefold())
        if token not in _STOPWORDS
    }


def _evidence_corpus(input_data: VerificationAgentInput) -> dict[SourceId, str]:
    corpus: dict[SourceId, list[str]] = {}
    for evidence in input_data.evidence:
        corpus.setdefault(evidence.evidence_id, []).append(evidence.claim)
    for analysis in input_data.category_analyses:
        texts = (
            analysis.fit_summary,
            *analysis.strengths,
            *analysis.weaknesses,
            *analysis.warnings,
        )
        for evidence_id in analysis.evidence_ids:
            corpus.setdefault(evidence_id, []).extend(texts)
    for assessment in input_data.trust_assessments:
        texts = (
            assessment.summary,
            *assessment.red_flags,
            *assessment.positive_signals,
            *(signal.summary for signal in assessment.trust_signals),
        )
        for evidence_id in assessment.evidence_ids:
            corpus.setdefault(evidence_id, []).extend(texts)
    for decision in input_data.deduplication_decisions:
        for evidence_id in decision.evidence_ids:
            corpus.setdefault(evidence_id, []).append(decision.rationale)
    return {
        evidence_id: " ".join(texts)
        for evidence_id, texts in corpus.items()
        if any(texts)
    }


def _has_final_candidate_conflict_or_weak_evidence(
    bundle: RecommendationBundle,
    input_data: VerificationAgentInput,
) -> bool:
    evidence_ids = set(_final_candidate_evidence_ids(bundle))
    if not evidence_ids:
        return False
    for evidence in input_data.evidence:
        if evidence.evidence_id not in evidence_ids:
            continue
        if evidence.evidence_type == EvidenceType.WARNING:
            return True
        if evidence.source_quality.level in (
            SourceQualityLevel.WEAK,
            SourceQualityLevel.MIXED,
        ):
            return True
        if _texts_match_any_pattern(
            evidence.claim,
            (r"\bconflict", r"\bcontradict", r"\bmixed\b", r"\bwarning\b"),
        ):
            return True
    for analysis in input_data.category_analyses:
        if analysis.product_id != bundle.final_product_id:
            continue
        if analysis.warnings or analysis.confidence.score < 0.45:
            return True
    return False


def _final_candidate_evidence_ids(
    bundle: RecommendationBundle,
) -> tuple[SourceId, ...]:
    evidence_ids: list[SourceId] = [*bundle.evidence_ids]
    for result in bundle.mode_results:
        if result.product_id == bundle.final_product_id:
            evidence_ids.extend(result.evidence_ids)
    for row in bundle.comparison_matrix.rows:
        if row.product_id == bundle.final_product_id:
            evidence_ids.extend(row.evidence_ids)
    return _dedupe_ids(evidence_ids)


def _has_suspicious_listing_caveat(
    bundle: RecommendationBundle,
    listing_id: ListingId,
) -> bool:
    for warning in bundle.warnings:
        if _texts_match_any_pattern(warning, _SUSPICIOUS_CAVEAT_PATTERNS):
            return True
    for item in bundle.rejected_items:
        if item.listing_id == listing_id and _texts_match_any_pattern(
            item.reason,
            _SUSPICIOUS_CAVEAT_PATTERNS,
        ):
            return True
    return _texts_match_any_pattern(
        _all_user_facing_text(bundle),
        _SUSPICIOUS_CAVEAT_PATTERNS,
    )


def _has_conflict_or_weak_evidence_caveat(bundle: RecommendationBundle) -> bool:
    return _texts_match_any_pattern(
        _all_user_facing_text(bundle),
        _CONFLICT_CAVEAT_PATTERNS,
    )


def _all_user_facing_text(bundle: RecommendationBundle) -> str:
    chunks: list[str] = []
    for text in (bundle.final_rationale, bundle.no_strong_buy_reason):
        if text:
            chunks.append(text)
    chunks.extend(result.title for result in bundle.mode_results)
    chunks.extend(result.rationale for result in bundle.mode_results)
    chunks.extend(row.summary or "" for row in bundle.comparison_matrix.rows)
    chunks.extend(item.reason for item in bundle.rejected_items)
    chunks.extend(bundle.warnings)
    return "\n".join(chunk for chunk in chunks if chunk)


def _bundle_warning_text(bundle: RecommendationBundle) -> str:
    return "\n".join(bundle.warnings)


def _texts_match_any_pattern(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _known_evidence_ids(input_data: VerificationAgentInput) -> set[SourceId]:
    ids = {evidence.evidence_id for evidence in input_data.evidence}
    for analysis in input_data.category_analyses:
        ids.update(analysis.evidence_ids)
    for assessment in input_data.trust_assessments:
        ids.update(assessment.evidence_ids)
    for decision in input_data.deduplication_decisions:
        ids.update(decision.evidence_ids)
    return ids


def _known_source_ids(input_data: VerificationAgentInput) -> set[SourceId]:
    ids = {evidence.source_id for evidence in input_data.evidence}
    for product in input_data.products:
        ids.update(product.source_ids)
    for listing in input_data.listings:
        ids.update(listing.source_ids)
        ids.update(listing.seller.source_ids)
    for analysis in input_data.category_analyses:
        ids.update(analysis.source_ids)
    for assessment in input_data.trust_assessments:
        ids.update(assessment.source_ids)
    for decision in input_data.deduplication_decisions:
        ids.update(decision.source_ids)
    return ids


def _validate_product_id(
    product_id: ProductId | None,
    known_product_ids: set[ProductId],
) -> None:
    if product_id is not None and known_product_ids and product_id not in known_product_ids:
        raise ValueError("recommendation output used an unknown product ID.")


def _validate_listing_id(
    listing_id: ListingId | None,
    known_listing_ids: set[ListingId],
) -> None:
    if listing_id is not None and known_listing_ids and listing_id not in known_listing_ids:
        raise ValueError("recommendation output used an unknown listing ID.")


def _validate_evidence_ids(
    evidence_ids: tuple[SourceId, ...],
    known_evidence_ids: set[SourceId],
) -> None:
    if not known_evidence_ids:
        return
    if set(evidence_ids) - known_evidence_ids:
        raise ValueError("recommendation output used unknown evidence IDs.")


def _validate_source_ids(
    source_ids: tuple[SourceId, ...],
    known_source_ids: set[SourceId],
) -> None:
    if not known_source_ids:
        return
    if set(source_ids) - known_source_ids:
        raise ValueError("recommendation output used unknown source IDs.")


def _trust_by_listing_id(
    input_data: VerificationAgentInput,
) -> dict[ListingId, ListingTrustAssessment]:
    return {
        assessment.listing_id: assessment
        for assessment in input_data.trust_assessments
    }


def _listings_by_id(input_data: VerificationAgentInput) -> dict[ListingId, Any]:
    return {listing.listing_id: listing for listing in input_data.listings}


def _normalize_text(text: str) -> str:
    return " ".join(text.casefold().replace("_", " ").split())


def _dedupe_ids(values: Iterable[SourceId]) -> tuple[SourceId, ...]:
    seen: set[SourceId] = set()
    deduped: list[SourceId] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


def _merge_strings(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    merged: list[str] = []
    for value in values:
        normalized = " ".join(value.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)
    return tuple(merged)
