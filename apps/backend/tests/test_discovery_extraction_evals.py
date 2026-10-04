"""Cheap corpus/scorer/adapter tests; never execute a scored Dataset."""

import copy
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from agents import Runner
from pydantic_evals import Dataset

from app.agents.contracts import (
    DiscoveryAgentOutput,
    DiscoverySourceDecision,
)
from app.evals.discovery_extraction import (
    CORPUS_PATH,
    DiscoveryExtractionExpectation,
    DiscoveryExtractionOutput,
    FixtureSnapshotTools,
    ProductGroup,
    discovery_extraction_cases,
    discovery_extraction_dataset,
    offline_discovery_extraction_task,
)
from app.evals.discovery_extraction_scoring import (
    DiscoveryExtractionEvaluator,
    score_discovery_extraction,
)
from app.tools import run_evals


def named(name):
    return next(c for c in discovery_extraction_cases() if c.name == name)


def failures(case, output):
    return {
        key: result
        for key, result in score_discovery_extraction(
            case.inputs, output, case.expected_output
        ).items()
        if not result.value
    }


def source_output(case):
    source = case.inputs.discovery
    assert source is not None
    actions = [
        ("professional_review", "retain_as_evidence"),
        ("retailer_listing", "fetch"),
        ("irrelevant", "ignore"),
        ("irrelevant", "ignore"),
    ]
    return DiscoveryExtractionOutput(
        discovery=DiscoveryAgentOutput(
            search_results=tuple(r.model_copy(deep=True) for r in source.seed_results),
            selected_source_ids=tuple(r.source_id for r in source.seed_results[:2]),
            source_decisions=tuple(
                DiscoverySourceDecision(
                    source_id=r.source_id,
                    classification=kind,
                    next_action=action,
                    confidence=0.8,
                    reasons=("Independent test classification.",),
                    intended_treatment="Inspect relevant sources.",
                )
                for r, (kind, action) in zip(source.seed_results, actions, strict=True)
            ),
            outcome="selected",
        )
    )


def extraction_output(case):
    assert case.inputs.extraction is not None
    assert case.inputs.extraction.model_output is not None
    return DiscoveryExtractionOutput(
        extraction=case.inputs.extraction.model_output.model_copy(deep=True)
    )


def grouped_output(case):
    a, b = case.inputs.extractions
    # Independently construct a valid group; do not invoke the evaluated deduper.
    product = a.product.model_copy(
        update={
            "listing_ids": (a.listing.listing_id, b.listing.listing_id),
            "source_ids": (*a.product.source_ids, *b.product.source_ids),
        }
    )
    return DiscoveryExtractionOutput(
        groups=(
            ProductGroup(
                product=product,
                listings=(
                    a.listing,
                    b.listing.model_copy(update={"product_id": product.product_id}),
                ),
                match_kinds=("brand_model",),
            ),
        )
    )


def test_corpus_loads_without_execution_and_has_documented_coverage(monkeypatch):
    def reject(*args, **kwargs):
        pytest.fail("Corpus loading must not execute a Dataset or SDK runner.")

    monkeypatch.setattr(Dataset, "evaluate_sync", reject)
    monkeypatch.setattr(Runner, "run", reject)
    dataset = discovery_extraction_dataset()
    cases = discovery_extraction_cases()
    assert len(cases) == 21
    assert Counter(c.inputs.stage for c in cases) == {
        "discovery": 3,
        "quality": 5,
        "extraction": 7,
        "dedupe": 6,
    }
    assert len(dataset.evaluators) == 1
    assert isinstance(dataset.evaluators[0], DiscoveryExtractionEvaluator)
    docs = (Path(__file__).resolve().parents[3] / "docs/EVALUATION.md").read_text()
    assert all(c.name in docs for c in cases)
    assert all(c.expected_output.fields for c in cases)


def test_fresh_inputs_and_expectations_are_independent():
    case = named("extraction/cited-product-and-offer")
    original = case.expected_output.model_dump()
    case.inputs.extraction.model_output.listings[0].price.amount = "99999"
    assert case.expected_output.model_dump() == original
    assert (
        named(case.name).inputs.extraction.model_output.listings[0].price.amount
        == 15000
    )


@pytest.mark.parametrize(
    "damage",
    [
        "version",
        "nested_version",
        "duplicate_names",
        "wrong_stage",
        "duplicate_sources",
        "missing_id",
        "missing_timestamp",
        "wrong_snapshots",
        "wrong_root",
        "empty_fields",
        "bad_operand",
        "missing_group",
        "duplicate_group",
        "duplicate_rule",
    ],
)
def test_invalid_corpus_fails_closed(tmp_path, damage):
    raw = json.loads(CORPUS_PATH.read_text())
    case = raw["cases"][0]
    semantic = next(
        c for c in raw["cases"] if c["name"] == "extraction/cited-product-and-offer"
    )
    dedupe = next(
        c for c in raw["cases"] if c["name"] == "dedupe/same-model-distinct-offers"
    )
    if damage == "version":
        raw["schema_version"] = 2
    elif damage == "nested_version":
        semantic["inputs"]["extraction"]["request"]["workbench_snapshots"][0][
            "schema_version"
        ] = 2
    elif damage == "duplicate_names":
        raw["cases"][1]["name"] = case["name"]
    elif damage == "wrong_stage":
        case["inputs"]["stage"] = "quality"
    elif damage == "duplicate_sources":
        case["inputs"]["discovery"]["seed_results"].append(
            copy.deepcopy(case["inputs"]["discovery"]["seed_results"][0])
        )
    elif damage == "missing_id":
        semantic["inputs"]["extraction"]["model_output"]["products"][0].pop(
            "product_id"
        )
    elif damage == "missing_timestamp":
        semantic["inputs"]["extraction"]["request"]["workbench_snapshots"][0].pop(
            "captured_at"
        )
    elif damage == "wrong_snapshots":
        semantic["inputs"]["extraction"]["request"]["snapshot_ids"] = [
            "00000000-0000-4000-8000-000000000000"
        ]
    elif damage == "wrong_root":
        case["expected_output"]["fields"][0]["field"] = "quality.excluded"
    elif damage == "empty_fields":
        case["expected_output"]["fields"] = []
    elif damage == "bad_operand":
        case["expected_output"]["fields"][0]["value"] = "not a list"
    elif damage == "missing_group":
        dedupe["expected_output"]["groups"] = []
    elif damage == "duplicate_group":
        dedupe["expected_output"]["groups"].append(
            dedupe["expected_output"]["groups"][0]
        )
    elif damage == "duplicate_rule":
        case["expected_output"]["fields"].append(case["expected_output"]["fields"][0])
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        discovery_extraction_cases(path)


def test_manual_valid_discovery_and_extraction_and_group_output_pass_assertions():
    for name, make in [
        ("discovery/generic-shortlist", source_output),
        ("extraction/cited-product-and-offer", extraction_output),
        ("extraction/review-without-store-offer", extraction_output),
        ("extraction/collection-item-fidelity", extraction_output),
        ("dedupe/same-model-distinct-offers", grouped_output),
    ]:
        case = named(name)
        assert not failures(case, make(case))


@pytest.mark.asyncio
async def test_editorial_extraction_keeps_exact_quote_and_rejects_invented_punctuation(
    monkeypatch,
):
    import httpx
    import socket

    monkeypatch.setattr(Runner, "run", lambda *a, **kw: pytest.fail("No SDK calls."))
    monkeypatch.setattr(
        Dataset, "evaluate", lambda *a, **kw: pytest.fail("No Dataset runs.")
    )
    monkeypatch.setattr(
        Dataset, "evaluate_sync", lambda *a, **kw: pytest.fail("No Dataset runs.")
    )
    monkeypatch.setattr(
        httpx.AsyncClient, "request", lambda *a, **kw: pytest.fail("No network.")
    )
    monkeypatch.setattr(
        httpx.Client, "request", lambda *a, **kw: pytest.fail("No network.")
    )
    monkeypatch.setattr(
        socket.socket, "connect", lambda *a, **kw: pytest.fail("No network.")
    )
    case = named("extraction/review-without-store-offer")
    before = case.inputs.model_dump(mode="json")
    task = offline_discovery_extraction_task()
    output = await task(case.inputs)
    assert not failures(case, output)
    assert case.inputs.model_dump(mode="json") == before
    extraction = output.extraction
    assert extraction.products[0].name == "Harbor M27 Monitor"
    assert extraction.listings == ()
    evidence = extraction.source_evidence[0]
    assert evidence.claim == "Sharp 1440p text;"
    assert evidence.source_quality.level.value == "weak"
    assert evidence.source_id == case.inputs.extraction.request.snapshot_ids[0]
    assert (
        evidence.evidence_id
        == case.inputs.extraction.model_output.source_evidence[0].evidence_id
    )
    assert extraction.evidence_gaps[0].summary == "Stand adjustment not tested."
    invalid = case.inputs.model_copy(deep=True)
    invalid.extraction.model_output.source_evidence[0].claim = "Sharp 1440p text."
    rejected = await task(invalid)
    assert rejected.extraction.products == ()
    assert rejected.extraction.source_evidence == ()
    assert (
        rejected.extraction.evidence_gaps[0].summary
        == "Agent extraction was invalid or timed out."
    )
    assert "field.extraction.products[0]" in failures(case, rejected)


@pytest.mark.parametrize(
    "damage, key",
    [
        ("missing_listing", "field.discovery.selected_source_ids"),
        ("excluded", "discovery.excluded_sources"),
        ("lost_quality", "discovery.source_fidelity"),
        ("missing_decision", "discovery.source_decisions"),
        ("review_as_offer", "field.discovery.source_decisions.0.classification"),
    ],
)
def test_shortlist_regressions_have_specific_failures(damage, key):
    case = named("discovery/generic-shortlist")
    out = source_output(case)
    d = out.discovery
    if damage == "missing_listing":
        d.selected_source_ids = d.selected_source_ids[:1]
    elif damage == "excluded":
        d.selected_source_ids = (*d.selected_source_ids, d.search_results[2].source_id)
    elif damage == "lost_quality":
        d.search_results[0].quality.level = "strong"
    elif damage == "missing_decision":
        d.source_decisions = d.source_decisions[:-1]
    else:
        d.source_decisions[0].classification = "retailer_listing"
    failed = failures(case, out)
    assert any(k.startswith(key) for k in failed)
    assert all("Actual:" in result.reason for result in failed.values())


@pytest.mark.parametrize(
    "damage, key",
    [
        ("price", "field.extraction.listings.0.price.amount"),
        ("seller", "field.extraction.listings.0.seller.seller_name"),
        ("claim", "field.extraction.source_evidence.0.claim"),
        ("quality", "extraction.evidence.0.source_quality"),
        ("citation", "extraction.source_ids"),
        ("available", "field.extraction.listings.0.region_availability.0.status"),
    ],
)
def test_extraction_fidelity_regressions_fail(damage, key):
    case = named("extraction/cited-product-and-offer")
    out = extraction_output(case)
    e = out.extraction
    if damage == "price":
        e.listings[0].price.amount = "99999"
    elif damage == "seller":
        e.listings[0].seller.seller_name = "Another Seller"
    elif damage == "claim":
        e.source_evidence[0].claim = "Invented 4K resolution."
    elif damage == "quality":
        e.source_evidence[0].source_quality.level = "strong"
    elif damage == "citation":
        e.source_evidence[0].source_id = "00000000-0000-4000-8000-000000000000"
    else:
        e.listings[0].region_availability[0].status = "out_of_stock"
    assert any(k.startswith(key) for k in failures(case, out))


def test_collection_item_price_swap_and_wrong_url_fail():
    case = named("extraction/collection-item-fidelity")
    out = extraction_output(case)
    e = out.extraction
    e.listings[0].price.amount, e.listings[1].price.amount = (
        e.listings[1].price.amount,
        e.listings[0].price.amount,
    )
    e.listings[0].url = case.inputs.extraction.request.workbench_snapshots[0].url
    failed = failures(case, out)
    assert any(k.startswith("field.extraction.listings.0.price.amount") for k in failed)
    assert any(k.startswith("field.extraction.listings.*.url") for k in failed)


@pytest.mark.parametrize(
    "field",
    ["price", "seller", "region_availability", "source_quality", "source_ids", "url"],
)
def test_dedupe_cannot_transfer_offer_context(field):
    case = named("dedupe/same-model-distinct-offers")
    out = grouped_output(case)
    a, b = out.groups[0].listings
    setattr(b, field, copy.deepcopy(getattr(a, field)))
    assert f"dedupe.listings.{b.listing_id}.{field}" in failures(case, out)


def test_uncertain_duplicates_cannot_be_collapsed():
    case = named("dedupe/uncertain-missing-specs")
    out = grouped_output(case)
    failed = failures(case, out)
    assert "dedupe.group_partition" in failed
    assert any(k.startswith("field.fuzzy_decisions.*.outcome") for k in failed)


def test_lost_listing_and_identity_links_fail():
    case = named("dedupe/same-model-distinct-offers")
    out = grouped_output(case)
    out.groups[0].listings = out.groups[0].listings[:1]
    failed = failures(case, out)
    assert "dedupe.listing_coverage" in failed
    assert "dedupe.groups.0.identity_links" in failed


def test_schema_and_missing_fields_fail_explicitly():
    case = named("extraction/cited-product-and-offer")
    assert any(
        k.startswith("schema.")
        for k in failures(case, {"extraction": {"products": [{"name": ""}]}})
    )
    raw = case.expected_output.model_dump()
    raw["fields"][0]["field"] = "extraction.nonexistent"
    expected = DiscoveryExtractionExpectation.model_validate(raw)
    result = score_discovery_extraction(case.inputs, extraction_output(case), expected)
    assert not result["field.extraction.nonexistent[0]"].value


@pytest.mark.parametrize(
    "name",
    [
        "discovery/generic-shortlist",
        "quality/misleading-domain",
        "extraction/normalized-offer",
        "extraction/cited-product-and-offer",
        "extraction/unreadable-page-gap",
        "dedupe/same-model-distinct-offers",
        "dedupe/uncertain-missing-specs",
    ],
)
@pytest.mark.asyncio
async def test_offline_adapter_branches_use_production_contracts_without_network(
    monkeypatch, name
):
    calls = []

    def reject(*args, **kwargs):
        calls.append(True)
        raise AssertionError("No network/model execution authorized.")

    monkeypatch.setattr(Runner, "run", reject)
    monkeypatch.setattr("socket.socket.connect", reject)
    monkeypatch.setenv("CARTCART_LIVE_AGENTS_ENABLED", "true")
    monkeypatch.setenv("CARTCART_OPENAI_AGENT_TRACING_ENABLED", "true")
    case = named(name)
    before = case.inputs.model_dump(mode="json")
    task = offline_discovery_extraction_task()
    assert not task.settings.live_agents_enabled
    assert not task.settings.openai_agent_tracing_enabled
    assert task.settings.openai_api_key is None
    output = await task(case.inputs)
    assert isinstance(output, DiscoveryExtractionOutput)
    assert output.model_dump(mode="json")
    assert not calls  # Broad fallback cannot conceal a forbidden call attempt.
    assert case.inputs.model_dump(mode="json") == before
    if case.inputs.stage == "discovery":
        assert (
            task.discovery.model_runner.calls == 1
            and output.discovery.selected_source_ids
        )
    elif case.inputs.stage == "quality":
        assert output.quality.source_class == "unknown"
    elif name == "extraction/unreadable-page-gap":
        assert output.extraction.evidence_gaps and not output.extraction.products
    elif case.inputs.stage == "extraction":
        assert output.extraction.products and output.extraction.listings
    elif name == "dedupe/uncertain-missing-specs":
        assert (
            len(output.groups) == 2 and output.fuzzy_decisions[0].outcome == "uncertain"
        )
    else:
        assert len(output.groups) == 1 and len(output.groups[0].listings) == 2


@pytest.mark.asyncio
async def test_snapshot_fixture_read_is_bounded_and_has_no_fallback():
    request = named("extraction/cited-product-and-offer").inputs.extraction.request
    tools = FixtureSnapshotTools(request)
    assert (await tools.read("invalid-id")).status == "invalid_request"
    assert (await tools.read("00000000-0000-4000-8000-000000000000")).status == "gap"
    assert (await tools.read(str(request.snapshot_ids[0]))).text
    for _ in range(23):
        assert (await tools.read(str(request.snapshot_ids[0]))).status == "succeeded"
    assert (await tools.read(str(request.snapshot_ids[0]))).status == "gap"


@pytest.mark.parametrize("passed", [True, False])
def test_cli_selects_only_scoped_dataset_without_execution(
    monkeypatch, tmp_path, passed
):
    seen = []

    def fake_run(dataset, task, output_dir):
        seen.append((dataset.name, task, output_dir))
        return tmp_path / "stub-report.json", passed

    monkeypatch.setattr(run_evals, "run_local_evaluation", fake_run)
    result = run_evals.main(
        ["--suite", "discovery-extraction", "--output-dir", str(tmp_path)]
    )
    assert result == (0 if passed else 1)
    assert seen[0][0] == "cartcart-discovery-extraction"
    assert not (tmp_path / "stub-report.json").exists()


def test_evaluator_exposes_failed_assertions():
    case = named("extraction/cited-product-and-offer")
    out = extraction_output(case)
    out.extraction.listings[0].price.amount = "99999"
    result = DiscoveryExtractionEvaluator().evaluate(
        SimpleNamespace(
            inputs=case.inputs, output=out, expected_output=case.expected_output
        )
    )
    assert any(not v.value for v in result.values())


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_class", "unknown"),
        ("quality.level", "weak"),
        ("normalized_url", "https://impostor.example/monitor"),
    ],
)
def test_source_quality_regressions_fail_named_fields(field, value):
    from app.providers.source_quality import SourceQualityAssessment

    case = named("quality/official-manufacturer")
    out = DiscoveryExtractionOutput(
        quality=SourceQualityAssessment(
            normalized_url="https://samsung.com/us/monitor",
            normalized_domain="samsung.com",
            source_class="official_manufacturer",
            quality={"level": "strong", "score": 0.95},
            excluded=False,
            requires_trust_assessment=False,
            region_relevance="match",
            region_relevance_score=1,
            reasons=("Independent official own-product specification fixture.",),
        )
    )
    assert not failures(case, out)
    if field == "quality.level":
        out.quality.quality.level = value
    else:
        setattr(out.quality, field, value)
    assert any(k.startswith("field.quality." + field) for k in failures(case, out))


def test_excluded_source_and_regional_availability_regressions_fail():
    from app.providers.source_quality import SourceQualityAssessment

    excluded = named("quality/excluded-proxy")
    out = DiscoveryExtractionOutput(
        quality=SourceQualityAssessment(
            normalized_url="https://zenmarket.jp/product/fixture",
            normalized_domain="zenmarket.jp",
            source_class="reseller_import_proxy",
            quality={"level": "weak"},
            excluded=False,
            requires_trust_assessment=True,
            region_relevance="match",
            region_relevance_score=1,
            reasons=("Independent proxy-source fixture.",),
        )
    )
    assert any(k.startswith("field.quality.excluded") for k in failures(excluded, out))
    regional = named("quality/retailer-region-mismatch")
    out.quality.source_class = "established_retailer_mixed"
    assert any(
        k.startswith("field.quality.region_relevance") for k in failures(regional, out)
    )


@pytest.mark.asyncio
async def test_empty_page_never_starts_even_the_mock_model(monkeypatch):
    from app.agents.live_extraction import MockExtractionModelRunner

    def reject(*args, **kwargs):
        pytest.fail("Unreadable source must return a gap before running a model.")

    monkeypatch.setattr(MockExtractionModelRunner, "run", reject)
    case = named("extraction/unreadable-page-gap")
    out = await offline_discovery_extraction_task()(case.inputs)
    assert out.extraction.evidence_gaps


@pytest.mark.asyncio
async def test_invalid_recorded_price_falls_back_and_still_fails_acceptance():
    case = named("extraction/cited-product-and-offer")
    case.inputs.extraction.model_output.listings[0].price.amount = "99999"
    out = await offline_discovery_extraction_task()(case.inputs)
    assert not out.extraction.listings
    assert out.extraction.evidence_gaps
    assert any(
        k.startswith("field.extraction.listings.0.price.amount")
        for k in failures(case, out)
    )


def test_punctuated_price_case_rejects_a_swallowed_offer():
    from app.agents.contracts import ExtractionAgentOutput

    case = named("extraction/punctuated-price-fidelity")
    # A backend fallback is valid schema, but it does not satisfy fidelity.
    out = DiscoveryExtractionOutput(
        extraction=ExtractionAgentOutput(
            evidence_gaps=(
                {
                    "source_id": case.inputs.extraction.request.snapshot_ids[0],
                    "summary": "Agent extraction was invalid or timed out.",
                },
            ),
        )
    )
    assert any(
        k.startswith("field.extraction.listings.0.price.amount")
        for k in failures(case, out)
    )
