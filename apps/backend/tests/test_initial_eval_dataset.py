"""Corpus integrity checks only: no eval execution, provider or model calls."""

import json
import socket

import pytest
from pydantic import ValidationError

from app.evals.initial_dataset import CORPUS_DIR, initial_cases, initial_dataset


def test_corpus_loads_offline_with_complete_coverage(monkeypatch):
    def reject_network(*args, **kwargs):
        raise AssertionError("Loading the shopping corpus must stay offline")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    cases = initial_cases()
    assert len(cases) == 24
    assert len({case.name for case in cases}) == 24
    tags = {tag for case in cases for tag in case.metadata.tags}
    assert {
        "guided-intake",
        "off-topic",
        "unsafe",
        "monitor",
        "smartphone",
        "laptop",
        "headphones",
        "tv",
        "smartwatch",
        "office-chair",
        "coffee-grinder",
        "running-shoes",
        "power-bank",
        "youtube",
        "reddit",
        "amazon",
        "ikea",
        "user-added-product",
        "region-specific-query",
        "suspicious-listing",
        "budget-stretch",
        "duplicates",
        "weak-sources",
        "refinement",
    } <= tags
    assert all(case.expected_output.criteria for case in cases)
    assert all("synthetic" in case.metadata.tags for case in cases)
    # Guardrail and guided intake cases are backed by requests/answers, not
    # invented product evidence. Later-stage cases have source excerpts or gaps.
    for case in cases:
        if case.name.startswith(("guardrail/", "intake/")):
            assert case.inputs.brief is None
            assert not case.inputs.sources
        else:
            assert case.inputs.brief is not None
            assert case.inputs.sources
            assert all(
                source.excerpts or source.evidence_gaps
                for source in case.inputs.sources
            )
    dataset = initial_dataset()
    assert dataset.name == "cartcart-initial-shopping"
    assert [case.name for case in dataset.cases] == [case.name for case in cases]
    assert dataset.evaluators == []


def test_load_returns_independent_inputs_and_expectations():
    first = initial_cases()
    first[3].inputs.products[0].name = "Caller mutation"
    first[3].expected_output.criteria[0].requirement = "Caller expectation mutation"
    second = initial_cases()
    assert second[3].inputs.products[0].name == "Fixture M27"
    assert (
        second[3].expected_output.criteria[0].requirement
        != "Caller expectation mutation"
    )


@pytest.mark.parametrize(
    "change, message",
    [
        ("duplicate-name", "names must be unique"),
        ("missing-fixture", "fixtures must match exactly"),
        ("unused-fixture", "fixtures must match exactly"),
        ("unknown-source", "expectation cites an unknown source"),
        ("unknown-evidence", "expectation cites unknown evidence"),
        ("wrong-evidence-source", "evidence must cite its owning source"),
        ("dangling-listing", "unknown product"),
        ("duplicate-source", "Duplicate source IDs"),
        ("empty-criteria", "at least 1 item"),
        ("unsupported-version", "Unsupported corpus version"),
    ],
)
def test_broken_corpus_fails_closed(tmp_path, change, message):
    manifest = json.loads((CORPUS_DIR / "cases.json").read_text())
    corpus = json.loads((CORPUS_DIR / "inputs.json").read_text())
    case = manifest["cases"][3]
    inputs = corpus["fixtures"][case["inputs"]]
    unknown_id = "00000000-0000-4000-8000-000000000000"
    if change == "duplicate-name":
        case["name"] = manifest["cases"][0]["name"]
    elif change == "missing-fixture":
        del corpus["fixtures"][case["inputs"]]
    elif change == "unused-fixture":
        corpus["fixtures"]["unused"] = inputs
    elif change == "unknown-source":
        case["expected_output"]["criteria"][0]["source_ids"] = [unknown_id]
    elif change == "unknown-evidence":
        case["expected_output"]["criteria"][0]["evidence_ids"] = [unknown_id]
    elif change == "wrong-evidence-source":
        case["expected_output"]["criteria"][0]["source_ids"] = [
            inputs["sources"][1]["source_id"]
        ]
    elif change == "dangling-listing":
        inputs["listings"][0]["product_id"] = unknown_id
    elif change == "duplicate-source":
        inputs["sources"].append(inputs["sources"][0])
    elif change == "empty-criteria":
        case["expected_output"]["criteria"] = []
    elif change == "unsupported-version":
        corpus["schema_version"] = 2
    for filename, payload in (("cases.json", manifest), ("inputs.json", corpus)):
        (tmp_path / filename).write_text(json.dumps(payload))
    with pytest.raises((ValueError, ValidationError), match=message):
        initial_cases(tmp_path)


def test_every_case_is_documented():
    evaluation_doc = CORPUS_DIR.parents[5] / "docs" / "EVALUATION.md"
    text = evaluation_doc.read_text()
    for case in initial_cases():
        assert f"`{case.name}`" in text
