"""Task-local integrity/scorer/representative adapter checks; no scored Dataset run."""

import copy
import json
from collections import Counter
from types import SimpleNamespace

import pytest
from agents import Runner
from pydantic_evals import Dataset

from app.evals.source_intelligence import (
    CORPUS_PATH,
    SourceOutput,
    _Providers,
    offline_source_intelligence_task,
    source_intelligence_cases,
    source_intelligence_dataset,
)
from app.evals.source_intelligence_scoring import (
    SourceIntelligenceEvaluator,
    score_source_intelligence,
)
from app.schemas.confidence import Confidence
from app.schemas.search_sources import (
    VideoReviewEvidenceBundle,
    VideoReviewEvidence,
)
from app.services.amazon_evidence_creation import AmazonProductEvidenceCreator
from app.services.ikea_evidence_creation import IKEAStoreEvidenceCreator


def case(name):
    return next(c for c in source_intelligence_cases() if c.name == name)


def no_execution(*args, **kwargs):
    raise AssertionError("Scored Dataset/SDK execution is deferred to the gate.")


def test_corpus_coverage_independence_and_dataset(monkeypatch):
    monkeypatch.setattr(Dataset, "evaluate_sync", no_execution)
    monkeypatch.setattr(Dataset, "evaluate", no_execution)
    monkeypatch.setattr(Runner, "run", no_execution)
    cases = source_intelligence_cases()
    assert len(cases) == 36
    assert Counter(c.inputs.stage for c in cases) == {
        "youtube": 11,
        "reddit": 8,
        "amazon": 8,
        "ikea": 9,
    }
    assert {c.inputs.mode for c in cases} == {"service", "specialist"}
    assert sum(c.inputs.recommendation_claim is not None for c in cases) == 8
    dataset = source_intelligence_dataset()
    assert dataset.name == "cartcart-source-intelligence"
    assert len(dataset.cases) == 36
    cases[0].inputs.youtube.products[0].name = "Changed test input"
    assert (
        source_intelligence_cases()[0].inputs.youtube.products[0].name
        != "Changed test input"
    )
    assert "expected" not in cases[0].inputs.model_dump_json()


def test_documented_case_list_and_regular_quality_gate():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    evaluation = (root / "docs/EVALUATION.md").read_text()
    operations = (root / "docs/OPERATIONS.md").read_text()
    for c in source_intelligence_cases():
        assert f"`{c.name}`" in evaluation
    assert "This lane is required for reusable source handling changes" in evaluation
    assert "--suite source-intelligence" in operations


@pytest.mark.parametrize(
    "mutation",
    [
        "corpus-version",
        "nested-version",
        "duplicate-case",
        "missing-time",
        "missing-id",
        "second-stage",
        "wrong-criterion",
        "only-metadata",
        "empty-criteria",
        "duplicate-rule",
        "duplicate-transcript",
        "unknown-video",
        "unknown-product",
        "unknown-listing",
        "wrong-provider-kind",
        "fault-service",
        "unavailable-facts",
        "invalid-count",
        "invalid-set",
    ],
)
def test_malformed_corpus_fails_closed(tmp_path, mutation):
    raw = json.loads(CORPUS_PATH.read_text())
    first = raw["cases"][0]
    fixture = first["inputs"]
    amazon = raw["cases"][13]["inputs"]
    if mutation == "corpus-version":
        raw["schema_version"] = 2
    elif mutation == "nested-version":
        fixture["youtube"]["schema_version"] = 2
    elif mutation == "duplicate-case":
        raw["cases"].append(copy.deepcopy(first))
    elif mutation == "missing-time":
        del fixture["observed_at"]
    elif mutation == "missing-id":
        del fixture["youtube"]["products"][0]["product_id"]
    elif mutation == "second-stage":
        fixture["amazon"] = amazon["amazon"]
    elif mutation == "wrong-criterion":
        first["expected_output"]["fields"][0]["field"] = "amazon.evidence"
    elif mutation == "only-metadata":
        first["expected_output"]["fields"] = [
            dict(
                field="model_calls",
                operator="equals",
                value=0,
                requirement="Only metadata",
            )
        ]
    elif mutation == "empty-criteria":
        first["expected_output"]["fields"] = []
    elif mutation == "duplicate-rule":
        first["expected_output"]["fields"].append(first["expected_output"]["fields"][0])
    elif mutation == "duplicate-transcript":
        fixture["transcripts"].append(fixture["transcripts"][0])
    elif mutation == "unknown-video":
        fixture["transcripts"][0]["video"]["video_id"] = "unknown"
    elif mutation == "unknown-product":
        amazon["amazon_facts"][0]["product_id"] = "00000000-0000-4000-8000-000000000099"
    elif mutation == "unknown-listing":
        amazon["amazon_facts"][0]["listing_id"] = "00000000-0000-4000-8000-000000000099"
    elif mutation == "wrong-provider-kind":
        fixture["amazon_facts"] = amazon["amazon_facts"]
    elif mutation == "fault-service":
        fixture["model_fault"] = "timeout"
    elif mutation == "unavailable-facts":
        amazon["provider_status"] = "unavailable"
    elif mutation == "invalid-count":
        first["expected_output"]["fields"][1]["value"] = -1
    elif mutation == "invalid-set":
        first["expected_output"]["fields"][0]["value"] = "wrong shape"
    target = tmp_path / "bad-corpus.json"
    target.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        source_intelligence_cases(target)


def authored_video_output():
    c = case("youtube/transcript-bias")
    f = c.inputs
    snapshot = f.youtube.source_snapshots[0]
    recording = f.transcripts[0]
    risk = dict(
        level="medium", score=0.72, rationale="Visible sponsorship and affiliate links."
    )
    video = recording.video.model_copy(
        update={
            "sponsorship_disclosed": True,
            "affiliate_links_disclosed": True,
            "affiliate_bias_risk": Confidence.model_validate(risk),
        }
    )
    # Independent valid contract object, not an evaluated task response.
    video = type(video).model_validate(video.model_dump())
    evidence = tuple(
        VideoReviewEvidence(
            source_id=snapshot.source_id,
            target=dict(
                target_type="product", product_id=f.youtube.products[0].product_id
            ),
            video_id=video.video_id,
            claim=s.text,
            confidence=dict(level="medium", score=0.66, rationale="Quoted review."),
            source_quality=snapshot.quality,
            transcript_segment_ids=(s.segment_id,),
            timestamp_references=(
                dict(start_seconds=s.start_seconds, end_seconds=s.end_seconds),
            ),
        )
        for s in recording.segments
    )
    bundle = VideoReviewEvidenceBundle(
        videos=(video,),
        source_references=(
            dict(source_id=snapshot.source_id, url=video.url, title=video.title),
        ),
        transcript_segments=recording.segments,
        evidence=evidence,
    )
    return c, SourceOutput(youtube=bundle, model_calls=1)


def test_authored_video_contract_passes():
    c, output = authored_video_output()
    checks = score_source_intelligence(c.inputs, output, c.expected_output)
    assert all(r.value for r in checks.values()), checks


@pytest.mark.parametrize(
    "mutation,key",
    [
        ("quote", "quote"),
        ("timestamp", "timestamp"),
        ("bias", "bias"),
        ("channel", "channel"),
        ("availability", "availability"),
        ("target", "target"),
        ("page", "identity"),
        ("affiliate", "neutral"),
    ],
)
def test_video_regressions_fail_named_assertions(mutation, key):
    c, output = authored_video_output()
    data = output.model_dump(mode="json")
    b = data["youtube"]
    if mutation == "quote":
        b["evidence"][0]["claim"] = "Invented 240Hz panel."
    elif mutation == "timestamp":
        b["evidence"][0]["timestamp_references"][0]["start_seconds"] = 18
    elif mutation == "bias":
        b["videos"][0]["sponsorship_disclosed"] = False
    elif mutation == "channel":
        b["videos"][0]["channel_name"] = "Wrong channel"
    elif mutation == "availability":
        b["videos"][0]["transcript_availability"] = "unavailable"
    elif mutation == "target":
        b["evidence"][0]["target"]["product_id"] = (
            "00000000-0000-4000-8000-000000000099"
        )
    elif mutation == "page":
        b["source_references"][0]["url"] = "https://www.youtube.com/watch/wrong"
    elif mutation == "affiliate":
        b["source_references"][0]["url"] += "&tag=affiliate"
    checks = score_source_intelligence(c.inputs, data, c.expected_output)
    assert any(key in k and not r.value for k, r in checks.items()), checks
    assert all("Actual:" in r.reason for r in checks.values())


@pytest.mark.parametrize(
    "stage,mutation,key",
    [
        ("amazon", "seller", "context"),
        ("amazon", "review-count", "context"),
        ("amazon", "shipping", "context"),
        ("amazon", "risk", "seller_risk"),
        ("amazon", "review-risk", "review_provenance"),
        ("ikea", "price", "context"),
        ("ikea", "currency", "context"),
        ("ikea", "region", "region"),
        ("ikea", "scope", "scope"),
    ],
)
def test_marketplace_and_store_regressions(stage, mutation, key):
    c = case("amazon/pooled-variants" if stage == "amazon" else "ikea/local-delivery")
    bundle = (
        AmazonProductEvidenceCreator().create(c.inputs.amazon_facts)
        if stage == "amazon"
        else IKEAStoreEvidenceCreator().create(c.inputs.ikea_facts)
    )
    data = SourceOutput(**{stage: bundle}, model_calls=0).model_dump(mode="json")
    b = data[stage]
    if stage == "amazon":
        ctx = b["listing_contexts"][0]
        if mutation == "seller":
            ctx["seller_name"] = "Amazon"
        elif mutation == "review-count":
            ctx["review_count"] = 999999
        elif mutation == "shipping":
            ctx["ships_to_region"] = True
        else:
            b["evidence"] = [
                e
                for e in b["evidence"]
                if e["fact_type"]
                != (
                    "marketplace_warning"
                    if mutation == "risk"
                    else "review_quality_warning"
                )
            ]
    else:
        ctx = b["store_contexts"][0]
        if mutation == "price":
            ctx["price"]["amount"] = "1"
        elif mutation == "currency":
            ctx["price"]["currency"] = "USD"
        elif mutation == "region":
            ctx["country_code"] = "US"
        elif mutation == "scope":
            b["evidence"][0]["evidence_quality_warnings"] = []
    checks = score_source_intelligence(c.inputs, data, c.expected_output)
    assert any(key in k and not r.value for k, r in checks.items()), checks


def test_evaluator_schema_errors_are_named():
    c = case("youtube/transcript-bias")
    checks = score_source_intelligence(c.inputs, {}, c.expected_output)
    assert not checks["schema.output"].value
    ctx = SimpleNamespace(inputs=c.inputs, output={}, expected_output=None)
    assert (
        not SourceIntelligenceEvaluator().evaluate(ctx)["schema.expected_output"].value
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "youtube/relevant-video",
        "youtube/transcript-bias",
        "youtube/unavailable",
        "youtube/invented-quote",
        "reddit/quoted-recurrence",
        "reddit/invented-quote",
        "amazon/marketplace-seller-region",
        "amazon/retained-hard-risk",
        "ikea/official-ph-read",
        "ikea/invented-price",
        "downstream/amazon-cited",
        "downstream/youtube-unsupported",
    ],
)
async def test_representative_adapters_are_offline_and_do_not_mutate_inputs(
    monkeypatch, name
):
    import httpx

    attempts = []

    async def reject(*args, **kwargs):
        attempts.append("forbidden call")
        raise AssertionError("No SDK/network calls in Task 99A.")

    monkeypatch.setattr(Runner, "run", reject)
    monkeypatch.setattr(httpx.AsyncClient, "request", reject)
    monkeypatch.setenv("LIVE_AGENTS_ENABLED", "true")
    monkeypatch.setenv("OPENAI_AGENT_TRACING_ENABLED", "true")
    c = case(name)
    before = c.inputs.model_dump(mode="json")
    task = offline_source_intelligence_task()
    assert (
        not task.settings.live_agents_enabled
        and not task.settings.openai_agent_tracing_enabled
    )
    output = await task(c.inputs)
    assert attempts == []
    assert c.inputs.model_dump(mode="json") == before
    checks = score_source_intelligence(c.inputs, output, c.expected_output)
    failures = {k: r.reason for k, r in checks.items() if not r.value}
    assert not failures, failures


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["youtube", "reddit", "amazon", "ikea"])
@pytest.mark.parametrize("supported", [True, False])
async def test_downstream_controls_preserve_grounding_decisions_and_cautions(
    monkeypatch, stage, supported
):
    import httpx
    import socket

    monkeypatch.setattr(Runner, "run", no_execution)
    monkeypatch.setattr(Dataset, "evaluate", no_execution)
    monkeypatch.setattr(Dataset, "evaluate_sync", no_execution)
    monkeypatch.setattr(httpx.AsyncClient, "request", no_execution)
    monkeypatch.setattr(httpx.Client, "request", no_execution)
    monkeypatch.setattr(socket.socket, "connect", no_execution)
    c = case(f"downstream/{stage}-{'cited' if supported else 'unsupported'}")
    before = c.inputs.model_dump(mode="json")
    output = await offline_source_intelligence_task()(c.inputs)
    checks = score_source_intelligence(c.inputs, output, c.expected_output)
    assert {k: r.reason for k, r in checks.items() if not r.value} == {}
    assert c.inputs.model_dump(mode="json") == before
    assert output.verification.approved is supported
    draft = output.recommendation
    assert draft.final_rationale == c.inputs.recommendation_claim
    source_ids = {e.evidence_id for e in output.bundle.evidence}
    assert source_ids.issubset(set(draft.evidence_ids))
    assert set(draft.source_ids) == {
        e.source_id for e in (*output.bundle.evidence, *c.inputs.offer_evidence)
    }
    assert draft.no_strong_buy is (stage == "reddit")
    assert draft.final_product_id == (
        None if stage == "reddit" else c.inputs.request.products[0].product_id
    )
    assert draft.final_listing_id == (
        None if stage == "reddit" else c.inputs.request.listings[0].listing_id
    )
    claims = {e.evidence_id: e.claim for e in output.bundle.evidence}
    for row in draft.comparison_matrix.rows:
        assert row.summary == " ".join(
            claim
            for evidence_id, claim in claims.items()
            if evidence_id in row.evidence_ids
        )
    cautions = " ".join(draft.warnings)
    if stage == "youtube":
        assert (
            "treat review claims with bias caution"
            in output.bundle.videos[0].bias_notes
        )
        assert "sponsorship and affiliate-link disclosures" in cautions
        assert "bias caution" in cautions
    elif stage == "reddit":
        assert "qualitative" in cautions
        assert "brigaded or astroturfed" in cautions
        assert "biased or manipulated" in cautions
        assert (
            "Do not use Reddit alone for specifications, warranty, price, or availability."
            in cautions
        )
        assert "ear pads split after a few months" in draft.no_strong_buy_reason
        assert "Next," in draft.no_strong_buy_reason
        assert draft.rejected_items[0].reason_code.value == "poor_fit"
        assert "ear pads split after a few months" in draft.rejected_items[0].reason
    elif stage == "amazon":
        assert (
            "listing trust must be assessed separately from product quality" in cautions
        )
        assert "not independently authenticated" in cautions
        assert "pool multiple Amazon variants" in cautions
    else:
        assert (
            "shipping elsewhere"
            in output.bundle.evidence[0].evidence_quality_warnings[0]
        )
        assert "applies only to PH" in cautions
        assert "postcode" in draft.comparison_matrix.rows[0].summary
    if supported:
        assert output.verification.blocking_issues == ()
        assert output.verification.recommendation_bundle == draft
    else:
        assert "240Hz OLED" in draft.final_rationale
        assert any(
            "factual claim not backed" in issue
            for issue in output.verification.blocking_issues
        )


@pytest.mark.parametrize(
    "mutation",
    ["missing-citations", "invented-citation", "unsupported-spec", "wrong-source-kind"],
)
def test_downstream_regressions_fail_independently(mutation):
    c = case("downstream/amazon-cited")
    bundle = AmazonProductEvidenceCreator().create(c.inputs.amazon_facts)
    # Independent authored draft, never an evaluated task/model response.
    raw = json.loads((CORPUS_PATH.parent / "trust_recommendation.json").read_text())
    draft = next(
        v["inputs"]["verification"]["request"]
        for v in raw["cases"]
        if v["name"] == "verification/supported-claims"
    )
    ids = [str(e.evidence_id) for e in bundle.evidence]
    sources = [str(bundle.source_references[0].source_id)]
    analysis = draft["category_analyses"][0]
    analysis.update(
        product_id=str(c.inputs.request.products[0].product_id),
        listing_ids=[str(c.inputs.request.listings[0].listing_id)],
        evidence_ids=ids,
        source_ids=sources,
    )
    recommendation = draft["recommendation_bundle"]
    recommendation.update(
        final_product_id=str(c.inputs.request.products[0].product_id),
        final_listing_id=str(c.inputs.request.listings[0].listing_id),
        evidence_ids=ids,
        source_ids=sources,
        final_rationale=c.inputs.recommendation_claim,
    )
    for mode in recommendation["mode_results"]:
        mode.update(
            product_id=recommendation["final_product_id"],
            listing_id=recommendation["final_listing_id"],
            evidence_ids=ids,
            source_ids=sources,
            rationale=c.inputs.recommendation_claim,
        )
    data = dict(
        amazon=bundle.model_dump(mode="json"),
        analysis=analysis,
        recommendation=recommendation,
        verification=dict(
            approved=True,
            recommendation_bundle=recommendation,
            blocking_issues=[],
            notes=[],
        ),
        model_calls=4,
    )
    positive = score_source_intelligence(c.inputs, data, c.expected_output)
    assert all(v.value for v in positive.values()), positive
    if mutation == "missing-citations":
        data["analysis"]["evidence_ids"] = [str(c.inputs.offer_evidence[0].evidence_id)]
    elif mutation == "invented-citation":
        data["analysis"]["evidence_ids"] = ["00000000-0000-4000-8000-000000000099"]
    elif mutation == "unsupported-spec":
        recommendation["mode_results"][0]["rationale"] = (
            "This candidate has a 240Hz OLED screen."
        )
    else:
        data["ikea"] = (
            IKEAStoreEvidenceCreator()
            .create(case("ikea/local-delivery").inputs.ikea_facts)
            .model_dump(mode="json")
        )
        data.pop("amazon")
    checks = score_source_intelligence(c.inputs, data, c.expected_output)
    assert any(not v.value for v in checks.values()), checks


@pytest.mark.asyncio
async def test_fixture_providers_reject_unrecorded_requests():
    f = case("youtube/transcript-bias").inputs
    with pytest.raises(ValueError, match="Unrecorded"):
        await _Providers(f).search_videos("not recorded")
    video = f.transcripts[0].video.model_copy(update={"video_id": "unknown"})
    with pytest.raises(ValueError, match="Unrecorded"):
        await _Providers(f).fetch_transcript(video)


@pytest.mark.parametrize("passed", [True, False])
def test_cli_selection_preserves_failure_exit_without_running_evals(
    monkeypatch, tmp_path, capsys, passed
):
    from app.tools import run_evals

    monkeypatch.setattr(Dataset, "evaluate_sync", no_execution)
    selected = []

    def fake_run(dataset, task, output_dir):
        selected.append((dataset.name, len(dataset.cases), callable(task), output_dir))
        return output_dir / "not-written.json", passed

    monkeypatch.setattr(run_evals, "run_local_evaluation", fake_run)
    assert run_evals.main(
        ["--suite", "source-intelligence", "--output-dir", str(tmp_path)]
    ) == (0 if passed else 1)
    assert selected == [("cartcart-source-intelligence", 36, True, tmp_path)]
    assert ("passed" if passed else "failed") in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["youtube/late-transcript-focus", "reddit/late-discussion-focus"])
async def test_late_source_facts_are_retrieved_without_rewriting_support(name):
    c = case(name)
    output = await offline_source_intelligence_task()(c.inputs)
    checks = score_source_intelligence(c.inputs, output, c.expected_output)
    assert all(result.value for result in checks.values()), checks
    if output.youtube:
        assert c.inputs.read_focus is None
        quote = output.youtube.evidence[0]
        segment = next(s for s in c.inputs.transcripts[0].segments if s.segment_id == quote.transcript_segment_ids[0])
        assert quote.claim in segment.text
        assert "the stand wobbles on light desks" in quote.claim
        assert quote.timestamp_references[0].start_seconds == 15
        assert output.youtube.videos[0].sponsorship_disclosed is True
    else:
        assert output.reddit.evidence[0].recurring_signal is True
        assert len(output.reddit.evidence[0].supporting_quotes) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["youtube/late-transcript-focus", "reddit/late-discussion-focus"])
async def test_parent_source_context_uses_exact_validated_evidence_without_raw_replay(name):
    from app.agents.context_management import source_bundle_context
    output = await offline_source_intelligence_task()(case(name).inputs)
    bundle = output.youtube or output.reddit
    canonical = bundle.model_dump(mode="json")
    projected = source_bundle_context(bundle)
    assert projected["evidence"] == canonical["evidence"]
    assert projected["source_references"] == canonical["source_references"]
    assert len(json.dumps(projected)) < len(json.dumps(canonical))
    assert bundle.model_dump(mode="json") == canonical
    if output.youtube:
        assert "transcript_segments" not in projected
        assert projected["videos"] == canonical["videos"]
    else:
        assert all(discussion["text_deferred"] is True for discussion in projected["discussions"])
        assert all("extracted_public_summary" not in discussion for discussion in projected["discussions"])
