"""Observed Section Q failures must pass the original acceptance assertions."""

import socket

import pytest
from agents import Runner

from app.evals.discovery_extraction import (
    discovery_extraction_cases,
    offline_discovery_extraction_task,
)
from app.evals.discovery_extraction_scoring import score_discovery_extraction
from app.evals.intake_planning import (
    intake_planning_cases,
    offline_intake_planning_task,
)
from app.evals.intake_planning_scoring import score_intake_planning
from app.evals.source_intelligence import (
    source_intelligence_cases,
    offline_source_intelligence_task,
)
from app.evals.source_intelligence_scoring import score_source_intelligence
from app.evals.trust_recommendation import (
    trust_recommendation_cases,
    offline_trust_recommendation_task,
)
from app.evals.trust_recommendation_scoring import score_trust_recommendation
from app.services.volunteered_products import volunteered_names


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,loader,factory,score",
    [
        (
            "guide/monitor-sequence",
            intake_planning_cases,
            offline_intake_planning_task,
            score_intake_planning,
        ),
        (
            "planning/coffee-grinder-us",
            intake_planning_cases,
            offline_intake_planning_task,
            score_intake_planning,
        ),
        (
            "extraction/punctuated-price-fidelity",
            discovery_extraction_cases,
            offline_discovery_extraction_task,
            score_discovery_extraction,
        ),
        (
            "recommendation/preferred-stretch",
            trust_recommendation_cases,
            offline_trust_recommendation_task,
            score_trust_recommendation,
        ),
        (
            "recommendation/manual-only-no-buy",
            trust_recommendation_cases,
            offline_trust_recommendation_task,
            score_trust_recommendation,
        ),
        (
            "recommendation/conflict-disclosure",
            trust_recommendation_cases,
            offline_trust_recommendation_task,
            score_trust_recommendation,
        ),
        (
            "verification/invented-citation",
            trust_recommendation_cases,
            offline_trust_recommendation_task,
            score_trust_recommendation,
        ),
        (
            "youtube/invented-quote",
            source_intelligence_cases,
            offline_source_intelligence_task,
            score_source_intelligence,
        ),
        (
            "youtube/wrong-source",
            source_intelligence_cases,
            offline_source_intelligence_task,
            score_source_intelligence,
        ),
        (
            "youtube/timeout",
            source_intelligence_cases,
            offline_source_intelligence_task,
            score_source_intelligence,
        ),
    ],
)
async def test_observed_failure_meets_unchanged_acceptance(
    name, loader, factory, score, monkeypatch
):
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Section Q repairs must remain offline.")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(Runner, "run", forbidden)
    case = next(case for case in loader() if case.name == name)
    before = case.inputs.model_dump()
    output = await factory()(case.inputs)
    failures = {
        key: value.reason
        for key, value in score(case.inputs, output, case.expected_output).items()
        if not value.value
    }
    assert not attempts
    assert case.inputs.model_dump() == before
    assert not failures, failures


@pytest.mark.parametrize(
    "text,considered,expected",
    [
        ("Coding and movies", False, ()),
        ("Prefer comfortable seating", False, ()),
        ("Harbor M27", False, ("Harbor M27",)),
        ("Fixture Audio Pro", False, ("Fixture Audio Pro",)),
        ("IKEA MICKE", False, ("IKEA MICKE",)),
        ("an ergonomic office chair", True, ("an ergonomic office chair",)),
        ("Check Harbor M27 and Willow M27", False, ("Harbor M27", "Willow M27")),
    ],
)
def test_candidate_hints_require_product_context_or_model_identity(
    text, considered, expected
):
    assert volunteered_names(text, considered_answer=considered) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "price,accepted",
    [
        ("PHP 15,000.", True),
        ("PHP 15,000.00.", True),
        ("PHP 15000,", True),
        ("PHP 15,000.99.", False),
        ("PHP 15,000.999.", False),
        ("PHP 15,00.", False),
    ],
)
async def test_cited_price_support_accepts_punctuation_without_truncating_numbers(
    price, accepted
):
    case = next(
        c
        for c in discovery_extraction_cases()
        if c.name == "extraction/punctuated-price-fidelity"
    )
    content = case.inputs.extraction.request.workbench_snapshots[0].extracted_content
    content.text = content.text.replace("PHP 15,000.", price)
    output = await offline_discovery_extraction_task()(case.inputs)
    assert bool(output.extraction.listings) is accepted
    assert bool(output.extraction.evidence_gaps) is not accepted


@pytest.mark.asyncio
async def test_manual_only_fallback_keeps_evidence_empty_even_with_a_source_reference():
    case = next(
        c
        for c in trust_recommendation_cases()
        if c.name == "recommendation/manual-only-no-buy"
    )
    request = case.inputs.recommendation.request
    # A source record is not an evidence record.
    request.products[0].source_ids = (request.run_id,)
    output = await offline_trust_recommendation_task()(case.inputs)
    assert output.recommendation.no_strong_buy is True
    assert output.recommendation.evidence_ids == ()
    assert all(
        not row.evidence_ids for row in output.recommendation.comparison_matrix.rows
    )


@pytest.mark.asyncio
async def test_fallback_bias_uses_approved_transcript_disclosures_and_preserves_stronger_context():
    case = next(
        c for c in source_intelligence_cases() if c.name == "youtube/invented-quote"
    )
    video = case.inputs.youtube.source_snapshots[0].video
    video.description = "Fixture Monitor review."
    video.affiliate_bias_risk = {
        "score": 0.9,
        "level": "high",
        "rationale": "Recorded review-bias caution.",
    }
    case.inputs.transcripts[0].segments[
        0
    ].text += " Sponsored review with affiliate links."
    output = await offline_source_intelligence_task()(case.inputs)
    emitted = output.youtube.videos[0]
    assert emitted.sponsorship_disclosed is True
    assert emitted.affiliate_links_disclosed is True
    assert emitted.affiliate_bias_risk.score == 0.9
    assert all(
        e.metadata_only and not e.timestamp_references for e in output.youtube.evidence
    )
    assert all(
        e.sponsorship_disclosed and e.affiliate_bias_risk.score == 0.9
        for e in output.youtube.evidence
    )


@pytest.mark.asyncio
async def test_verifier_keeps_specific_unknown_evidence_issue_from_model_output():
    from app.agents.live_verifier_critic import (
        LiveVerifierCriticAgent,
        MockVerifierCriticModelRunner,
    )
    from app.agents.contracts import VerificationReport

    case = next(
        c
        for c in trust_recommendation_cases()
        if c.name == "verification/invented-citation"
    )
    task = offline_trust_recommendation_task()
    request = case.inputs.verification.request
    agent = LiveVerifierCriticAgent(
        task.settings,
        model_runner=MockVerifierCriticModelRunner(
            output=VerificationReport(
                approved=True, recommendation_bundle=request.recommendation_bundle
            ),
        ),
    )
    report = await agent.run(request)
    assert report.approved is False
    assert "unknown evidence" in " ".join(report.blocking_issues)
