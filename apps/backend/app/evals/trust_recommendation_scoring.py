"""Structural assertions for advisory shopping decisions and optional editorial assistance."""

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from app.evals.schemas import EvalMetadata
from app.evals.trust_recommendation import (
    STAGES,
    TrustRecommendationExpectation,
    TrustRecommendationInput,
    TrustRecommendationOutput,
    TrustRecommendationResult,
)
from app.schemas.analysis import RecommendationBundle


def _check(passed: bool, requirement: str, actual: object) -> EvaluationReason:
    return EvaluationReason(value=passed, reason=f"{requirement} Actual: {actual!r}")


def _values(value: Any, path: list[str]) -> list[Any]:
    if not path:
        return [value]
    head, *rest = path
    if head == "*" and isinstance(value, list):
        return [v for child in value for v in _values(child, rest)]
    if isinstance(value, dict) and head in value:
        return _values(value[head], rest)
    if isinstance(value, list) and head.isdecimal() and int(head) < len(value):
        return _values(value[int(head)], rest)
    raise KeyError("Missing field or wrong shape.")


def shopper_text(bundle: RecommendationBundle) -> str:
    # Internal author/handoff/verification metadata are not displayed as copy.
    return " ".join(
        v
        for v in (
            bundle.final_rationale,
            bundle.no_strong_buy_reason,
            *bundle.warnings,
            *(m.title for m in bundle.mode_results),
            *(m.rationale for m in bundle.mode_results),
            *(m.confidence.rationale for m in bundle.mode_results),
            *(r.summary for r in bundle.comparison_matrix.rows),
            *(r.reason for r in bundle.rejected_items),
        )
        if v
    )


def _bundle_checks(
    inputs: TrustRecommendationInput, bundle: RecommendationBundle
) -> dict[str, EvaluationReason]:
    fixture = inputs.recommendation or inputs.verification
    assert fixture is not None
    request = fixture.request
    products = {item.product_id for item in request.products}
    listings = {item.listing_id: item for item in request.listings}
    evidence = {item.evidence_id: item for item in request.evidence}
    sources = {item.source_id for item in request.evidence}
    sources.update(
        value
        for item in (*request.products, *request.listings)
        for value in item.source_ids
    )
    sources.update(item.source_id for item in getattr(request, "source_results", ()))
    sources.update(item.source_id for item in getattr(request, "source_snapshots", ()))
    results = {}
    selected = [("final", bundle.final_product_id, bundle.final_listing_id)]
    selected.extend(
        (f"mode.{index}", item.product_id, item.listing_id)
        for index, item in enumerate(bundle.mode_results)
    )
    selected.extend(
        (f"row.{index}", item.product_id, item.listing_id)
        for index, item in enumerate(bundle.comparison_matrix.rows)
    )
    for label, product_id, listing_id in selected:
        results[f"recommendation.{label}.identity"] = _check(
            (product_id is None or product_id in products)
            and (
                listing_id is None
                or listing_id in listings
                and listings[listing_id].product_id == product_id
            ),
            "Use known product IDs and paired listing IDs when a listing is supplied.",
            (product_id, listing_id),
        )
    results["recommendation.runner_ups"] = _check(
        set(bundle.runner_up_product_ids).issubset(products),
        "Alternatives use known product identities.",
        bundle.runner_up_product_ids,
    )
    surfaces = [("bundle", bundle.evidence_ids, bundle.source_ids)]
    surfaces.extend(
        (f"mode.{index}", item.evidence_ids, item.source_ids)
        for index, item in enumerate(bundle.mode_results)
    )
    surfaces.extend(
        (f"rejection.{index}", item.evidence_ids, item.source_ids)
        for index, item in enumerate(bundle.rejected_items)
    )
    surfaces.extend(
        (f"row.{index}", item.evidence_ids, ())
        for index, item in enumerate(bundle.comparison_matrix.rows)
    )
    for label, associations, source_ids in surfaces:
        results[f"evidence.{label}.ids"] = _check(
            set(associations).issubset(evidence),
            "Optional evidence associations identify supplied records.",
            associations,
        )
        results[f"evidence.{label}.sources"] = _check(
            set(source_ids).issubset(sources),
            "Optional source links identify supplied sources; a quotation is not required.",
            source_ids,
        )
    return results


def score_trust_recommendation(
    inputs: TrustRecommendationInput,
    output: object,
    expected: TrustRecommendationExpectation,
) -> dict[str, EvaluationReason]:
    try:
        actual = TrustRecommendationOutput.model_validate(output)
    except ValidationError as error:
        return {
            "schema." + ".".join(map(str, v["loc"])): _check(
                False, v["msg"], v.get("input")
            )
            for v in error.errors()
        }
    has_technical_failure = actual.technical_failure is not None
    expected_stages = tuple(
        inputs.stage == stage and not has_technical_failure for stage in STAGES
    )
    results = {
        "schema.stage_output": _check(
            tuple(getattr(actual, stage) is not None for stage in STAGES)
            == expected_stages
            and (
                not has_technical_failure
                or inputs.stage == "guardrail"
                and actual.technical_failure.retryable
            )
            and (inputs.stage == "trust" or not actual.price_findings),
            "Return only the selected stage's output.",
            actual,
        )
    }
    data = actual.model_dump(mode="json")
    for i, rule in enumerate(expected.fields):
        try:
            values = _values(data, rule.field.split("."))
            value = values if "*" in rule.field.split(".") else values[0]
            if rule.operator == "equals":
                passed = value == rule.value
            elif rule.operator == "set_equals":
                passed = (
                    isinstance(value, list)
                    and len(value) == len(rule.value)
                    and set(value) == set(rule.value)
                )
            elif rule.operator == "count":
                passed = isinstance(value, (list, dict)) and len(value) == rule.value
            else:
                text = (
                    value
                    if isinstance(value, str)
                    else " ".join(value)
                    if isinstance(value, list)
                    and all(isinstance(v, str) for v in value)
                    else ""
                )
                passed = str(rule.value).casefold() in text.casefold()
        except (KeyError, TypeError):
            value, passed = "Missing field or wrong shape.", False
        results[f"field.{rule.field}[{i}]"] = _check(
            passed,
            f"{rule.requirement} Expected {rule.operator}: {rule.value!r}.",
            value,
        )
    if actual.trust and inputs.trust:
        fixture = inputs.trust
        listing = fixture.request.listing
        sources = {s for v in (listing, *fixture.price_peers) for s in v.source_ids}
        sources.update(e.source_id for e in fixture.request.evidence)
        citations = sources | {e.evidence_id for e in fixture.request.evidence}
        results["trust.listing_identity"] = _check(
            actual.trust.listing_id == listing.listing_id,
            "Assess the exact seller offer, not a different listing of this product.",
            actual.trust.listing_id,
        )
        for i, item in enumerate((actual.trust, *actual.trust.trust_signals)):
            results[f"trust.citations.{i}"] = _check(
                set(item.evidence_ids).issubset(citations)
                and set(item.source_ids).issubset(sources),
                "Trust signals may cite only fixture listing/peer evidence.",
                item.evidence_ids,
            )
    if actual.recommendation and inputs.recommendation:
        results.update(_bundle_checks(inputs, actual.recommendation))
    if actual.verification and inputs.verification:
        report = actual.verification
        original = inputs.verification.request.recommendation_bundle
        results["verification.nonblocking"] = _check(
            report.approved and not report.blocking_issues,
            "Optional editorial assistance does not block model advice.",
            report.blocking_issues,
        )
        results["verification.owner_choices"] = _check(
            (
                report.recommendation_bundle.final_product_id,
                report.recommendation_bundle.final_listing_id,
                report.recommendation_bundle.no_strong_buy,
            )
            == (
                original.final_product_id,
                original.final_listing_id,
                original.no_strong_buy,
            ),
            "Optional editorial assistance preserves the owning model's purchase judgment.",
            report.recommendation_bundle.final_product_id,
        )
    return results


@dataclass
class TrustRecommendationEvaluator(
    Evaluator[TrustRecommendationInput, TrustRecommendationResult, EvalMetadata]
):
    def evaluate(
        self,
        ctx: EvaluatorContext[
            TrustRecommendationInput, TrustRecommendationResult, EvalMetadata
        ],
    ) -> dict[str, EvaluationReason]:
        if not isinstance(ctx.expected_output, TrustRecommendationExpectation):
            return {
                "schema.expected_output": _check(
                    False, "Independent expectations are required.", ctx.expected_output
                )
            }
        return score_trust_recommendation(ctx.inputs, ctx.output, ctx.expected_output)
