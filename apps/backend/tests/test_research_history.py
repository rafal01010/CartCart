import json
from dataclasses import replace

import pytest
from agents import Agent, RunConfig, function_tool

from app.agents.context_management import (
    BoundedRunner,
    ContextBudget,
    ContextBudgetExceeded,
    ContextLimits,
    context_scope,
    prepare_history,
)
from app.agents.research_history import (
    active_history,
    history_scope,
    retired_output,
    tracked_tools,
)
from test_context_management import ScriptModel, ScriptProvider, call


def test_only_explicit_processing_retires_verified_views_and_keeps_late_warranty():
    body = "Price PHP 90000. " + "Background text. " * 500 + "No local warranty."
    with history_scope() as history:
        original = json.dumps(
            {"status": "succeeded", "source_id": "same-run-page", "text": body}
        )
        output = history.register("fetch_source", original)
        view_id = json.loads(output)["_research_view"]["view_id"]
        assert retired_output(output) == output
        assert (
            history.complete(view_id, ["Invented safe seller."])["status"]
            == "invalid_request"
        )
        assert retired_output(output) == output
        assert history.complete(view_id, ["Price PHP 90000."])["status"] == "processed"
        compact = retired_output(output)
        state = json.loads(compact)
        assert state["retained"]["facts"] == ["Price PHP 90000."]
        assert state["retained"]["cautions"] == ["No local warranty."]
        assert state["retained"]["identities"] == {"source_id": ["same-run-page"]}
        assert "unreviewed" in state["retained"]["coverage"]
        assert len(compact) < len(output) / 2
        reread = history.read(view_id, focus="No local warranty")
        assert "No local warranty." in reread["text"]
        assert reread["text_truncated"] is True
        assert history.views[view_id].original == json.dumps(
            json.loads(original), ensure_ascii=False, separators=(",", ":")
        )
        changed = json.loads(output)
        changed["text"] += " Conflicting seller warranty applies only overseas."
        assert retired_output(json.dumps(changed)) == json.dumps(changed)
        newer = history.register("fetch_source", json.dumps(changed))
        assert "Conflicting seller warranty" in retired_output(newer)
        assert (
            history.complete("missing-original", ["Price PHP 90000."])["status"]
            == "unknown_view"
        )
    with history_scope() as other:
        assert other.read(view_id)["status"] == "unknown_view"
        assert retired_output(output) == output


def test_tiny_outputs_do_not_gain_reference_overhead():
    tiny = json.dumps(
        {"status": "succeeded", "quote": "Price PHP 90000.", "evidence_id": "quote-id"}
    )
    with history_scope() as history:
        assert history.register("record_source_quote", tiny) == tiny
        assert history.views == {}


def test_processing_keeps_structured_gap_reasons_and_video_bias_context():
    payload = {
        "status": "succeeded",
        "source_id": "source",
        "text": "Background. " * 300 + "Exact useful fact.",
        "video": {
            "video_id": "video",
            "sponsorship_disclosed": True,
            "affiliate_links_disclosed": True,
            "bias_notes": "The maker supplied this sample.",
        },
        "evidence_gaps": [
            {
                "gap_id": "gap",
                "source_id": "source",
                "summary": "Amazon shipping to PH could not be confirmed.",
                "reason": "The regional check did not complete.",
            }
        ],
    }
    with history_scope() as history:
        output = history.register(
            "consult_amazon_product_listing_review", json.dumps(payload)
        )
        view_id = json.loads(output)["_research_view"]["view_id"]
        history.complete(view_id, ["Exact useful fact."])
        retained = json.loads(retired_output(output))["retained"]
        assert retained["gaps"] == [
            "Amazon shipping to PH could not be confirmed.",
            "The regional check did not complete.",
        ]
        assert retained["cautions"] == ["The maker supplied this sample."]
        video = next(
            row for row in retained["references"] if row.get("video_id") == "video"
        )
        assert video["sponsorship_disclosed"] is True
        assert video["affiliate_links_disclosed"] is True
        gap = next(row for row in retained["references"] if row.get("gap_id") == "gap")
        assert gap["source_id"] == "source"
        assert gap["summary"] == "Amazon shipping to PH could not be confirmed."


@pytest.mark.asyncio
async def test_actual_sdk_processed_cached_read_is_compact_and_new_reads_stay_visible():
    canonical = {
        "status": "succeeded",
        "snapshot_id": "page",
        "text": "Price PHP 90000. " + "Background. " * 700 + "No local warranty.",
    }

    @function_tool
    async def read_run_evidence(source_id: str) -> str:
        assert source_id == "page"
        return json.dumps(canonical)

    def checkpoint(input, tools):
        output = next(
            json.loads(item["output"])
            for item in input
            if item.get("type") == "function_call_output"
        )
        assert "Background." in output["text"]
        view_id = output["_research_view"]["view_id"]
        return call(
            "complete_research_result",
            "process",
            view_id=view_id,
            retained_facts=["Price PHP 90000."],
        )

    def cached(input, tools):
        text = json.dumps(input)
        assert "Background." not in text
        assert "No local warranty." in text
        assert "unreviewed" in text
        assert prepare_history(input) == input
        return call("read_run_evidence", "cached", source_id="page")

    def change(input, tools):
        assert "Background." not in json.dumps(input)
        canonical["text"] += " Regional seller terms conflict."
        return call("read_run_evidence", "changed", source_id="page")

    def finish(input, tools):
        last = json.loads(
            [
                item["output"]
                for item in input
                if item.get("type") == "function_call_output"
            ][-1]
        )
        assert "Regional seller terms conflict." in last["text"]
        assert "Background." in last["text"]
        return "Do not buy this imported offer without local warranty."

    model = ScriptModel(
        [
            call("read_run_evidence", "first", source_id="page"),
            checkpoint,
            cached,
            change,
            finish,
        ],
        actual=1000,
    )
    budget = ContextBudget()
    with context_scope(budget):
        result = await BoundedRunner.run(
            Agent(
                name="GeneralShoppingAgent",
                model="bounded",
                tools=list(tracked_tools((read_run_evidence,))),
            ),
            "Inspect the local warranty before selecting a seller.",
            run_config=RunConfig(
                model_provider=ScriptProvider({"bounded": model}), tracing_disabled=True
            ),
            max_turns=6,
        )
    assert (
        result.final_output == "Do not buy this imported offer without local warranty."
    )
    assert budget.spent == 5500
    assert active_history() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("characters,allowed", [(40000, True), (46000, False)])
async def test_revised_headroom_funds_middle_range_but_blocks_above_19000(
    characters, allowed
):
    model = ScriptModel(["Funded exact decision"], actual=1000)
    budget = ContextBudget()
    with context_scope(budget):
        if allowed:
            result = await BoundedRunner.run(
                Agent(name="VerifierCriticAgent", model="bounded"),
                "x" * characters,
                run_config=RunConfig(
                    model_provider=ScriptProvider({"bounded": model}),
                    tracing_disabled=True,
                ),
                max_turns=1,
            )
            assert result.final_output == "Funded exact decision"
        else:
            with pytest.raises(ContextBudgetExceeded):
                await BoundedRunner.run(
                    Agent(name="VerifierCriticAgent", model="bounded"),
                    "x" * characters,
                    run_config=RunConfig(
                        model_provider=ScriptProvider({"bounded": model}),
                        tracing_disabled=True,
                    ),
                    max_turns=1,
                )
    estimate = budget.events[0]["output"]["estimated_input_tokens"]
    if allowed:
        assert 16000 < estimate < 19000
        assert budget.spent == 1100
    else:
        assert estimate > 19000
        assert budget.spent == 0
        assert len(model.inputs) == 0
    assert (
        ContextLimits().decision_reserve
        == ContextLimits().verification_reserve
        == 24000
    )
    assert replace(ContextLimits(), total_tokens=90000).input_tokens == 19000


def test_retired_cautions_keep_bounds_and_explicit_deferred_coverage():
    body = "Price PHP 90000. " + "Warranty uncertain " * 1000
    payload = {
        "status": "succeeded",
        "source_id": "bounded-cautions",
        "text": body,
        "material_cautions": ["Seller warning " + "details " * 1000] * 7,
        "deferred_caution_count": 20,
        "cautions_truncated": True,
        "caution_focus_terms": ["warranty", "seller"],
        "unreviewed_cautions": True,
    }
    with history_scope() as history:
        output = history.register("fetch_source", json.dumps(payload))
        view_id = json.loads(output)["_research_view"]["view_id"]
        history.complete(view_id, ["Price PHP 90000."])
        retained = json.loads(retired_output(output))["retained"]
        assert len(retained["cautions"]) <= 6
        assert all(len(passage) <= 300 for passage in retained["cautions"])
        assert retained["deferred_caution_count"] >= 20
        assert retained["unreviewed_cautions"] is True
        assert retained["cautions_truncated"] is True
        assert {"warranty", "seller"}.issubset(retained["caution_focus_terms"])
        assert history.unjustified_safety_claims(
            "This product has a local warranty.",
            ["This product has a local warranty."],
            ["bounded-cautions"],
        ) == ("This product has a local warranty.",)
        assert (
            history.read(view_id, focus="Warranty uncertain")["status"] == "succeeded"
        )


@pytest.mark.parametrize(
    "assurance",
    [
        "The listing is safe to buy; price may change.",
        "The seller is legitimate and not counterfeit.",
        "This product is safe to buy before Friday.",
        "This is a reputable seller.",
        "You can buy confidently.",
        "This product is genuine.",
        "The offer is low-risk.",
    ],
)
def test_unprocessed_research_and_unrelated_qualifications_cannot_prove_safety(
    assurance,
):
    with history_scope() as history:
        history.register(
            "fetch_source",
            json.dumps(
                {
                    "status": "succeeded",
                    "source_id": "unchecked",
                    "text": "Price PHP 90000. "
                    + "Navigation. " * 400
                    + "No local warranty.",
                }
            ),
        )
        assert history.unjustified_safety_claims(
            assurance, ["Price PHP 90000."], ["unchecked"]
        )
        assert not history.unjustified_safety_claims(
            "This product is not safe to buy.", ["Price PHP 90000."], ["unchecked"]
        )
        assert not history.unjustified_safety_claims(
            "Check whether this product is safe to buy.",
            ["Price PHP 90000."],
            ["unchecked"],
        )


def test_one_warning_field_with_multiple_passages_keeps_deferred_count():
    with history_scope() as history:
        output = history.register(
            "fetch_source",
            json.dumps(
                {
                    "source_id": "multi-risk",
                    "warning": " ".join(f"Risk {index}." for index in range(7)),
                    "text": "Useful fact. " + "Navigation. " * 400,
                }
            ),
        )
        view_id = json.loads(output)["_research_view"]["view_id"]
        history.complete(view_id, ["Useful fact."])
        retained = json.loads(retired_output(output))["retained"]
        assert retained["cautions"] == [f"Risk {index}." for index in range(6)]
        assert retained["deferred_caution_count"] == 1
        assert retained["unreviewed_cautions"] is True
        assert "Risk 6." in history.read(view_id, focus="Risk 6.")["text"]


def test_explicit_completion_supersedes_automatic_projection_and_keeps_fresh_read():
    with history_scope() as history:
        body = "Price PHP 2400. " + "Background prose. " * 1000 + "No local warranty."
        output = history.register(
            "fetch_source", json.dumps({"source_id": "page", "text": body})
        )
        view_id = json.loads(output)["_research_view"]["view_id"]
        projected = json.dumps(
            {
                "source_id": "page",
                "text": body[:800],
                "_research_view": {"view_id": view_id, "tool": "fetch_source"},
                "_context_projection": {
                    "derived_context": True,
                    "omitted_material_unreviewed": True,
                },
            }
        )
        history.projections[output] = projected
        assert retired_output(output) == projected
        assert history.complete(view_id, ["Price PHP 2400."])["status"] == "processed"
        fresh = history.register(
            "read_source_snapshot",
            json.dumps(
                {
                    "source_id": "page",
                    "text": "Late evidence prose. " * 100 + "No local warranty.",
                    "start_char": 4000,
                }
            ),
        )
        items = [
            {
                "type": "function_call",
                "call_id": "old",
                "name": "fetch_source",
                "arguments": "{}",
            },
            {"type": "function_call_output", "call_id": "old", "output": output},
            {
                "type": "function_call",
                "call_id": "fresh",
                "name": "read_source_snapshot",
                "arguments": "{}",
            },
            {"type": "function_call_output", "call_id": "fresh", "output": fresh},
        ]
        prepared = prepare_history(items)
        retained = json.loads(prepared[1]["output"])
        assert retained["status"] == "processed"
        assert retained["retained"]["facts"] == ["Price PHP 2400."]
        assert retained["retained"]["cautions"] == ["No local warranty."]
        assert "Background prose." not in prepared[1]["output"]
        assert (
            json.loads(prepared[3]["output"])["text"]
            == "Late evidence prose. " * 100 + "No local warranty."
        )
        assert [item["call_id"] for item in prepared] == [
            "old",
            "old",
            "fresh",
            "fresh",
        ]


def test_large_completed_receipt_keeps_original_instead_of_stale_projection():
    body = " ".join(f"Word{index}" for index in range(150))
    with history_scope() as history:
        output = history.register(
            "fetch_source", json.dumps({"source_id": "a", "text": body})
        )
        view_id = json.loads(output)["_research_view"]["view_id"]
        automatic = json.dumps(
            {"source_id": "a", "text": body[:80], "derived_context": True}
        )
        history.projections[output] = automatic
        facts = [body[start : start + 350] for start in range(0, 600, 50)]
        assert history.complete(view_id, facts)["status"] == "processed"
        assert len(history.retired(view_id)) > len(output)
        assert retired_output(output) == output
        assert facts[-1] in json.loads(retired_output(output))["text"]
        assert retired_output(output) != automatic
