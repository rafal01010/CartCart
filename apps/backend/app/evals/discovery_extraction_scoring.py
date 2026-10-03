"""Task-local assertions with explicit field and evidence/grouping failures."""

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from app.evals.discovery_extraction import (
    DiscoveryExtractionExpectation,
    DiscoveryExtractionInput,
    DiscoveryExtractionOutput,
    DiscoveryExtractionResult,
)
from app.evals.schemas import EvalMetadata


def _assertion(passed: bool, requirement: str, actual: object) -> EvaluationReason:
    return EvaluationReason(value=passed, reason=f"{requirement} Actual: {actual!r}")


def _values(value: Any, path: list[str]) -> list[Any]:
    if not path:
        return [value]
    head, *rest = path
    if head == "*" and isinstance(value, list):
        return [v for child in value for v in _values(child, rest)]
    if isinstance(value, dict) and head in value:
        return _values(value[head], rest)
    if isinstance(value, list) and head.isdecimal() and int(head) < len(value):
        return _values(value[int(head)], rest)
    raise KeyError("Missing field or wrong shape.")


def _dedupe_assertions(
    inputs: DiscoveryExtractionInput,
    output: DiscoveryExtractionOutput,
    expected: DiscoveryExtractionExpectation,
) -> dict[str, EvaluationReason]:
    results = {}
    groups = output.groups
    partition = [
        frozenset(str(listing.listing_id) for listing in g.listings) for g in groups
    ]
    wanted = [frozenset(str(i) for i in g) for g in expected.groups]
    results["dedupe.group_partition"] = _assertion(
        len(partition) == len(wanted) and set(partition) == set(wanted),
        f"Preserve the independent listing partition {wanted!r}; keep uncertain variants separate.",
        partition,
    )
    actual_listings = [listing for g in groups for listing in g.listings]
    ids = [listing.listing_id for listing in actual_listings]
    originals = {e.listing.listing_id: e.listing for e in inputs.extractions}
    results["dedupe.listing_coverage"] = _assertion(
        len(ids) == len(set(ids)) and set(ids) == set(originals),
        "Retain every distinct offer exactly once.",
        ids,
    )
    for listing in actual_listings:
        original = originals.get(listing.listing_id)
        # Only canonical identity and generated normalized keys may change.
        for name in (
            "title",
            "url",
            "seller",
            "price",
            "region_availability",
            "source_quality",
            "source_ids",
            "user_added_matches",
            "captured_at",
        ):
            actual = getattr(listing, name)
            value = getattr(original, name) if original is not None else None
            results[f"dedupe.listings.{listing.listing_id}.{name}"] = _assertion(
                original is not None and actual == value,
                f"Keep offer-specific {name}; product grouping cannot transfer another seller's context.",
                actual,
            )
    for index, group in enumerate(groups):
        results[f"dedupe.groups.{index}.identity_links"] = _assertion(
            all(
                listing.product_id == group.product.product_id
                for listing in group.listings
            )
            and set(group.product.listing_ids)
            == {listing.listing_id for listing in group.listings},
            "Group listings must reference their canonical product and its complete listing IDs.",
            group.product.listing_ids,
        )
        sources = {
            s
            for e in inputs.extractions
            if e.listing.listing_id
            in {listing.listing_id for listing in group.listings}
            for s in e.product.source_ids
        }
        results[f"dedupe.groups.{index}.source_ids"] = _assertion(
            set(group.product.source_ids) == sources,
            "Preserve the union of product identity sources.",
            group.product.source_ids,
        )
        results[f"dedupe.groups.{index}.match_evidence"] = _assertion(
            len(group.listings) <= 1 or bool(group.match_kinds),
            "Collapsed products need auditable match evidence.",
            group.match_kinds,
        )
    return results


def score_discovery_extraction(
    inputs: DiscoveryExtractionInput,
    output: object,
    expected: DiscoveryExtractionExpectation,
) -> dict[str, EvaluationReason]:
    try:
        actual = DiscoveryExtractionOutput.model_validate(output)
    except ValidationError as error:
        return {
            "schema." + ".".join(str(v) for v in item["loc"]): _assertion(
                False, item["msg"], item.get("input")
            )
            for item in error.errors()
        }
    results = {}
    data = actual.model_dump(mode="json")
    populated = (
        actual.discovery is not None,
        actual.quality is not None,
        actual.extraction is not None,
        bool(actual.groups),
    )
    results["schema.stage_output"] = _assertion(
        populated
        == tuple(
            inputs.stage == s for s in ("discovery", "quality", "extraction", "dedupe")
        ),
        "Return exactly the selected stage's output.",
        populated,
    )
    for index, rule in enumerate(expected.fields):
        key = f"field.{rule.field}[{index}]"
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
                passed = (
                    isinstance(value, str)
                    and str(rule.value).casefold() in value.casefold()
                )
        except (KeyError, TypeError):
            value, passed = "Missing field or wrong shape.", False
        results[key] = _assertion(
            passed,
            f"{rule.requirement} Expected {rule.operator}: {rule.value!r}.",
            value,
        )
    if inputs.discovery is not None and actual.discovery is not None:
        output_discovery = actual.discovery
        originals = {r.source_id: r for r in inputs.discovery.seed_results}
        observed = {r.source_id: r for r in output_discovery.search_results}
        results["discovery.source_fidelity"] = _assertion(
            observed == originals
            and len(observed) == len(output_discovery.search_results),
            "Offline discovery must retain every supplied result, quality and source ID without inventing sources.",
            tuple(observed),
        )
        decisions = {d.source_id: d for d in output_discovery.source_decisions}
        results["discovery.source_decisions"] = _assertion(
            set(decisions) == set(originals),
            "Classify every observed source exactly once.",
            tuple(decisions),
        )
        excluded = {
            r.source_id
            for r in originals.values()
            if any(
                r.provider.raw.get(flag)
                for flag in (
                    "excluded",
                    "source_policy_excluded",
                    "excluded_by_source_policy",
                )
            )
        }
        selected = set(output_discovery.selected_source_ids)
        results["discovery.excluded_sources"] = _assertion(
            not selected & excluded,
            "Excluded proxy/reseller sources cannot enter the shortlist.",
            selected & excluded,
        )
        actionable = {
            d.source_id
            for d in output_discovery.source_decisions
            if d.next_action in {"fetch", "retain_as_evidence"}
        }
        results["discovery.action_consistency"] = _assertion(
            selected == actionable
            and all(
                d.classification != "irrelevant"
                for d in output_discovery.source_decisions
                if d.source_id in selected
            ),
            "Selected sources must match relevant fetch/evidence decisions.",
            selected,
        )
    if inputs.extraction is not None and actual.extraction is not None:
        snapshots = {
            s.source_id: s for s in inputs.extraction.request.workbench_snapshots
        }
        extracted = actual.extraction
        cited = (
            [s for p in extracted.products for s in p.source_ids]
            + [
                s
                for listing in extracted.listings
                for s in (*listing.source_ids, *listing.seller.source_ids)
            ]
            + [e.source_id for e in extracted.source_evidence]
            + [g.source_id for g in extracted.evidence_gaps]
            + [m.source_id for m in extracted.product_mentions]
        )
        results["extraction.source_ids"] = _assertion(
            set(cited).issubset(snapshots)
            and all(p.source_ids for p in extracted.products),
            "All entities, evidence, mentions and gaps must cite assigned snapshots.",
            cited,
        )
        for index, evidence in enumerate(extracted.source_evidence):
            snapshot = snapshots.get(evidence.source_id)
            results[f"extraction.evidence.{index}.source_quality"] = _assertion(
                snapshot is not None and evidence.source_quality == snapshot.quality,
                "Keep source-quality limitations attached to extracted claims.",
                evidence.source_quality,
            )
        editorial = set(inputs.extraction.request.editorial_snapshot_ids)
        results["extraction.editorial_not_offer"] = _assertion(
            all(
                not set(listing.source_ids) & editorial
                for listing in extracted.listings
            ),
            "Review/editorial pages must not become seller offers.",
            [listing.source_ids for listing in extracted.listings],
        )
    if inputs.stage == "dedupe":
        results.update(_dedupe_assertions(inputs, actual, expected))
    return results


@dataclass
class DiscoveryExtractionEvaluator(
    Evaluator[DiscoveryExtractionInput, DiscoveryExtractionResult, EvalMetadata]
):
    def evaluate(
        self,
        ctx: EvaluatorContext[
            DiscoveryExtractionInput, DiscoveryExtractionResult, EvalMetadata
        ],
    ) -> dict[str, EvaluationReason]:
        if not isinstance(ctx.expected_output, DiscoveryExtractionExpectation):
            return {
                "schema.expected_output": _assertion(
                    False, "Independent expectations are required.", ctx.expected_output
                )
            }
        return score_discovery_extraction(ctx.inputs, ctx.output, ctx.expected_output)
