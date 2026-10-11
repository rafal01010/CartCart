"""Cheap Task 99 integrity/scoring/adapter checks; no scored Dataset execution."""

import copy
import json
from collections import Counter
from types import SimpleNamespace

import pytest
from agents import Runner
from pydantic_evals import Dataset

from app.evals.trust_recommendation import (
    CORPUS_PATH,
    TrustRecommendationExpectation,
    TrustRecommendationOutput,
    offline_trust_recommendation_task,
    trust_recommendation_cases,
)
from app.evals.trust_recommendation_scoring import (
    TrustRecommendationEvaluator,
    score_trust_recommendation,
)
from app.schemas.analysis import RecommendationBundle
from app.tools import run_evals


def named(name):
    return next(c for c in trust_recommendation_cases() if c.name == name)


def failures(case, output):
    return {
        k: v
        for k, v in score_trust_recommendation(
            case.inputs, output, case.expected_output
        ).items()
        if not v.value
    }


def independent_pick():
    case = named("recommendation/best-fit-over-cheapest")
    return TrustRecommendationOutput(
        recommendation=RecommendationBundle.model_validate(
            case.inputs.recommendation.model_output
        ),
        runtime_status="model_comparison_decision_completed",
        model_calls=1,
    )


def test_corpus_is_documented_and_load_only(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("No Dataset or SDK execution during corpus checks.")

    monkeypatch.setattr(Dataset, "evaluate_sync", forbidden)
    monkeypatch.setattr(Dataset, "evaluate", forbidden)
    monkeypatch.setattr(Runner, "run", forbidden)
    cases = trust_recommendation_cases()
    assert len(cases) == 42
    assert Counter(c.inputs.stage for c in cases) == {
        "guardrail": 9,
        "trust": 6,
        "recommendation": 9,
        "verification": 18,
    }
    assert all(case.expected_output.fields for case in cases)
    assert any(
        case.name == "trust/model-can-improve-advisory-price-risk" for case in cases
    )


def test_fresh_loads_and_independent_expectations():
    a = named("recommendation/best-fit-over-cheapest")
    b = named(a.name)
    a.inputs.recommendation.request.category_analyses[
        0
    ].fit_summary = "Changed fixture."
    assert (
        b.inputs.recommendation.request.category_analyses[0].fit_summary
        != "Changed fixture."
    )
    before = b.expected_output.model_dump()
    b.inputs.recommendation.request.listings[0].price.amount = 999999
    assert b.expected_output.model_dump() == before
    assert "expected_output" not in b.inputs.model_dump_json()


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "nested_version",
        "duplicate_name",
        "wrong_stage",
        "wrong_root",
        "empty_rules",
        "metadata_only",
        "missing_id",
        "missing_time",
        "duplicate_product",
        "duplicate_evidence",
        "dangling_listing",
        "wrong_membership",
        "dangling_analysis",
        "dangling_trust",
        "wrong_evidence_target",
        "trust_peer_identity",
        "trust_context_citation",
        "count_operand",
        "set_operand",
        "duplicate_rule",
        "response_and_failure",
    ],
)
def test_bad_corpus_fails_closed(tmp_path, mutation):
    raw = json.loads(CORPUS_PATH.read_text())
    guard = raw["cases"][0]
    trust = next(c for c in raw["cases"] if c["inputs"]["stage"] == "trust")
    rec = next(c for c in raw["cases"] if c["inputs"]["stage"] == "recommendation")
    request = rec["inputs"]["recommendation"]["request"]
    rule = rec["expected_output"]["fields"][0]
    unknown = "00000000-0000-4000-8000-000000099999"
    if mutation == "version":
        raw["schema_version"] = 2
    elif mutation == "nested_version":
        request["brief"]["schema_version"] = 2
    elif mutation == "duplicate_name":
        raw["cases"][1]["name"] = guard["name"]
    elif mutation == "wrong_stage":
        guard["inputs"]["stage"] = "trust"
    elif mutation == "wrong_root":
        rule["field"] = "trust.level"
    elif mutation == "empty_rules":
        rec["expected_output"]["fields"] = []
    elif mutation == "metadata_only":
        rec["expected_output"]["fields"] = [
            {
                "field": "model_calls",
                "value": 1,
                "requirement": "Metadata alone cannot pass.",
            }
        ]
    elif mutation == "missing_id":
        del request["products"][0]["product_id"]
    elif mutation == "missing_time":
        del request["listings"][0]["captured_at"]
    elif mutation == "duplicate_product":
        request["products"].append(copy.deepcopy(request["products"][0]))
    elif mutation == "duplicate_evidence":
        request["evidence"].append(copy.deepcopy(request["evidence"][0]))
    elif mutation == "dangling_listing":
        request["listings"][0]["product_id"] = unknown
    elif mutation == "wrong_membership":
        request["products"][0]["listing_ids"] = []
    elif mutation == "dangling_analysis":
        request["category_analyses"][0]["evidence_ids"] = [unknown]
    elif mutation == "dangling_trust":
        request["trust_assessments"][0]["listing_id"] = unknown
    elif mutation == "wrong_evidence_target":
        request["evidence"][0]["target"]["product_id"] = unknown
    elif mutation == "trust_peer_identity":
        trust["inputs"]["trust"]["price_peers"][0]["product_id"] = unknown
    elif mutation == "trust_context_citation":
        trust["inputs"]["trust"]["context"]["source_ids"] = [unknown]
    elif mutation == "count_operand":
        rule.update(operator="count", value=True)
    elif mutation == "set_operand":
        rule.update(operator="set_equals", value=[{}])
    elif mutation == "duplicate_rule":
        rec["expected_output"]["fields"].append(copy.deepcopy(rule))
    elif mutation == "response_and_failure":
        guard["inputs"]["guardrail"].update(
            failure="timeout", model_output={"decision": "allowed"}
        )
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        trust_recommendation_cases(path)


def test_schema_and_missing_paths_fail_explicitly():
    case = named("recommendation/best-fit-over-cheapest")
    assert "schema.model_calls" in failures(case, {})
    expected = TrustRecommendationExpectation(
        fields=[
            dict(
                field="recommendation.missing",
                value=True,
                requirement="Missing paths cannot silently pass.",
            )
        ]
    )
    result = score_trust_recommendation(case.inputs, independent_pick(), expected)
    assert not result["field.recommendation.missing[0]"].value
    wrong = independent_pick().model_dump()
    wrong["recommendation"] = None
    assert not score_trust_recommendation(case.inputs, wrong, case.expected_output)[
        "schema.stage_output"
    ].value


def test_evaluator_requires_independent_expectations():
    case = named("recommendation/best-fit-over-cheapest")
    ctx = SimpleNamespace(
        inputs=case.inputs,
        output=independent_pick(),
        expected_output=case.expected_output,
    )
    evaluator = TrustRecommendationEvaluator()
    assert all(r.value for r in evaluator.evaluate(ctx).values())
    ctx.expected_output = None
    assert not evaluator.evaluate(ctx)["schema.expected_output"].value


@pytest.mark.parametrize("passed,expected_exit", [(True, 0), (False, 1)])
def test_cli_registers_regular_gate_suite_without_executing(
    monkeypatch, tmp_path, capsys, passed, expected_exit
):
    seen = []

    def fake_run(dataset, task, output_dir):
        seen.append((dataset.name, len(dataset.cases), callable(task), output_dir))
        return output_dir / "stub-report.json", passed

    monkeypatch.setattr(run_evals, "run_local_evaluation", fake_run)
    assert (
        run_evals.main(
            ["--suite", "trust-recommendation", "--output-dir", str(tmp_path)]
        )
        == expected_exit
    )
    assert seen == [("cartcart-trust-recommendation", 42, True, tmp_path.resolve())]
    assert not (tmp_path / "stub-report.json").exists()
    assert "trust/guardrail/recommendation" in capsys.readouterr().out


def test_optional_modes_sources_budget_and_copy_are_model_judgments():
    case = named("recommendation/best-fit-over-cheapest")
    output = independent_pick()
    bundle = output.recommendation.model_copy(
        update={
            "final_rationale": "This model has an OLED panel. Confirm warranty and avoid counterfeit listings."
        }
    )
    results = score_trust_recommendation(
        case.inputs,
        output.model_copy(update={"recommendation": bundle}),
        case.expected_output,
    )
    assert all(result.value for result in results.values())
    assert not any(
        key.startswith("budget.")
        or key.startswith("wording.")
        or key.endswith("factual_claims")
        for key in results
    )


def test_optional_associations_still_identify_available_records():
    case = named("recommendation/best-fit-over-cheapest")
    output = independent_pick()
    from app.schemas.ids import new_id

    output.recommendation.evidence_ids = (new_id(),)
    broken = failures(case, output)
    assert "evidence.bundle.ids" in broken


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["guardrail/timeout", "guardrail/invalid-response"])
async def test_sdk_classifier_failure_is_retryable_without_a_blocked_judgment(name):
    case = named(name)
    output = await offline_trust_recommendation_task()(case.inputs)
    assert output.guardrail is None
    assert output.technical_failure.code == "shopping_guardrail_unavailable"
    assert output.technical_failure.retryable is True
    assert output.model_calls == 1
    assert not failures(case, output)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "guardrail/off-topic",
        "guardrail/unsafe-firearm",
        "guardrail/illegal-purchase",
        "guardrail/unsafe-later-answer",
    ],
)
async def test_refusal_fixtures_use_explicit_sdk_classifier_outputs(name):
    case = named(name)
    output = await offline_trust_recommendation_task()(case.inputs)
    assert output.guardrail == case.inputs.guardrail.model_output
    assert output.guardrail.decision == "blocked"
    assert output.model_calls == 1
    assert output.technical_failure is None
    assert not failures(case, output)
