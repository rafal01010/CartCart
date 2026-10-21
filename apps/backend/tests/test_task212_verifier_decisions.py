import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
from agents import Agent, RunConfig

from app.agents.contracts import VerificationReport
from app.agents.live_verifier_critic import (
    LiveVerifierCriticAgent,
    OpenAIAgentsSDKVerifierCriticModelRunner,
    _VerifierModelDecision,
    _model_input,
)
from app.schemas.analysis import RecommendationBundle
from app.schemas.ids import new_id
from test_context_management import ScriptModel, ScriptProvider
from test_live_verifier_critic_agent import _settings, _verification_input


@dataclass
class OfflineSDKRunner:
    output: dict[str, Any]
    model: ScriptModel = field(init=False)
    schema: dict[str, Any] = field(default_factory=dict)
    model_input: str = ""

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        self.model = ScriptModel([json.dumps(self.output)], actual=300)
        self.schema = agent.output_type.json_schema()
        self.model_input = model_input
        agent.model = "offline-verifier"
        return await OpenAIAgentsSDKVerifierCriticModelRunner().run(
            agent,
            model_input,
            run_config=replace(run_config, model_provider=ScriptProvider({"offline-verifier": self.model})),
            max_turns=max_turns,
        )


def _request():
    request = _verification_input(
        final_rationale="A useful option, with qualifications below."
    )
    analysis = request.category_analyses[0].model_copy(
        update={
            "fit_summary": "The monitor suits ordinary desk work. Confirm local warranty before buying.",
        }
    )
    bundle = request.recommendation_bundle.model_copy(
        update={
            "result_author": "MonitorSpecialistAgent",
            "handoff_chain": (
                "GeneralShoppingAgent",
                "TechnologySpecialistAgent",
                "MonitorSpecialistAgent",
            ),
            "warnings": (
                "Avoid the separate imported offer with unclear seller identity.",
            ),
        }
    )
    return request.model_copy(
        update={"recommendation_bundle": bundle, "category_analyses": (analysis,)}
    )


@pytest.mark.asyncio
async def test_sdk_unchanged_approval_preserves_literal_bundle_without_reemission(
    monkeypatch,
):
    monkeypatch.setattr(
        "socket.socket.connect",
        lambda *args: pytest.fail("Offline SDK control attempted network access."),
    )
    request = _request()
    runner = OfflineSDKRunner({})
    agent = LiveVerifierCriticAgent(settings=_settings(), model_runner=runner)
    report = await agent.run(request)
    assert report.approved is True
    assert report.recommendation_bundle.model_dump(
        mode="json"
    ) == request.recommendation_bundle.model_dump(mode="json")
    assert (
        report.recommendation_bundle.final_rationale
        == "A useful option, with qualifications below."
    )
    assert report.recommendation_bundle.warnings == (
        "Avoid the separate imported offer with unclear seller identity.",
    )
    assert len(runner.model.inputs) == 1
    assert "RecommendationBundle" not in json.dumps(runner.schema)
    assert "recommendation_bundle" not in _VerifierModelDecision.model_fields
    artifact = (
        Path(__file__).resolve().parents[3]
        / "data/artifacts/task212/verifier-sdk-measurements.json"
    )
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "schema_chars": len(json.dumps(runner.schema)),
                "same_baseline_fixture_input_chars": len(
                    _model_input(_verification_input())
                ),
                "observed_sdk_control_input_chars": len(runner.model_input),
                "generated_output_chars": len(json.dumps(runner.output)),
                "default_decision_output_chars": len(
                    _VerifierModelDecision().model_dump_json()
                ),
                "public_report_output_chars": len(report.model_dump_json()),
                "usage_is_synthetic": True,
                "transport_calls": len(runner.model.inputs),
                "baseline": json.loads(
                    (artifact.parent / "verifier-baseline.json").read_text()
                )
                if (artifact.parent / "verifier-baseline.json").exists()
                else {
                    "schema_chars": 7605,
                    "model_input_chars": 4962,
                    "public_report_output_chars": 1530,
                    "current_unchanged_decision_output_chars": 97,
                    "bundle_chars": 1437,
                },
                "baseline_note": "The previous null decision already supported compact unchanged output. This change removes the full bundle schema and changes supported revisions, not the already compact approval behavior.",
            },
            indent=2,
        )
        + "\n"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["final_rationale", "mode_rationale", "row_summary"])
async def test_sdk_copies_supported_canonical_explanation_without_touching_neighbors(
    target,
):
    request = _request()
    original = request.recommendation_bundle
    revision = {"target": target, "product_id": str(original.final_product_id)}
    if target == "mode_rationale":
        revision["mode"] = "best_overall"
    if target == "row_summary":
        revision["listing_id"] = str(original.final_listing_id)
    runner = OfflineSDKRunner({"revisions": [revision]})
    agent = LiveVerifierCriticAgent(settings=_settings(), model_runner=runner)
    report = await agent.run(request)
    assert report.approved is True
    assert agent.workbench_activity[0]["status"] == "optional_editorial_completed"
    expected = original.model_dump(mode="json")
    text = "The monitor suits ordinary desk work. Confirm local warranty before buying."
    if target == "final_rationale":
        expected["final_rationale"] = text
    elif target == "mode_rationale":
        expected["mode_results"][0]["rationale"] = text
    else:
        expected["comparison_matrix"]["rows"][0]["summary"] = text
    assert report.recommendation_bundle.model_dump(mode="json") == expected
    assert RecommendationBundle.model_validate(expected) == report.recommendation_bundle
    assert VerificationReport.model_validate(report.model_dump()) == report
    assert len(runner.model.inputs) == 1
    artifact = (
        Path(__file__).resolve().parents[3]
        / "data/artifacts/task212/verifier-sdk-measurements.json"
    )
    metrics = json.loads(artifact.read_text()) if artifact.exists() else {}
    metrics.setdefault("supported_revisions", {})[target] = {
        "sdk_model_input_chars": len(runner.model_input),
        "generated_output_chars": len(json.dumps(runner.output)),
        "reconstructed_legacy_full_report_output_chars": len(report.model_dump_json()),
        "baseline_note": "Legacy revised full-report output reconstructed from this exact final public report. No live usage measured.",
    }
    artifact.write_text(json.dumps(metrics, indent=2) + "\n")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        "novel_claim",
        "selection",
        "citation",
        "unknown_product",
        "unknown_listing",
        "duplicate_target",
        "invalid_support",
        "cross_candidate_support",
        "unknown_source",
        "blocked_change",
        "too_long_row",
        "atomic_failure",
    ],
)
async def test_sdk_rejects_unsupported_or_unsafe_edits_explicitly_and_atomically(bad):
    request = _request()
    original = request.recommendation_bundle
    revision = {
        "target": "final_rationale",
        "product_id": str(original.final_product_id),
    }
    output: dict[str, Any] = {"revisions": [revision]}
    if bad == "novel_claim":
        revision["text"] = "Guaranteed lifetime local warranty with no exclusions."
    elif bad == "selection":
        output["recommendation_bundle"] = {"final_product_id": str(new_id())}
    elif bad == "citation":
        revision["source_ids"] = [str(new_id())]
    elif bad == "unknown_product":
        revision["product_id"] = str(new_id())
    elif bad == "unknown_listing":
        revision.update(target="row_summary", listing_id=str(new_id()))
    elif bad == "duplicate_target":
        output["revisions"].append(dict(revision))
    elif bad == "invalid_support":
        request = request.model_copy(
            update={
                "category_analyses": (
                    request.category_analyses[0].model_copy(
                        update={"evidence_ids": (new_id(),)}
                    ),
                )
            }
        )
    elif bad == "cross_candidate_support":
        evidence = request.evidence[0].model_copy(
            update={
                "target": request.evidence[0].target.model_copy(
                    update={"product_id": new_id()}
                )
            }
        )
        request = request.model_copy(update={"evidence": (evidence,)})
    elif bad == "unknown_source":
        request = request.model_copy(
            update={
                "category_analyses": (
                    request.category_analyses[0].model_copy(
                        update={"source_ids": (new_id(),)}
                    ),
                )
            }
        )
    elif bad == "blocked_change":
        output.update(
            approved=False,
            blocking_issues=["The requested warranty claim is unsupported."],
        )
    elif bad == "too_long_row":
        revision.update(target="row_summary", listing_id=str(original.final_listing_id))
        request = request.model_copy(
            update={
                "category_analyses": (
                    request.category_analyses[0].model_copy(
                        update={"fit_summary": "X" * 1001}
                    ),
                )
            }
        )
    else:
        output["revisions"].append(
            {
                "target": "row_summary",
                "product_id": str(original.final_product_id),
                "listing_id": str(new_id()),
            }
        )
    runner = OfflineSDKRunner(output)
    agent = LiveVerifierCriticAgent(settings=_settings(), model_runner=runner)
    report = await agent.run(request)
    assert report.approved is True
    assert report.recommendation_bundle == original
    assert report.blocking_issues == ()
    assert "rejected" in " ".join(report.notes)
    assert agent.workbench_activity[0]["status"] == "optional_editorial_rejected"
    assert len(runner.model.inputs) == 1


@pytest.mark.asyncio
async def test_sdk_can_decline_unsupported_claim_without_vetoing_owner_advice():
    request = _request()
    runner = OfflineSDKRunner(
        {
            "approved": False,
            "blocking_issues": [
                "Do not add a lifetime warranty claim. Supplied information does not support it."
            ],
        }
    )
    agent = LiveVerifierCriticAgent(settings=_settings(), model_runner=runner)
    report = await agent.run(request)
    assert report.approved is True
    assert report.recommendation_bundle == request.recommendation_bundle
    assert report.blocking_issues == ()
    assert report.notes == (
        "Optional wording changes were declined. The original advice is preserved.",
        "Do not add a lifetime warranty claim. Supplied information does not support it.",
    )


@pytest.mark.asyncio
async def test_sdk_rejects_same_product_explanation_for_another_seller_offer():
    request = _request()
    other_listing = request.listings[0].model_copy(update={"listing_id": new_id()})
    original = request.recommendation_bundle.model_copy(
        update={"final_listing_id": other_listing.listing_id}
    )
    request = request.model_copy(
        update={
            "listings": (*request.listings, other_listing),
            "recommendation_bundle": original,
        }
    )
    runner = OfflineSDKRunner(
        {
            "revisions": [
                {
                    "target": "final_rationale",
                    "product_id": str(original.final_product_id),
                }
            ]
        }
    )
    agent = LiveVerifierCriticAgent(settings=_settings(), model_runner=runner)
    report = await agent.run(request)
    assert report.recommendation_bundle == original
    assert agent.workbench_activity[0]["status"] == "optional_editorial_rejected"
    assert "listing scope" in " ".join(report.notes)


@pytest.mark.asyncio
async def test_sdk_canonical_revision_carries_valid_references_and_source_warnings():
    request = _request()
    extra = request.evidence[0].model_copy(
        update={
            "evidence_id": new_id(),
            "claim": "The separate imported offer has unclear warranty.",
        }
    )
    analysis = request.category_analyses[0].model_copy(
        update={
            "evidence_ids": (extra.evidence_id,),
            "warnings": ("Confirm warranty for this exact offer.",),
        }
    )
    request = request.model_copy(
        update={
            "evidence": (*request.evidence, extra),
            "category_analyses": (analysis,),
        }
    )
    runner = OfflineSDKRunner(
        {
            "revisions": [
                {
                    "target": "mode_rationale",
                    "product_id": str(analysis.product_id),
                    "mode": "best_overall",
                }
            ]
        }
    )
    agent = LiveVerifierCriticAgent(settings=_settings(), model_runner=runner)
    report = await agent.run(request)
    assert (
        report.recommendation_bundle.mode_results[0].rationale
        == "The monitor suits ordinary desk work. Confirm local warranty before buying."
    )
    assert report.recommendation_bundle.evidence_ids == (
        *request.recommendation_bundle.evidence_ids,
        extra.evidence_id,
    )
    assert report.recommendation_bundle.mode_results[0].evidence_ids == (
        *request.recommendation_bundle.mode_results[0].evidence_ids,
        extra.evidence_id,
    )
    assert (
        report.recommendation_bundle.source_ids
        == request.recommendation_bundle.source_ids
    )
    assert report.recommendation_bundle.warnings == (
        "Avoid the separate imported offer with unclear seller identity.",
        "Confirm warranty for this exact offer.",
    )
    assert (
        report.recommendation_bundle.final_rationale
        == request.recommendation_bundle.final_rationale
    )
    assert agent.workbench_activity[0]["status"] == "optional_editorial_completed"


@pytest.mark.asyncio
async def test_sdk_revises_same_mode_for_two_distinct_candidates():
    request = _request()
    other_product = request.products[0].model_copy(
        update={"product_id": new_id(), "name": "Second Monitor", "listing_ids": ()}
    )
    other_analysis = request.category_analyses[0].model_copy(
        update={
            "product_id": other_product.product_id,
            "listing_ids": (),
            "evidence_ids": (),
            "fit_summary": "The second monitor suits compact desks. It has fewer connection options.",
        }
    )
    other_mode = request.recommendation_bundle.mode_results[0].model_copy(
        update={
            "product_id": other_product.product_id,
            "listing_id": None,
            "evidence_ids": (),
            "rationale": "A compact alternative.",
        }
    )
    original = request.recommendation_bundle.model_copy(
        update={
            "mode_results": (*request.recommendation_bundle.mode_results, other_mode)
        }
    )
    request = request.model_copy(
        update={
            "products": (*request.products, other_product),
            "category_analyses": (*request.category_analyses, other_analysis),
            "recommendation_bundle": original,
        }
    )
    runner = OfflineSDKRunner(
        {
            "revisions": [
                {
                    "target": "mode_rationale",
                    "product_id": str(request.products[0].product_id),
                    "mode": "best_overall",
                },
                {
                    "target": "mode_rationale",
                    "product_id": str(other_product.product_id),
                    "mode": "best_overall",
                },
            ]
        }
    )
    agent = LiveVerifierCriticAgent(settings=_settings(), model_runner=runner)
    report = await agent.run(request)
    assert tuple(
        item.rationale for item in report.recommendation_bundle.mode_results
    ) == (
        "The monitor suits ordinary desk work. Confirm local warranty before buying.",
        "The second monitor suits compact desks. It has fewer connection options.",
    )
    assert tuple(
        item.product_id for item in report.recommendation_bundle.mode_results
    ) == (request.products[0].product_id, other_product.product_id)
    assert report.recommendation_bundle.final_rationale == original.final_rationale
    assert agent.workbench_activity[0]["status"] == "optional_editorial_completed"
