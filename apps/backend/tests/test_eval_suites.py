import json
from pathlib import Path

import pytest

from app.evals.suites import LANES, QUICK_CASES, run_suite, select_dataset
from app.tools import run_evals


def test_quick_selection_is_fixed_fresh_and_preserves_scoring():
    assert sum(map(len, QUICK_CASES.values())) == 27
    assert sum(len(lane.dataset().cases) for lane in LANES) == 112
    assert tuple(QUICK_CASES) == tuple(lane.name for lane in LANES)
    stages = set()
    for lane in LANES:
        original = lane.dataset()
        selected = select_dataset(lane, "quick")
        assert tuple(case.name for case in selected.cases) == QUICK_CASES[lane.name]
        assert selected.evaluators
        assert [type(e) for e in selected.evaluators] == [
            type(e) for e in original.evaluators
        ]
        original_by_name = {case.name: case for case in original.cases}
        for case in selected.cases:
            reference = original_by_name[case.name]
            assert case.inputs == reference.inputs
            assert case.expected_output == reference.expected_output
            stages.add(case.name.split("/")[0])
        selected.cases.clear()
        assert len(select_dataset(lane, "quick").cases) == len(QUICK_CASES[lane.name])
    assert stages == {
        "scaffolding",
        "guide",
        "intake",
        "planning",
        "discovery",
        "quality",
        "extraction",
        "dedupe",
        "guardrail",
        "trust",
        "recommendation",
        "verification",
        "youtube",
        "reddit",
        "amazon",
        "ikea",
        "downstream",
    }


@pytest.mark.parametrize("selection", [(), ("missing",), ("guardrail/off-topic",) * 2])
def test_stale_empty_duplicate_quick_selections_fail_closed(monkeypatch, selection):
    monkeypatch.setitem(QUICK_CASES, "trust-recommendation", selection)
    with pytest.raises(ValueError):
        select_dataset(LANES[3], "quick")


@pytest.mark.parametrize("suite", ["quick", "full"])
@pytest.mark.parametrize("failure_index", [None, 0, 4])
def test_suite_order_manifest_and_failure_propagation(tmp_path, suite, failure_index):
    calls = []

    def runner(dataset, task, output_dir):
        assert callable(task)
        assert output_dir == tmp_path
        index = len(calls)
        calls.append((dataset.name, len(dataset.cases)))
        return tmp_path / f"eval-{index}.json", index != failure_index

    path, passed = run_suite(suite, tmp_path, runner)
    saved = json.loads(path.read_text())
    expected_names = [lane.dataset().name + "-quick" for lane in LANES]
    if suite == "full":
        expected_names += [lane.dataset().name for lane in LANES]
    assert [name for name, _ in calls] == expected_names
    assert passed == saved["passed"] == (failure_index is None)
    assert saved["execution_mode"] == "fixture"
    assert saved["schema_version"] == 1
    assert sum(count for _, count in calls[:5]) == 27
    if suite == "full":
        assert sum(count for _, count in calls[5:]) == 112
    assert [lane["phase"] for lane in saved["lanes"]] == (
        ["quick"] * 5 if suite == "quick" else ["quick"] * 5 + ["full"] * 5
    )
    for lane, (name, count) in zip(saved["lanes"], calls, strict=True):
        assert len(lane["case_names"]) == count
        assert Path(lane["report_path"]).parent == tmp_path


@pytest.mark.parametrize("suite", ["quick", "full"])
@pytest.mark.parametrize("passed", [True, False])
def test_cli_uses_suite_orchestrator_without_scored_execution(
    tmp_path, monkeypatch, capsys, suite, passed
):
    seen = []

    def fake_suite(selected, output_dir, runner):
        seen.append((selected, output_dir, runner))
        return tmp_path / "suite.json", passed

    monkeypatch.setattr(run_evals, "run_suite", fake_suite)
    assert run_evals.main(["--suite", suite, "--output-dir", str(tmp_path)]) == (
        0 if passed else 1
    )
    assert seen == [(suite, tmp_path, run_evals.run_local_evaluation)]
    assert f"Offline {suite} eval" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


def test_quick_retains_observed_regressions_and_documented_cases():
    repository = Path(__file__).resolve().parents[3]
    documentation = (repository / "docs/EVALUATION.md").read_text()
    for names in QUICK_CASES.values():
        for name in names:
            assert f"`{name}`" in documentation
    for name in (
        "intake/inferred-monitor-fields",
        "extraction/punctuated-price-fidelity",
        "recommendation/preferred-stretch",
        "recommendation/manual-only-no-buy",
        "recommendation/conflict-disclosure",
        "youtube/invented-quote",
    ):
        assert any(name in names for names in QUICK_CASES.values())


def test_selected_task_factories_override_live_settings(monkeypatch):
    monkeypatch.setenv("CARTCART_LIVE_AGENTS_ENABLED", "true")
    monkeypatch.setenv("CARTCART_OPENAI_AGENT_TRACING_ENABLED", "true")
    for lane in LANES[1:]:
        task = lane.task()
        owner = task.__self__
        settings = (
            owner.intake.settings if lane.name == "intake-planning" else owner.settings
        )
        assert settings.live_agents_enabled is False
        assert settings.openai_agent_tracing_enabled is False
        assert settings.openai_api_key is None


def test_gate_fixture_corrections_preserve_independent_expectations():
    from app.evals.intake_planning import intake_planning_cases
    from app.evals.discovery_extraction import discovery_extraction_cases
    from app.evals.trust_recommendation import trust_recommendation_cases

    intake = next(
        c for c in intake_planning_cases() if c.name == "intake/explicit-controls"
    )
    region = next(r for r in intake.expected_output.fields if r.field == "brief.region")
    assert region.value["region"]["locale"] is None
    assert region.value["notes"] is None
    proxy = next(
        c for c in discovery_extraction_cases() if c.name == "quality/excluded-proxy"
    )
    assert proxy.inputs.quality.url.host == "www.zenmarket.jp"
    assert (
        next(
            r for r in proxy.expected_output.fields if r.field == "quality.excluded"
        ).value
        is True
    )
    positive = next(
        c
        for c in trust_recommendation_cases()
        if c.name == "trust/established-retailer"
    )
    listing = positive.inputs.trust.request.listing
    assert listing.sku and listing.region_availability[0].status == "available"
    assert listing.region_availability[0].checked_at is not None
    assert (
        next(
            r for r in positive.expected_output.fields if r.field == "trust.level"
        ).value
        == "strong"
    )


def test_timeout_availability_uses_observed_metadata_but_still_checks_bias():
    from app.evals.source_intelligence import source_intelligence_cases, SourceOutput
    from app.evals.source_intelligence_scoring import score_source_intelligence
    from app.schemas.search_sources import VideoReviewEvidenceBundle

    case = next(c for c in source_intelligence_cases() if c.name == "youtube/timeout")
    video = case.inputs.youtube.source_snapshots[0].video.model_copy(deep=True)
    output = SourceOutput(
        youtube=VideoReviewEvidenceBundle(videos=(video,)), model_calls=1
    )
    scored = score_source_intelligence(case.inputs, output, case.expected_output)
    assert scored[f"youtube.{video.video_id}.availability"].value is True
    assert scored[f"youtube.{video.video_id}.bias"].value is False
    video.transcript_availability = "available"
    scored = score_source_intelligence(case.inputs, output, case.expected_output)
    assert scored[f"youtube.{video.video_id}.availability"].value is False
