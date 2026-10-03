"""Independent source provenance, gap, scope and downstream assertions."""

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pydantic import ValidationError
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from app.evals.schemas import EvalMetadata
from app.evals.source_intelligence import (
    SourceExpectation,
    SourceFixture,
    SourceOutput,
    SourceResult,
)
from app.evals.trust_recommendation_scoring import _values, shopper_text
from app.schemas.search_sources import VideoReviewEvidenceBundle


def _check(passed: bool, requirement: str, actual: Any) -> EvaluationReason:
    return EvaluationReason(value=passed, reason=f"{requirement} Actual: {actual!r}")


def score_source_intelligence(
    inputs: SourceFixture, output: object, expected: SourceExpectation
) -> dict[str, EvaluationReason]:
    try:
        actual = SourceOutput.model_validate(output)
        bundle = actual.bundle
    except (ValidationError, ValueError) as exc:
        return {
            "schema.output": _check(False, "Return one valid source bundle.", str(exc))
        }
    results = {
        "schema.stage": _check(
            getattr(actual, inputs.stage) is bundle,
            "Return the requested source kind.",
            type(bundle).__name__,
        )
    }
    if (
        not results["schema.stage"].value
        or actual.schema_version != 1
        or bundle.schema_version != 1
    ):
        results["schema.output"] = _check(
            False, "Use supported output versions and the selected source kind.", actual
        )
        return results
    data = actual.model_dump(mode="json")
    for i, rule in enumerate(expected.fields):
        try:
            values = _values(data, rule.field.split("."))
            value = values if "*" in rule.field.split(".") else values[0]
            if rule.operator == "equals":
                passed = value == rule.value
            elif rule.operator == "set_equals":
                passed = (
                    isinstance(value, list)
                    and len(value) == len(rule.value)
                    and set(value) == set(rule.value)
                )
            elif rule.operator == "count":
                passed = isinstance(value, (list, dict)) and len(value) == rule.value
            else:
                text = (
                    value
                    if isinstance(value, str)
                    else " ".join(value)
                    if isinstance(value, list)
                    and all(isinstance(v, str) for v in value)
                    else ""
                )
                passed = str(rule.value).casefold() in text.casefold()
        except (KeyError, TypeError):
            value, passed = "Missing field or wrong shape.", False
        results[f"field.{rule.field}[{i}]"] = _check(
            passed,
            f"{rule.requirement} Expected {rule.operator}: {rule.value!r}.",
            value,
        )
    source_records = {s.source_id: s for s in inputs.request.source_snapshots}
    if inputs.video_result and inputs.video_result.bundle:
        source_records.update(
            {s.source_id: s for s in inputs.video_result.bundle.source_references}
        )
    if inputs.community_result and inputs.community_result.bundle:
        source_records.update(
            {s.source_id: s for s in inputs.community_result.bundle.source_references}
        )
    source_records.update(
        {
            f.source_reference.source_id: f.source_reference
            for f in (*inputs.amazon_facts, *inputs.ikea_facts)
        }
    )
    for ref in bundle.source_references:
        original = source_records.get(ref.source_id)

        def neutral(url: str) -> tuple[str, str, str | None]:
            parsed = urlsplit(url)
            return (
                (parsed.hostname or "").removeprefix("www."),
                parsed.path,
                parse_qs(parsed.query).get("v", [None])[0],
            )

        results[f"sources.{ref.source_id}.identity"] = _check(
            original is not None
            and neutral(str(ref.url)) == neutral(str(original.url)),
            "Retain the recorded source identity and page path.",
            str(ref.url),
        )
        parsed = urlsplit(str(ref.url))
        results[f"sources.{ref.source_id}.neutral"] = _check(
            (
                not parsed.query
                or (
                    parsed.hostname in {"youtube.com", "www.youtube.com"}
                    and set(parse_qs(parsed.query)) == {"v"}
                )
            )
            and not parsed.fragment
            and not parsed.username,
            "Source URLs must stay neutral.",
            str(ref.url),
        )
    products = {p.product_id for p in inputs.request.products}
    listings = {v.listing_id for v in inputs.request.listings}
    for i, e in enumerate(bundle.evidence):
        results[f"evidence.{i}.target"] = _check(
            (not e.target.product_id or e.target.product_id in products)
            and (not e.target.listing_id or e.target.listing_id in listings),
            "Do not transfer evidence to an unknown candidate/offer.",
            e.target,
        )

    if inputs.stage == "youtube" and isinstance(bundle, VideoReviewEvidenceBundle):
        recordings = {r.video.video_id: r for r in inputs.transcripts}
        for video in bundle.videos:
            record = recordings.get(video.video_id)
            original_video = next(
                (
                    s.video
                    for s in inputs.request.source_snapshots
                    if s.video and s.video.video_id == video.video_id
                ),
                None,
            )
            original_video = original_video or (
                next(
                    (
                        v
                        for v in inputs.video_result.bundle.videos
                        if v.video_id == video.video_id
                    ),
                    None,
                )
                if inputs.video_result and inputs.video_result.bundle
                else None
            )
            if record:
                # Timeout faults happen before any tool read. The unread
                # provider cassette is not knowledge available to the agent.
                availability = (
                    original_video.transcript_availability
                    if inputs.model_fault == "timeout" and original_video
                    else record.availability
                )
                results[f"youtube.{video.video_id}.availability"] = _check(
                    video.transcript_availability == availability,
                    "Preserve observed availability; do not infer unread transcript access after timeout.",
                    video.transcript_availability,
                )
            if original_video:
                results[f"youtube.{video.video_id}.channel"] = _check(
                    video.channel_name == original_video.channel_name
                    and video.published_at == original_video.published_at,
                    "Retain channel and publication context.",
                    video,
                )
            text = (
                " ".join(
                    (
                        original_video.description or "" if original_video else "",
                        *(s.text or "" for s in record.segments if record),
                    )
                )
                if record
                else (original_video.description or "" if original_video else "")
            )
            if re.search(r"\b(sponsored|paid promotion)\b", text, re.I):
                results[f"youtube.{video.video_id}.bias"] = _check(
                    video.sponsorship_disclosed is True
                    and video.affiliate_bias_risk is not None
                    and video.affiliate_bias_risk.score >= 0.5,
                    "Visible sponsorship requires a retained bias caution.",
                    video,
                )
        for i, e in enumerate(bundle.evidence):
            record = recordings.get(e.video_id)
            segments = {s.segment_id: s for s in record.segments} if record else {}
            if e.metadata_only:
                results[f"youtube.evidence.{i}.metadata"] = _check(
                    e.target.target_type == "source_metadata"
                    and not e.timestamp_references
                    and not e.transcript_segment_ids
                    and bool(e.transcript_gap or bundle.transcript_gap_notes),
                    "Metadata-only sources cannot become timestamped product claims; retain the gap.",
                    e,
                )
            else:
                cited = [segments[s] for s in e.transcript_segment_ids if s in segments]
                results[f"youtube.evidence.{i}.quote"] = _check(
                    bool(cited)
                    and len(cited) == len(e.transcript_segment_ids)
                    and any(
                        " ".join(e.claim.split()) in " ".join((s.text or "").split())
                        for s in cited
                    ),
                    "Every video claim needs an exact permitted transcript quote.",
                    e.claim,
                )
                results[f"youtube.evidence.{i}.timestamp"] = _check(
                    [(t.start_seconds, t.end_seconds) for t in e.timestamp_references]
                    == [(s.start_seconds, s.end_seconds) for s in cited],
                    "Preserve exact segment timestamps.",
                    e.timestamp_references,
                )
                results[f"youtube.evidence.{i}.source"] = _check(
                    any(
                        r.source_id == e.source_id
                        and str(r.url)
                        == str(
                            next(
                                v for v in bundle.videos if v.video_id == e.video_id
                            ).url
                        )
                        for r in bundle.source_references
                    ),
                    "Bind the quote to its own video source.",
                    e.source_id,
                )
    if inputs.stage == "reddit":
        original = (
            {d.source_id: d for d in inputs.community_result.bundle.discussions}
            if inputs.community_result and inputs.community_result.bundle
            else {}
        )
        for d in bundle.discussions:
            before = original.get(d.source_id)
            results[f"reddit.context.{d.source_id}"] = _check(
                before == d,
                "Retain thread/comment, recency, engagement and public excerpt context.",
                d,
            )
        for i, e in enumerate(bundle.evidence):
            warnings = " ".join(
                (e.claim, e.confidence.rationale, *e.evidence_quality_warnings)
            ).casefold()
            results[f"reddit.evidence.{i}.qualitative"] = _check(
                e.qualitative_signal
                and ("qualitative" in warnings or "anecdotal" in warnings)
                and (
                    "authoritative" in warnings or "do not use reddit alone" in warnings
                )
                and e.confidence.score < 0.85,
                "Community reports remain attributed qualitative signals.",
                e,
            )
            results[f"reddit.evidence.{i}.recurrence"] = _check(
                not e.recurring_signal or len(set(e.context_source_ids)) >= 2,
                "Recurrence requires multiple distinct source contexts.",
                e.context_source_ids,
            )
            for quote in e.supporting_quotes:
                context = original.get(quote.source_id)
                results[f"reddit.evidence.{i}.quote.{quote.source_id}"] = _check(
                    context is not None
                    and quote.quote in (context.extracted_public_summary or ""),
                    "Supporting community quotes must exist in public recorded content.",
                    quote.quote,
                )
    if inputs.stage == "amazon":
        facts = {f.source_reference.source_id: f for f in inputs.amazon_facts}
        for c in bundle.listing_contexts:
            before = facts.get(c.source_id)
            results[f"amazon.context.{c.source_id}"] = _check(
                before is not None and c == before.listing_context,
                "Keep marketplace/ASIN/variant/seller/fulfillment/review totals and unknown shipping distinct.",
                c,
            )
        for source_id, fact in facts.items():
            selected = [e for e in bundle.evidence if e.source_id == source_id]
            if not selected:
                continue  # Mismatch/failed interpretation can return an explicit gap.
            if (
                fact.listing_context.seller_name
                and "amazon" not in fact.listing_context.seller_name.casefold()
            ):
                results[f"amazon.{source_id}.seller_risk"] = _check(
                    any(
                        e.fact_type == "marketplace_warning" and "separately" in e.claim
                        for e in selected
                    ),
                    "Third-party seller trust warnings cannot be dropped by the model.",
                    [e.claim for e in selected],
                )
            if fact.review_summary_claim:
                results[f"amazon.{source_id}.review_provenance"] = _check(
                    any(
                        e.fact_type == "review_quality_warning"
                        and "not independently" in e.claim
                        for e in selected
                    ),
                    "Marketplace reviews need authentication/variant caveats.",
                    [e.claim for e in selected],
                )
    if inputs.stage == "ikea":
        facts = {f.source_reference.source_id: f for f in inputs.ikea_facts}
        for c in bundle.store_contexts:
            before = facts.get(c.source_id)
            if before:
                results[f"ikea.context.{c.source_id}"] = _check(
                    c.country_code == before.store_context.country_code
                    and c.price == before.store_context.price
                    and c.availability == before.store_context.availability,
                    "Preserve official regional price/currency and stock status.",
                    c,
                )
            results[f"ikea.{c.source_id}.region"] = _check(
                c.country_code == inputs.request.target_region_code,
                "Another country's store is not local availability evidence.",
                c.country_code,
            )
        for i, e in enumerate(bundle.evidence):
            results[f"ikea.evidence.{i}.scope"] = _check(
                "shipping elsewhere" in " ".join(e.evidence_quality_warnings)
                and (
                    e.target.target_type != "region"
                    or e.target.region_code == inputs.request.target_region_code
                ),
                "IKEA facts remain scoped to the official country/region.",
                e,
            )

    if inputs.recommendation_claim:
        evidence = {
            e.evidence_id: e for e in (*bundle.evidence, *inputs.offer_evidence)
        }
        results["downstream.outputs"] = _check(
            actual.analysis is not None
            and actual.recommendation is not None
            and actual.verification is not None,
            "Run analyst, decision and verifier against actual source evidence.",
            actual,
        )
        if actual.analysis and actual.recommendation:
            for label, cited in (
                ("analysis", actual.analysis.evidence_ids),
                ("recommendation", actual.recommendation.evidence_ids),
            ):
                results[f"downstream.{label}.citations"] = _check(
                    bool(
                        set(cited).intersection(e.evidence_id for e in bundle.evidence)
                    )
                    and set(cited).issubset(evidence),
                    "Source-derived evidence must reach downstream citations without invented IDs.",
                    cited,
                )
            if actual.recommendation.final_product_id:
                results["downstream.product_basis"] = _check(
                    any(
                        e.target.product_id == actual.recommendation.final_product_id
                        or e.target.listing_id == actual.recommendation.final_listing_id
                        for e in bundle.evidence
                    ),
                    "A buy needs product/offer evidence, not metadata alone.",
                    actual.recommendation.final_product_id,
                )
        if actual.verification and actual.verification.approved:
            shown = shopper_text(actual.verification.recommendation_bundle)
            cited = {
                i
                for m in actual.verification.recommendation_bundle.mode_results
                for i in m.evidence_ids
            }
            claims = " ".join(
                evidence[i].claim for i in cited if i in evidence
            ).casefold()
            specs = re.findall(
                r"\b(?:\d+(?:\.\d+)?\s?(?:hz|mah|gb|tb|nits|inches|inch|w)|oled|4k|8k)\b",
                shown,
                re.I,
            )
            results["downstream.supported_claims"] = _check(
                all(s.casefold() in claims for s in specs),
                "Approved shopper specifications must exist in cited source facts.",
                specs,
            )
            results["downstream.approval"] = _check(
                not actual.verification.blocking_issues,
                "An approved result cannot hide blocking issues.",
                actual.verification.blocking_issues,
            )
    return results


@dataclass
class SourceIntelligenceEvaluator(Evaluator[SourceFixture, SourceResult, EvalMetadata]):
    def evaluate(
        self, ctx: EvaluatorContext[SourceFixture, SourceResult, EvalMetadata]
    ) -> dict[str, EvaluationReason]:
        if not isinstance(ctx.expected_output, SourceExpectation):
            return {
                "schema.expected_output": _check(
                    False,
                    "Independent expected criteria are required.",
                    ctx.expected_output,
                )
            }
        return score_source_intelligence(ctx.inputs, ctx.output, ctx.expected_output)
