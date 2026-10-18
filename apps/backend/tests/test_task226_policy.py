import json
from dataclasses import replace
from hashlib import sha256

import pytest

from app.agents.context_management import ContextBudget, ContextBudgetExceeded
from app.agents.context_management import completion_instructions
from app.agents.context_metrics import measure
from app.agents.decision_sources import fit_owner_projection, input_projection, select_decision_sources
from app.agents.live_comparison_decision import _build_comparison_decision_agent
from app.agents.token_policy import CompletionPurpose
from app.schemas.decision_sources import DecisionSourcePacket
from app.schemas.ids import new_id
from app.schemas.intake import ShoppingBrief
from test_live_general_shopping_agent import _RecordingRunner, _isolated_agent
from test_task224_finalization import LocalResponsesProvider, bounded_run, complete_output, response_payload


def packet(name, candidates, questions, text, *, findings=(), perspective=None, cautions=()):
    return DecisionSourcePacket(
        source_id=new_id(), url=f"https://example.org/{name}", title=name,
        content_kind="page", candidate_names=candidates, buying_questions=questions,
        excerpts=(text,), findings=findings, perspective=perspective,
        material_cautions=cautions, content_sha256=sha256(text.encode()).hexdigest(),
    )


def request(packets):
    brief = ShoppingBrief(original_query="Compare camera and battery for travel")
    projection = select_decision_sources(brief, packets)
    return json.dumps({"brief": brief.model_dump(mode="json"), "decision_sources": projection.model_dump(mode="json")})


def test_overlap_removal_keeps_late_alternative_and_exact_useful_facts():
    guide = packet("guide", ("Aster", "Birch"), ("camera", "battery"), "Aster has better low-light detail. Birch lasts longer during travel. " * 20)
    comfort = packet("comfort", ("Aster", "Birch"), ("comfort",), "Aster and Birch both fit a jacket pocket during travel. " * 20)
    late = packet("late", ("Cedar",), ("camera",), "Cedar keeps moving subjects sharp without a heavy body. " * 20)
    original = request((guide, comfort, late))
    assert input_projection(original).selected_source_ids == (guide.source_id, comfort.source_id, late.source_id)
    target = measure(original)["estimated_tokens"] - measure(comfort.model_dump(mode="json"))["estimated_tokens"] // 2
    fitted = fit_owner_projection(original, target)
    result = input_projection(fitted)
    assert result.selected_source_ids == (guide.source_id, late.source_id)
    assert result.deferred_source_ids == (comfort.source_id,)
    assert {row.candidate_name for row in result.candidate_coverage} == {"Aster", "Birch", "Cedar"}
    assert tuple(row.excerpts for row in result.sources) == (guide.excerpts, late.excerpts)
    assert json.loads(fitted)["brief"] == json.loads(original)["brief"]
    assert measure(fitted)["estimated_tokens"] <= target
    assert fit_owner_projection(fitted, target) == fitted


def test_redundant_positive_page_cannot_erase_contrary_findings_or_adverse_caution():
    favorable = packet("daily", ("Aster",), ("battery",), "Aster lasts a full day in light use. " * 20, findings=("full day in light use",), perspective="daily use")
    contrary = packet("navigation", ("Aster",), ("battery",), "Aster lasted under six hours during navigation and overheated. " * 20, findings=("under six hours during navigation",), perspective="continuous navigation", cautions=("Aster overheats during continuous navigation.",))
    repeated = packet("repeated", ("Aster",), ("battery",), "Aster has useful battery life for ordinary phone calls. " * 20)
    original = request((favorable, contrary, repeated))
    target = measure(original)["estimated_tokens"] - measure(repeated.model_dump(mode="json"))["estimated_tokens"] // 2
    fitted = fit_owner_projection(original, target)
    result = input_projection(fitted)
    assert set(result.selected_source_ids) == {favorable.source_id, contrary.source_id}
    assert result.deferred_source_ids == (repeated.source_id,)
    retained = {row.source_id: row for row in result.sources}
    assert retained[favorable.source_id].findings == ("full day in light use",)
    assert retained[contrary.source_id].findings == ("under six hours during navigation",)
    assert retained[contrary.source_id].material_cautions == ("Aster overheats during continuous navigation.",)
    assert retained[contrary.source_id] == contrary
    assert measure(fitted)["estimated_tokens"] <= target


def test_impossible_bound_keeps_sole_alternative_support_for_technical_failure():
    first = packet("first", ("Aster",), ("camera",), "Aster records stable video. " * 20)
    second = packet("second", ("Birch",), ("battery",), "Birch lasts longer during travel. " * 20)
    original = request((first, second))
    fitted = fit_owner_projection(original, measure(original)["estimated_tokens"] - 1)
    assert fitted == original
    assert {row.candidate_name for row in input_projection(fitted).candidate_coverage} == {"Aster", "Birch"}


def test_unique_conflicting_findings_remain_without_a_caution_label():
    favorable = packet("light-use", ("Aster",), ("battery",), "Aster lasts a full day in light use.", findings=("full day in light use",), perspective="light use")
    contrary = packet("navigation", ("Aster",), ("battery",), "Aster lasts under six hours during navigation.", findings=("under six hours during navigation",), perspective="navigation")
    original = request((favorable, contrary))
    assert fit_owner_projection(original, measure(original)["estimated_tokens"] - 1) == original


@pytest.mark.asyncio
async def test_unaffordable_faithful_request_fails_before_model_transport():
    original = request((
        packet("first", ("Aster",), ("camera",), "Aster records stable video. " * 100),
        packet("second", ("Birch",), ("battery",), "Birch lasts longer during travel. " * 100),
    ))
    provider = LocalResponsesProvider(response_payload(json.dumps(complete_output())))
    budget = ContextBudget()
    budget.limits = replace(budget.limits, input_tokens=600)
    try:
        with pytest.raises(ContextBudgetExceeded):
            await bounded_run(provider, budget, text=original)
        assert len(provider.calls) == 0
        assert budget.events[-1]["status"] == "blocked"
        assert "stable video" in original and "longer during travel" in original
    finally:
        await provider.client.close()


@pytest.mark.asyncio
async def test_actual_owner_constructors_share_selection_before_winner_and_completion_policy():
    runner = _RecordingRunner()
    owner, supplied, _, engine = await _isolated_agent(runner)
    try:
        await owner.run(supplied)
        general = runner.seen_agent
        technology = general.handoffs[0]._agent_ref()
        terminals = [handoff._agent_ref() for handoff in technology.handoffs]
        assert {agent.name for agent in terminals} == {
            "MonitorSpecialistAgent", "SmartphoneSpecialistAgent", "LaptopSpecialistAgent",
            "EarphonesHeadphonesSpecialistAgent", "TVSpecialistAgent", "SmartwatchSpecialistAgent",
        }
        comparison = _build_comparison_decision_agent("gpt-6-sol")
        for agent in (general, technology, *terminals, comparison):
            instructions = agent.instructions
            assert instructions.count("Select the useful option set before naming an optional preferred winner.") == 1
            assert instructions.index("Choose up to three strong useful primary choices first.") < instructions.index("Then actively consider up to two worthwhile runners-up")
            assert "larger number of retrieved pages" in instructions
            assert "Sources provide findings and viewpoints to weigh against the complete buyer brief." in instructions
            assert "usually belong among runners-up" not in instructions
            closure = completion_instructions(instructions, CompletionPurpose.OWNER)
            assert closure.count("Select the useful option set before naming an optional preferred winner.") == 1
            assert "Further research is closed" in closure
            assert closure.count("Write direct, concise advice about what to buy for an ordinary shopper.") == 1
            assert completion_instructions(closure, CompletionPurpose.OWNER) == closure
        schema = general.output_type.model_json_schema()
        assert schema["properties"]["selected_candidate_name"]["description"].startswith("Optional preferred winner")
        assert "Null is valid" in schema["properties"]["selected_candidate_name"]["description"]
        assert "selected useful" in schema["properties"]["candidates"]["description"] or "useful selected" in schema["properties"]["candidates"]["description"]
    finally:
        await engine.dispose()
