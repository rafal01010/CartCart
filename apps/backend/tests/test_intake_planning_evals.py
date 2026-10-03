"""Task-local corpus/scorer/adapter tests; these do not run a scored eval suite."""

import json
import socket
from copy import deepcopy

import pytest
from agents import Runner
from pydantic import ValidationError
from pydantic_evals import Dataset

from app.evals.intake_planning import (
    INTAKE_PLANNING_PATH,
    IntakePlanningOutput,
    intake_planning_cases,
    intake_planning_dataset,
    offline_intake_planning_task,
)
from app.evals.intake_planning_scoring import score_intake_planning
from app.schemas.intake import ShoppingBrief
from app.schemas.search_sources import SearchPlan
from app.tools.run_evals import main


def _case(name):
    return next(case for case in intake_planning_cases() if case.name == name)


def _failures(case, actual):
    return {
        name: result.reason
        for name, result in score_intake_planning(
            case.inputs, actual, case.expected_output
        ).items()
        if result.value is False
    }


def _monitor_output():
    # Independently authored actual output, never copied from eval expectations.
    return IntakePlanningOutput(
        brief=ShoppingBrief.model_validate(
            {
                "original_query": "I need a 27-inch 1440p monitor for coding and movies under PHP 18,000 in the Philippines",
                "category": "monitor",
                "category_source": "inferred",
                "region": {
                    "region": {"country_code": "PH", "currency": "PHP"},
                    "source": "inferred",
                },
                "budget": {
                    "amount": {"amount": "18000", "currency": "PHP"},
                    "mode": "hard_cap",
                    "source": "inferred",
                },
                "constraints": [
                    {"text": "27-inch size", "mode": "hard", "source": "inferred"},
                    {"text": "1440p resolution", "mode": "hard", "source": "inferred"},
                ],
                "preferences": [
                    {"text": "Good for coding", "mode": "soft", "source": "inferred"},
                    {"text": "Good for movies", "mode": "soft", "source": "inferred"},
                ],
            }
        )
    )


def _plan_output():
    return IntakePlanningOutput(
        search_plan=SearchPlan.model_validate(
            {
                "queries": [
                    {
                        "query": "monitor below 15,000 PHP PH stores",
                        "intent": "discovery",
                        "region_code": "PH",
                        "required_source_types": ["retailer_listing"],
                    },
                    {
                        "query": "1440p monitor coding reviews comparison",
                        "intent": "review",
                        "region_code": "PH",
                        "required_source_types": ["professional_review"],
                    },
                    {
                        "query": "monitor PH seller prices warranty",
                        "intent": "price_check",
                        "region_code": "PH",
                        "required_source_types": ["product_page"],
                    },
                    {
                        "query": "Harbor M27 official PH listing",
                        "intent": "official_source",
                        "region_code": "PH",
                        "required_source_types": ["official_brand_page"],
                    },
                ],
                "rationale": "Check local offers and independent reviews for coding fit and warranty.",
            }
        )
    )


def _guide_output():
    return IntakePlanningOutput.model_validate(
        {
            "guide_states": [
                {
                    "status": "collecting",
                    "current_question": {
                        "question_id": "comparison-priority",
                        "text": "Which matters most for this comparison?",
                        "purpose": "priorities",
                        "answer_surface": "inline_choice",
                        "capture_targets": ["priorities"],
                        "inline_choice": {
                            "control_id": "priority",
                            "control_type": "two_option_plus_type_answer",
                            "options": [
                                {"choice_id": "comfort", "label": "Comfort"},
                                {"choice_id": "value", "label": "Value"},
                            ],
                            "custom_answer_label": "Type my answer",
                        },
                    },
                    "analysis_start": {
                        "enough_information": True,
                        "can_skip_all_and_start_analysis": True,
                    },
                }
            ],
            "considered_products": [
                "Sony WH-1000XM5",
                "Bose QuietComfort Ultra headphones",
            ],
        }
    )


def test_corpus_dataset_and_documentation_are_complete_without_execution(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Loading a corpus must not execute agents or evals")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(Dataset, "evaluate_sync", reject)
    monkeypatch.setattr(Runner, "run", reject)
    cases = intake_planning_cases()
    assert len(cases) == 17
    assert {
        stage: sum(case.inputs.stage == stage for case in cases)
        for stage in ("guide", "intake", "planning")
    } == {"guide": 8, "intake": 4, "planning": 5}
    dataset = intake_planning_dataset()
    assert dataset.name == "cartcart-intake-planning"
    assert len(dataset.cases) == 17
    assert len(dataset.evaluators) == 1
    docs = (INTAKE_PLANNING_PATH.parents[5] / "docs" / "EVALUATION.md").read_text()
    for case in cases:
        assert f"`{case.name}`" in docs
        assert case.expected_output.fields
        assert "mocked-contract" in case.metadata.tags


def test_inputs_and_expectations_are_independent_fresh_loads():
    first = _case("intake/inferred-monitor-fields")
    first.inputs.request.query = "Changed by caller"
    first.expected_output.fields[0].value = "Changed expectation"
    second = _case(first.name)
    assert second.inputs.request.query.startswith("I need a 27-inch")
    assert second.expected_output.fields[0].value.startswith("I need a 27-inch")


@pytest.mark.parametrize(
    "broken",
    [
        "version",
        "case-version",
        "input-version",
        "nested-version",
        "duplicate",
        "stage",
        "operand",
        "empty",
        "plan",
        "terms",
    ],
)
def test_invalid_corpus_fails_closed(tmp_path, broken):
    payload = json.loads(INTAKE_PLANNING_PATH.read_text())
    first = payload["cases"][0]
    if broken == "version":
        payload["schema_version"] = 2
    elif broken == "case-version":
        first["schema_version"] = 2
    elif broken == "input-version":
        first["inputs"]["schema_version"] = 2
    elif broken == "nested-version":
        first["inputs"]["guide_turns"][0]["schema_version"] = 2
    elif broken == "duplicate":
        payload["cases"].append(deepcopy(first))
    elif broken == "stage":
        first["inputs"]["stage"] = "intake"
    elif broken == "operand":
        first["expected_output"]["fields"][0].update(
            operator="includes", value="wrong-shape"
        )
    elif broken == "empty":
        first["expected_output"]["fields"] = []
    elif broken == "plan":
        del payload["cases"][-1]["expected_output"]["plan"]
    else:
        payload["cases"][-1]["expected_output"]["plan"]["context_terms"] = [[]]
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(payload))
    with pytest.raises((ValidationError, ValueError)):
        intake_planning_cases(path)


def test_scorer_accepts_independent_outputs_and_equivalent_search_wording():
    assert not _failures(_case("intake/inferred-monitor-fields"), _monitor_output())
    assert not _failures(
        _case("planning/ph-monitor-and-considered-name"), _plan_output()
    )
    assert not _failures(_case("guide/comparison-control"), _guide_output())


@pytest.mark.parametrize(
    "path,value,field",
    [
        ("category", "tv", "brief.category"),
        ("budget.amount.amount", "19000", "brief.budget.amount.amount"),
        ("budget.amount.currency", "USD", "brief.budget.amount.currency"),
        ("budget.mode", "preferred", "brief.budget.mode"),
        ("budget.source", "user_provided", "brief.budget.source"),
        ("region.region.country_code", "US", "brief.region.region.country_code"),
        ("region.source", "user_provided", "brief.region.source"),
        ("constraints.0.mode", "soft", "brief.constraints.0.mode"),
        ("preferences.1.mode", "hard", "brief.preferences.1.mode"),
    ],
)
def test_wrong_brief_fields_have_specific_failure_reasons(path, value, field):
    actual = _monitor_output().model_dump(mode="json")
    target = actual["brief"]
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    target[parts[-1]] = value
    failures = _failures(_case("intake/inferred-monitor-fields"), actual)
    assert any(
        name.startswith(f"field.{field}[") and field in reason and "Actual:" in reason
        for name, reason in failures.items()
    )


def test_schema_failure_and_missing_or_unknown_paths_never_pass():
    case = _case("intake/inferred-monitor-fields")
    actual = _monitor_output().model_dump(mode="json")
    actual["brief"]["budget"]["mode"] = "unrecognized"
    assert "schema.brief.budget.mode" in _failures(case, actual)
    case.expected_output.fields[0].field = "brief.misspelled_field"
    assert "wrong shape" in next(iter(_failures(case, _monitor_output()).values()))
    assert _failures(case, IntakePlanningOutput())


@pytest.mark.parametrize(
    "broken,criterion",
    [
        ("surface", "current_question.answer_surface"),
        ("control", "inline_choice.control_type"),
        ("sequence", "current_question.purpose"),
        ("skip", "skippable_question.can_skip"),
        ("names", "considered_products"),
        ("extra-name", "considered_products"),
        ("focus", "current_question.focus"),
        ("recommendation", "current_question.no_recommendation"),
    ],
)
def test_poor_guide_behavior_names_the_failed_criterion(broken, criterion):
    actual = _guide_output().model_dump(mode="json")
    state = actual["guide_states"][0]
    question = state["current_question"]
    if broken == "surface":
        question.update(answer_surface="textbox", inline_choice=None)
    elif broken == "control":
        question["inline_choice"].update(
            control_type="two_option", custom_answer_label=None
        )
    elif broken == "sequence":
        question["purpose"] = "budget"
    elif broken == "skip":
        state["skippable_question"]["can_skip"] = True
    elif broken == "names":
        actual["considered_products"] = []
    elif broken == "extra-name":
        actual["considered_products"].append("Coding and movies")
    elif broken == "focus":
        question["text"] = "What is your budget? What is your use case?"
    else:
        question["text"] = "I recommend Harbor M27. What matters most?"
    assert any(
        criterion in name
        for name in _failures(_case("guide/comparison-control"), actual)
    )


def test_question_repetition_and_missing_turns_fail():
    case = _case("guide/comparison-control")
    case.inputs.guide_turns[0].skipped_question_ids = ("comparison-priority",)
    failures = _failures(case, _guide_output())
    assert "guide_states.0.current_question.no_repeat" in failures
    assert "guide.question_sequence.length" in _failures(case, IntakePlanningOutput())


@pytest.mark.parametrize(
    "broken,criterion",
    [
        ("region", "search_plan.queries.region_code"),
        ("sources", "reasoning.source_strategy"),
        ("topic", "reasoning.topic_relevance"),
        ("context", "reasoning.context[0]"),
        ("name", "reasoning.considered_products[0]"),
        ("budget", "reasoning.budget"),
        ("duplicate", "reasoning.duplicate_queries"),
        ("blocked", "reasoning.generic_support"),
        ("rationale", "search_plan.rationale"),
    ],
)
def test_bad_search_plans_identify_reasoning_failures(broken, criterion):
    actual = _plan_output().model_dump(mode="json")
    plan = actual["search_plan"]
    queries = plan["queries"]
    if broken == "region":
        queries[0]["region_code"] = "US"
    elif broken == "sources":
        queries[1]["required_source_types"] = ["retailer_listing"]
    elif broken == "topic":
        queries[1]["query"] = "running shoe reviews"
    elif broken == "context":
        queries[1]["query"] = "monitor reviews for coding"
    elif broken == "name":
        queries.pop()
    elif broken == "budget":
        queries[0]["query"] = "monitor around 15000 PHP PH stores"
    elif broken == "duplicate":
        duplicate = deepcopy(queries[0])
        duplicate["query"] = "  MONITOR below 15,000 PHP PH stores  "
        queries.append(duplicate)
    elif broken == "blocked":
        plan["rationale"] = "No specialist exists; cannot search."
    else:
        plan["rationale"] = None
    failures = _failures(_case("planning/ph-monitor-and-considered-name"), actual)
    assert criterion in failures
    assert failures[criterion] and "Actual:" in failures[criterion]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "guide/monitor-sequence",
        "intake/inferred-monitor-fields",
        "planning/ph-monitor-and-considered-name",
    ],
)
async def test_offline_adapters_invoke_production_contracts_without_sdk_or_network(
    name, monkeypatch
):
    forbidden_calls = []

    def reject(*args, **kwargs):
        forbidden_calls.append(True)
        raise AssertionError("Mocked adapters must not call SDK Runner or network")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(Runner, "run", reject)
    monkeypatch.setenv("CARTCART_LIVE_AGENTS_ENABLED", "true")
    monkeypatch.setenv("CARTCART_OPENAI_AGENT_TRACING_ENABLED", "true")
    case = _case(name)
    before = case.inputs.model_dump_json()
    task = offline_intake_planning_task()
    output = await task(case.inputs)
    assert not forbidden_calls
    assert isinstance(output, IntakePlanningOutput)
    assert task.intake.settings.live_agents_enabled is False
    assert task.intake.settings.openai_agent_tracing_enabled is False
    assert task.intake.settings.openai_model == "eval-mock-model"
    assert case.inputs.model_dump_json() == before
    if case.inputs.stage == "guide":
        assert len(output.guide_states) == 4
        assert output.brief.category == "monitor"
        assert "Harbor M27" in output.considered_products
        assert task.guide.model_runner.calls == 4
        assert task.intake.model_runner.calls == 1
    elif case.inputs.stage == "intake":
        assert output.brief.category == "monitor"
        assert task.intake.model_runner.calls == 1
    else:
        assert output.search_plan.queries
        assert task.planner.model_runner.calls == 1


def test_cli_selects_scoped_suite_and_keeps_failure_exit_without_evaluation(
    tmp_path, monkeypatch
):
    calls = []

    def stub_run(dataset, task, output_dir):
        calls.append((dataset, task, output_dir))
        return tmp_path / "mock-report.json", False

    monkeypatch.setattr("app.tools.run_evals.run_local_evaluation", stub_run)
    assert main(["--suite", "intake-planning", "--output-dir", str(tmp_path)]) == 1
    assert calls[0][0].name == "cartcart-intake-planning"
    assert calls[0][2] == tmp_path
