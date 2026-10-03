import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError
from pydantic_evals import Dataset
from pydantic_evals.reporting import EvaluationReport

from app.evals.fixtures import EvalFixtureSearchProvider, SearchFixture
from app.evals.runner import DEFAULT_OUTPUT_DIR, run_local_evaluation
from app.evals.scaffolding import SMOKE_FIXTURE_PATH, smoke_dataset
from app.evals.schemas import EvalMetadata, LocalEvalCase
from app.tools.run_evals import main


@pytest.mark.asyncio
async def test_fixture_provider_preserves_sources_and_returns_independent_records():
    provider = EvalFixtureSearchProvider.from_file(SMOKE_FIXTURE_PATH)
    inputs = smoke_dataset().cases[0].inputs
    results = await provider.search(inputs.query, inputs.options)
    assert str(results[0].url) == "https://example.com/cartcart-eval-fixture"
    assert str(results[0].source_id) == "00000000-0000-4000-8000-000000000095"
    results[0].title = "Changed by a caller"
    second = await provider.search(inputs.query, inputs.options)
    assert second[0].title == "Synthetic shopping source"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["query", "region", "options"])
async def test_unrecorded_request_fails_without_provider_fallback(change):
    provider = EvalFixtureSearchProvider.from_file(SMOKE_FIXTURE_PATH)
    inputs = smoke_dataset().cases[0].inputs
    if change == "query":
        inputs.query.query = "unrecorded query"
    elif change == "region":
        inputs.query.region_code = "US"
    else:
        inputs.options.max_results = 2
    with pytest.raises(ValueError, match="No eval search fixture"):
        await provider.search(inputs.query, inputs.options)


def test_case_and_fixture_validation():
    with pytest.raises(ValidationError):
        LocalEvalCase[str, str].model_validate({"name": "missing-fields"})
    fixture = json.loads(SMOKE_FIXTURE_PATH.read_text())
    fixture["results"][0]["query"]["region_code"] = "US"
    with pytest.raises(ValidationError, match="recorded query"):
        SearchFixture.model_validate(fixture)


@pytest.mark.parametrize(
    "outcome",
    ["passed", "assertion-failed", "task-failed", "evaluator-failed", "empty"],
)
def test_runner_saves_outcome_and_failure_details(tmp_path, monkeypatch, outcome):
    # Exercise report handling without executing an eval suite.
    case = {
        "name": "unit-case",
        "inputs": "input",
        "metadata": None,
        "expected_output": "expected",
        "output": "expected",
        "metrics": {},
        "attributes": {},
        "scores": {},
        "labels": {},
        "assertions": {
            "EqualsExpected": {
                "name": "EqualsExpected",
                "value": outcome == "passed",
                "reason": "fixture assertion",
                "source": {"name": "EqualsExpected"},
            }
        },
        "task_duration": 0,
        "total_duration": 0,
    }
    payload = {"name": "unit-report", "cases": [case], "failures": []}
    if outcome == "task-failed":
        payload["cases"] = []
        payload["failures"] = [
            {
                "name": "unit-case",
                "inputs": "input",
                "metadata": None,
                "expected_output": "expected",
                "error_message": "Missing fixture",
                "error_stacktrace": "fixture lookup failure",
            }
        ]
    elif outcome == "empty":
        payload["cases"] = []
    elif outcome == "evaluator-failed":
        case["evaluator_failures"] = [
            {
                "name": "EqualsExpected",
                "error_message": "Evaluator failed",
                "error_stacktrace": "evaluator failure",
                "source": {"name": "EqualsExpected"},
            }
        ]
    report = TypeAdapter(EvaluationReport[str, str, EvalMetadata]).validate_python(
        payload
    )
    monkeypatch.setattr(Dataset, "evaluate_sync", lambda *args, **kwargs: report)
    path, passed = run_local_evaluation(
        Dataset(name="unit-dataset", cases=[]), lambda value: value, tmp_path
    )
    saved = json.loads(path.read_text())
    assert passed == (outcome == "passed") == saved["passed"]
    assert saved["execution_mode"] == "fixture"
    assert saved["schema_version"] == 1
    if outcome == "task-failed":
        assert saved["report"]["failures"][0]["error_message"] == "Missing fixture"
    elif outcome != "empty":
        assert saved["report"]["cases"][0]["assertions"]["EqualsExpected"]["reason"]


def test_cli_smoke_persists_real_pydantic_eval_without_network(tmp_path, monkeypatch):
    import socket

    def reject_network(*args, **kwargs):
        raise AssertionError("Eval scaffolding must not open a network connection")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    assert main(["--output-dir", str(tmp_path)]) == 0
    saved = json.loads(next(tmp_path.glob("eval-*.json")).read_text())
    assert saved["passed"] is True
    assert saved["report"]["cases"][0]["name"] == "scaffolding/fixture-search"
    assert (
        DEFAULT_OUTPUT_DIR
        == Path(__file__).resolve().parents[3] / "data/artifacts/evals"
    )


def test_cli_returns_failure_exit_status(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.tools.run_evals.run_local_evaluation",
        lambda *args: (tmp_path / "failed.json", False),
    )
    assert main(["--output-dir", str(tmp_path)]) == 1
