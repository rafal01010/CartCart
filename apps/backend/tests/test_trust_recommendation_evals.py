"""Cheap Task 99 integrity/scoring/adapter checks; no scored Dataset execution."""

import copy
import json
from collections import Counter
from types import SimpleNamespace

import httpx
import pytest
from agents import Runner
from pydantic_evals import Dataset

from app.evals.trust_recommendation import (
    CORPUS_PATH,
    TrustRecommendationExpectation,
    TrustRecommendationOutput,
    offline_trust_recommendation_task,
    trust_recommendation_cases,
    trust_recommendation_dataset,
)
from app.evals.trust_recommendation_scoring import (
    TrustRecommendationEvaluator,
    score_trust_recommendation,
)
from app.schemas.analysis import RecommendationBundle, RecommendationMode
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
    # An authored draft, independent of the evaluated comparison implementation.
    case = named("verification/supported-claims")
    return TrustRecommendationOutput(
        recommendation=case.inputs.verification.request.recommendation_bundle.model_copy(
            deep=True
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
    assert len(cases) == 35
    assert Counter(c.inputs.stage for c in cases) == {
        "guardrail": 9,
        "trust": 6,
        "recommendation": 9,
        "verification": 11,
    }
    dataset = trust_recommendation_dataset()
    assert dataset.name == "cartcart-trust-recommendation"
    assert len(dataset.cases) == len(cases)
    assert isinstance(dataset.evaluators[0], TrustRecommendationEvaluator)
    docs = (CORPUS_PATH.parents[5] / "docs" / "EVALUATION.md").read_text()
    for case in cases:
        assert f"`{case.name}`" in docs
    assert "regular quality gate" in docs


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


def test_independently_authored_pick_passes():
    assert not failures(
        named("recommendation/best-fit-over-cheapest"), independent_pick()
    )


@pytest.mark.parametrize(
    "mutation,key",
    [
        ("cheapest", "field.recommendation.final_product_id"),
        ("wrong_listing", "recommendation.final.identity"),
        ("invented_evidence", "evidence.bundle.ids"),
        ("wrong_source", "evidence.bundle.source_binding"),
        ("wrong_candidate_citation", "evidence.mode.0.target_binding"),
        ("unsupported_spec", "evidence.final.factual_claims"),
        ("internal_copy", "wording.internal_language"),
        ("overconfidence", "wording.overconfidence"),
        ("unsafe_copy", "wording.unsafe_guidance"),
        ("duplicate_mode", "recommendation.unique_modes"),
        ("duplicate_runner_up", "recommendation.runner_ups"),
        ("confidence_copy", "wording.internal_language"),
    ],
)
def test_pick_regressions_fail_with_specific_reasons(mutation, key):
    case = named("recommendation/best-fit-over-cheapest")
    output = independent_pick()
    bundle = output.recommendation
    req = case.inputs.recommendation.request
    if mutation == "cheapest":
        bundle.final_product_id = req.products[1].product_id
        bundle.final_listing_id = req.listings[1].listing_id
    elif mutation == "wrong_listing":
        bundle.final_listing_id = req.listings[1].listing_id
    elif mutation == "invented_evidence":
        bundle.evidence_ids = (req.run_id,)
    elif mutation == "wrong_source":
        bundle.source_ids = ()
    elif mutation == "wrong_candidate_citation":
        bundle.mode_results[0].evidence_ids = (req.evidence[1].evidence_id,)
        bundle.mode_results[0].source_ids = (req.evidence[1].source_id,)
    elif mutation == "unsupported_spec":
        bundle.final_rationale = "Comfortable office monitor with 240Hz and 4K."
    elif mutation == "internal_copy":
        bundle.final_rationale = "The agent checked the provider schema."
    elif mutation == "overconfidence":
        bundle.final_rationale = "Guaranteed perfect with no risk."
    elif mutation == "unsafe_copy":
        bundle.final_rationale = "Bypass safety for an unregistered firearm."
    elif mutation == "duplicate_mode":
        bundle.mode_results += (bundle.mode_results[0].model_copy(deep=True),)
    elif mutation == "duplicate_runner_up":
        bundle.runner_up_product_ids = (
            req.products[1].product_id,
            req.products[1].product_id,
        )
    elif mutation == "confidence_copy":
        bundle.mode_results[
            0
        ].confidence.rationale = "The provider tool call approved it."
    broken = failures(case, output)
    assert any(k.startswith(key) for k in broken), broken
    assert all("Actual:" in v.reason for v in broken.values())


def test_hard_budget_applies_to_every_buy_surface():
    broken = failures(named("recommendation/hard-cap"), independent_pick())
    assert "budget.final.hard_cap" in broken
    assert "budget.modes.best_overall.0.hard_cap" in broken


def test_unknown_currency_cannot_be_within_budget():
    case = named("recommendation/best-fit-over-cheapest")
    case.inputs.recommendation.request.listings[0].price.currency = "USD"
    output = independent_pick()
    mode = output.recommendation.mode_results[0].model_copy(
        update={"mode": RecommendationMode.WITHIN_BUDGET}
    )
    output.recommendation.mode_results = (mode,)
    assert "budget.modes.within_budget.0.label" in failures(case, output)


def test_suspicious_listing_fails_even_when_product_fit_is_high():
    case = named("recommendation/best-fit-over-cheapest")
    case.inputs.recommendation.request.trust_assessments[0].level = "suspicious"
    broken = failures(case, independent_pick())
    assert "recommendation.final.trust" in broken
    assert any(
        k.startswith("trust.") and k.endswith("visible_rejection") for k in broken
    )


def test_no_strong_buy_requires_next_step_and_cleared_modes():
    case = named("recommendation/weak-evidence")
    bundle = RecommendationBundle(
        no_strong_buy=True,
        no_strong_buy_reason="Evidence is insufficient.",
        comparison_matrix={},
    )
    output = TrustRecommendationOutput(
        recommendation=bundle, runtime_status="completed", model_calls=1
    )
    assert "recommendation.no_strong_buy" in failures(case, output)
    bundle.no_strong_buy_reason = (
        "Evidence is insufficient. Next, look for clearer evidence."
    )
    bundle.mode_results = independent_pick().recommendation.mode_results
    assert "recommendation.no_strong_buy" in failures(case, output)


def test_hidden_review_conflict_is_independent_failure():
    broken = failures(named("recommendation/conflict-disclosure"), independent_pick())
    assert "evidence.material_conflict_disclosure" in broken
    assert any(k.startswith("field.recommendation.warnings") for k in broken)


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


@pytest.mark.parametrize(
    "name,calls",
    [
        ("guardrail/unsafe-firearm", 0),
        ("guardrail/semantic-off-topic", 1),
        ("guardrail/timeout", 1),
        ("trust/implausibly-cheap-offer", 1),
        ("trust/upgrade-cannot-erase-price-risk", 1),
        ("recommendation/preferred-stretch", 1),
        ("recommendation/manual-only-no-buy", 1),
        ("verification/supported-claims", 1),
        ("verification/conflict-hidden", 1),
        ("verification/timeout-blocks-display", 1),
    ],
)
@pytest.mark.asyncio
async def test_representative_adapter_branches_are_offline(monkeypatch, name, calls):
    attempts = []

    async def forbidden(*a, **kw):
        attempts.append(True)
        raise AssertionError("SDK/network runs are forbidden.")

    monkeypatch.setattr(Runner, "run", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden)
    monkeypatch.setenv("CARTCART_LIVE_AGENTS_ENABLED", "true")
    monkeypatch.setenv("CARTCART_OPENAI_AGENT_TRACING_ENABLED", "true")
    task = offline_trust_recommendation_task()
    assert task.settings.live_agents_enabled is False
    assert task.settings.openai_agent_tracing_enabled is False
    assert task.settings.openai_api_key is None
    case = named(name)
    before = case.inputs.model_dump()
    output = await task(case.inputs)
    assert case.inputs.model_dump() == before
    assert not attempts
    assert output.model_calls == calls
    broken = failures(case, output)
    assert not broken, broken


@pytest.mark.asyncio
async def test_conflicting_reviews_adapter_keeps_strict_criteria():
    case = named("recommendation/conflict-disclosure")
    output = await offline_trust_recommendation_task()(case.inputs)
    broken = failures(case, output)
    assert not broken, broken


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
    assert seen == [("cartcart-trust-recommendation", 35, True, tmp_path.resolve())]
    assert not (tmp_path / "stub-report.json").exists()
    assert "trust/guardrail/recommendation" in capsys.readouterr().out


def test_specifications_cannot_transfer_from_a_competing_product():
    case = named("recommendation/best-fit-over-cheapest")
    case.inputs.recommendation.request.evidence[
        1
    ].claim = "The other monitor has 240Hz."
    output = independent_pick()
    output.recommendation.evidence_ids = tuple(
        e.evidence_id for e in case.inputs.recommendation.request.evidence
    )
    output.recommendation.source_ids = tuple(
        e.source_id for e in case.inputs.recommendation.request.evidence
    )
    output.recommendation.final_rationale = "Comfortable office monitor with 240Hz."
    assert "evidence.final.factual_claims" in failures(case, output)


def test_preferred_stretch_amount_requirement_remains_independent():
    case = named("recommendation/preferred-stretch")
    output = independent_pick()
    output.recommendation.mode_results[
        0
    ].rationale = "Choose this only if your budget is flexible."
    assert any(
        k.startswith("field.recommendation.mode_results.*.rationale")
        for k in failures(case, output)
    )


def test_manual_only_no_buy_must_not_invent_evidence():
    case = named("recommendation/manual-only-no-buy")
    bundle = RecommendationBundle(
        no_strong_buy=True,
        no_strong_buy_reason="No checked buying details. Next, look for clearer evidence.",
        comparison_matrix={},
        evidence_ids=(case.inputs.recommendation.request.run_id,),
    )
    output = TrustRecommendationOutput(
        recommendation=bundle, runtime_status="completed", model_calls=1
    )
    assert "evidence.bundle.ids" in failures(case, output)


def test_verifier_approval_cannot_hide_named_blocking_issues():
    case = named("verification/unsupported-specification")
    output = TrustRecommendationOutput(
        verification={
            "approved": True,
            "recommendation_bundle": case.inputs.verification.request.recommendation_bundle,
            "blocking_issues": ["Unsupported claims."],
        },
        runtime_status="completed",
        model_calls=1,
    )
    broken = failures(case, output)
    assert "verification.approval_consistency" in broken
    assert "evidence.final.factual_claims" in broken
    assert any(k.startswith("field.verification.approved") for k in broken)


def test_seller_trust_mutations_keep_listing_and_price_risk_specific():
    case = named("trust/upgrade-cannot-erase-price-risk")
    # The synthetic optimistic response is separate from scorer expectations.
    output = TrustRecommendationOutput(
        trust=case.inputs.trust.model_output.model_copy(deep=True),
        runtime_status="schema_invalid_rule_based_fallback",
        model_calls=1,
    )
    broken = failures(case, output)
    assert any(k.startswith("field.trust.level") for k in broken)
    assert any(k.startswith("field.trust.trust_signals") for k in broken)
    output.trust.listing_id = case.inputs.trust.price_peers[0].listing_id
    output.trust.evidence_ids = (case.inputs.trust.request.run_id,)
    broken = failures(case, output)
    assert "trust.listing_identity" in broken
    assert "trust.citations.0" in broken
