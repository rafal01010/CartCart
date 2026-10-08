import importlib
import json
from dataclasses import replace

import pytest
from agents import Agent, RunConfig
from pydantic import AnyHttpUrl

from app.agents.catalog import DEFAULT_AGENT_CATALOG
from app.agents.context_management import BoundedRunner, ContextBudget, context_scope
from app.agents.contracts import (
    ComparisonDecisionAgentInput,
    ProductAnalysisAgentInput,
    VerificationAgentInput,
)
from app.agents.ikea_regional_tools import IKEARegionalStoreTools
from app.agents.live_comparison_decision import (
    _fallback_recommendation_bundle,
    _model_input as comparison_input,
)
from app.agents.live_verifier_critic import _model_input as verifier_input
from app.agents.model_input_projection import (
    canonical_support_model_fields,
    evidence_model_fields,
    model_input_json,
    restore_evidence,
    restore_explanations,
)
from app.agents.workbench import (
    _WorkbenchIKEAStoreIntelligenceProvider,
    _build_workbench_definitions,
    _scenario_comparison_monitor_shortlist,
    _scenario_ikea_available_regional_product,
    _scenario_verifier_suspicious_rejected_offer,
)
from app.agents.contracts import IKEAStoreIntelligenceAgentInput
from app.orchestration.shopping_runs import _evidence_for_product
from app.schemas.ids import new_id
from app.schemas.products import RegionAvailability
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceType,
    SourceEvidence,
    VideoSource,
)
from test_context_decision_fidelity import (
    _ScriptModel,
    _ScriptProvider,
    _call,
    _message,
    _tool_results,
)


ANALYSTS = (
    ("TechnologyDomainAnalystAgent", "live_technology_domain_analyst"),
    ("MonitorSpecialistAgent", "live_monitor_specialist"),
    ("SmartphoneSpecialistAgent", "live_smartphone_specialist"),
    ("LaptopSpecialistAgent", "live_laptop_specialist"),
    ("EarphonesHeadphonesSpecialistAgent", "live_earphones_headphones_specialist"),
    ("TVSpecialistAgent", "live_tv_specialist"),
    ("SmartwatchSpecialistAgent", "live_smartwatch_specialist"),
)


def _comparison():
    return ComparisonDecisionAgentInput.model_validate(
        _scenario_comparison_monitor_shortlist().input
    )


def _video_evidence(evidence):
    video = VideoSource(
        video_id="offline-video",
        url="https://www.youtube.com/watch?v=offline-video",
        description="Exact description. " * 230,
        sponsorship_disclosed=True,
        bias_notes="Sponsored review. Do not treat it as independent testing.",
    )
    return tuple(
        item.model_copy(
            update={"video": video, "evidence_type": EvidenceType.VIDEO_CLAIM}
        )
        for item in evidence
    )


@pytest.mark.parametrize(("name", "module"), ANALYSTS)
def test_assigned_analyst_keeps_declared_route_without_catalog(name, module):
    definitions = _build_workbench_definitions(DEFAULT_AGENT_CATALOG)
    supplied = ProductAnalysisAgentInput.model_validate(
        definitions[name].scenarios[0].input
    )
    route = DEFAULT_AGENT_CATALOG.route_product_analysis(supplied.product.category)
    builder = importlib.import_module(f"app.agents.{module}")._model_input
    payload = json.loads(builder(supplied, DEFAULT_AGENT_CATALOG, route))
    assert "allowed_routes" not in payload
    assert payload["declared_route"] == route.model_dump(mode="json")
    assert (
        tuple(SourceEvidence.model_validate(row) for row in restore_evidence(payload))
        == supplied.evidence
    )
    assert payload["product"]["product_id"] == str(supplied.product.product_id)
    if name != "TechnologyDomainAnalystAgent":
        assert any(key.startswith("required_") for key in payload)


def test_video_metadata_is_shared_without_losing_claims_or_changed_metadata():
    request = _comparison()
    evidence = _video_evidence(request.evidence)
    original = tuple(item.model_dump(mode="json") for item in evidence)
    payload = json.loads(
        comparison_input(request.model_copy(update={"evidence": evidence}))
    )
    assert len(payload["video_metadata"]) == 1
    assert (
        payload["video_metadata"]["video_1"]["description"]
        == "Exact description. " * 230
    )
    assert payload["video_metadata"]["video_1"]["sponsorship_disclosed"] is True
    assert (
        payload["video_metadata"]["video_1"]["bias_notes"]
        == "Sponsored review. Do not treat it as independent testing."
    )
    assert (
        tuple(
            SourceEvidence.model_validate(row).model_dump(mode="json")
            for row in restore_evidence(payload)
        )
        == original
    )
    assert tuple(item.model_dump(mode="json") for item in evidence) == original
    before = len(json.dumps({"evidence": original}, sort_keys=True))
    after = len(json.dumps(evidence_model_fields(evidence), sort_keys=True))
    assert after < before * 0.55
    changed = evidence[-1].model_copy(
        update={
            "video": evidence[-1].video.model_copy(
                update={
                    "bias_notes": "Independent review, different original metadata."
                }
            )
        }
    )
    projected = evidence_model_fields((*evidence[:-1], changed))
    assert (
        projected["evidence"][-1]["video"]["bias_notes"]
        == "Independent review, different original metadata."
    )
    tiny = evidence_model_fields((request.evidence[0],))
    assert "video_metadata" not in tiny
    assert len(json.dumps(tiny)) <= len(
        json.dumps({"evidence": [request.evidence[0].model_dump(mode="json")]})
    )


def test_unmatched_product_has_gap_and_shared_caution_stays_scoped():
    request = _comparison()
    product, listing = request.products[0], request.listings[0]
    other = request.evidence[1].model_copy(update={"source_id": product.source_ids[0]})
    caution = request.evidence[0].model_copy(
        update={
            "evidence_id": new_id(),
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.SOURCE_METADATA,
                source_id=product.source_ids[0],
            ),
            "claim": "Shared seller caution. No local warranty.",
        }
    )
    assert _evidence_for_product(product, (listing,), (other,)) == ()
    selected = _evidence_for_product(
        product, (listing,), (other, caution, request.evidence[0])
    )
    assert tuple(item.claim for item in selected) == (
        "Shared seller caution. No local warranty.",
        "Dell U2724DE has QHD resolution, USB-C hub features, and ergonomic stand.",
    )
    generic = importlib.import_module("app.agents.live_generic_product_analyst")
    missing = ProductAnalysisAgentInput(
        run_id=request.run_id,
        brief=request.brief,
        product=product,
        listings=(listing,),
        evidence=(),
    )
    prompt = json.loads(generic._model_input(missing))
    assert prompt["evidence"] == []
    assert prompt["evidence_gaps"] == ["No evidence is assigned to this product."]
    analysis = generic._mock_analysis_from_model_input(generic._model_input(missing))
    assert (
        "Only limited source evidence was supplied, so confidence is low and missing claims should stay unknown."
        in analysis.warnings
    )


def test_regional_source_associations_retain_cautions_without_foreign_subjects():
    request = _comparison()
    regional_source_id = new_id()
    product = request.products[0].model_copy(update={"source_ids": ()})
    listing = request.listings[0].model_copy(
        update={
            "source_ids": (),
            "seller": request.listings[0].seller.model_copy(update={"source_ids": ()}),
            "region_availability": (
                RegionAvailability(region_code="PH", source_ids=(regional_source_id,)),
            ),
        }
    )
    regional = request.evidence[0].model_copy(
        update={
            "evidence_id": new_id(),
            "source_id": regional_source_id,
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.REGION, region_code="PH"
            ),
            "claim": "This offer does not ship to the Philippines.",
        }
    )
    metadata = regional.model_copy(
        update={
            "evidence_id": new_id(),
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.SOURCE_METADATA,
                source_id=regional_source_id,
            ),
            "claim": "Regional source is unverified. Do not assume local warranty.",
        }
    )
    foreign_product = request.evidence[1].model_copy(
        update={"source_id": regional_source_id}
    )
    foreign_listing = regional.model_copy(
        update={
            "evidence_id": new_id(),
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.LISTING,
                listing_id=request.listings[1].listing_id,
            ),
            "claim": "A different product's offer ships to the Philippines.",
        }
    )
    pool = (foreign_product, regional, metadata, foreign_listing, request.evidence[1])
    selected = _evidence_for_product(product, (listing,), pool)
    assert tuple(item.claim for item in selected) == (
        "This offer does not ship to the Philippines.",
        "Regional source is unverified. Do not assume local warranty.",
    )
    without_association = listing.model_copy(update={"region_availability": ()})
    assert _evidence_for_product(product, (without_association,), pool) == ()
    generic = importlib.import_module("app.agents.live_generic_product_analyst")
    prompt = json.loads(
        generic._model_input(
            ProductAnalysisAgentInput(
                run_id=request.run_id,
                brief=request.brief,
                product=product,
                listings=(listing,),
                evidence=selected,
            )
        )
    )
    assert [item["claim"] for item in prompt["evidence"]] == [
        "This offer does not ship to the Philippines.",
        "Regional source is unverified. Do not assume local warranty.",
    ]
    assert len(json.dumps(prompt["evidence"])) < len(
        json.dumps([item.model_dump(mode="json") for item in pool])
    )


def test_typed_support_keeps_distinct_confidence_warning_and_region():
    evidence = _comparison().evidence[0]
    typed = {
        **evidence.model_dump(mode="json"),
        "fact_type": "product_page_fact",
        "evidence_quality_warnings": ["Provider has not checked local warranty."],
    }
    context = {
        "source_id": str(evidence.source_id),
        "marketplace_domain": "amazon.com",
        "ships_to_region": False,
        "seller_name": "Third party seller",
        "variant_label": "Imported variant",
    }
    support = (
        {
            "evidence_id": str(evidence.evidence_id),
            "snapshot_id": str(evidence.source_id),
            "status": "canonical_typed_support",
            "supporting_text": evidence.claim,
            "original_records": [context, typed],
        },
    )
    original = json.dumps(support, sort_keys=True)
    fields = canonical_support_model_fields(support, (evidence,))
    descriptor = fields["canonical_support"][0]
    assert "supporting_text" not in descriptor
    assert descriptor["supporting_evidence_id"] == str(evidence.evidence_id)
    assert descriptor["original_records"][0] == context
    projected = descriptor["original_records"][1]
    assert "claim" not in projected
    assert projected["evidence_quality_warnings"] == [
        "Provider has not checked local warranty."
    ]
    assert len(json.dumps(fields)) < len(json.dumps({"canonical_support": support}))
    assert json.dumps(support, sort_keys=True) == original
    typed["confidence"] = {
        "score": 0.2,
        "level": "low",
        "rationale": "Original provider uncertainty.",
    }
    changed = canonical_support_model_fields(support, (evidence,))
    assert (
        changed["canonical_support"][0]["original_records"][1]["confidence"]["score"]
        == 0.2
    )


@pytest.mark.asyncio
async def test_real_sdk_receives_complete_comparison_and_verifier_graphs():
    request = _comparison()
    evidence = _video_evidence(request.evidence)
    request = request.model_copy(update={"evidence": evidence})
    expected = _fallback_recommendation_bundle(request)
    assert expected.final_product_id == request.products[0].product_id
    assert "At least one candidate is over the stated budget." in expected.warnings
    verification = VerificationAgentInput.model_validate(
        _scenario_verifier_suspicious_rejected_offer().input
    )
    verification = verification.model_copy(
        update={"evidence": _video_evidence(verification.evidence)}
    )

    def comparison_step(items, handoffs):
        payload = restore_explanations(json.loads(items[0]["content"]))
        assert payload["products"] == [
            product.model_dump(mode="json") for product in request.products
        ]
        assert payload["listings"] == [
            listing.model_dump(mode="json") for listing in request.listings
        ]
        assert (
            tuple(
                SourceEvidence.model_validate(row) for row in restore_evidence(payload)
            )
            == evidence
        )
        assert payload["deduplication_decisions"][0]["evidence_ids"] == [
            str(item) for item in request.deduplication_decisions[0].evidence_ids
        ]
        return _message(expected.model_dump(mode="json"))

    def verifier_step(items, handoffs):
        payload = restore_explanations(json.loads(items[0]["content"]))
        assert payload[
            "recommendation_bundle"
        ] == verification.recommendation_bundle.model_dump(mode="json")
        rejected = payload["recommendation_bundle"]["rejected_items"][0]
        assert rejected["reason"] == "Do not buy this suspicious listing."
        assert rejected["reason_code"] == "suspicious_listing"
        assert rejected["listing_id"] in {
            str(item.listing_id) for item in verification.listings
        }
        assert payload["trust_assessments"] == [
            assessment.model_dump(mode="json")
            for assessment in verification.trust_assessments
        ]
        assert (
            tuple(
                SourceEvidence.model_validate(row) for row in restore_evidence(payload)
            )
            == verification.evidence
        )
        return _message({"approved": True})

    model = _ScriptModel([comparison_step, verifier_step])
    agent = Agent(
        name="ComparisonDecisionAgent",
        model="offline",
        instructions="Compare supplied evidence.",
    )
    configuration = RunConfig(
        model_provider=_ScriptProvider({"offline": model}), tracing_disabled=True
    )
    with context_scope(ContextBudget()):
        result = await BoundedRunner.run(
            agent, comparison_input(request), run_config=configuration, max_turns=2
        )
        assert json.loads(result.final_output)["final_product_id"] == str(
            request.products[0].product_id
        )
        agent.name = "VerifierCriticAgent"
        await BoundedRunner.run(
            agent, verifier_input(verification), run_config=configuration, max_turns=2
        )
    assert len(model.inputs) == 2


@pytest.mark.asyncio
async def test_source_specific_sdk_retirement_preserves_late_caution_and_new_result():
    supplied = IKEAStoreIntelligenceAgentInput.model_validate(
        _scenario_ikea_available_regional_product().input
    )
    tools = IKEARegionalStoreTools(supplied, _WorkbenchIKEAStoreIntelligenceProvider())
    searched = await tools.search(str(supplied.products[0].product_id))
    source_id = searched["sources"][0]["source_id"]
    record = tools._records[source_id]
    original = (
        "Price PHP 90000. " + "Catalogue navigation. " * 240 + "No local warranty."
    )
    tools._records[source_id] = replace(record, text=original)
    view_ids = []

    def process_first(items, handoffs):
        result = _tool_results(items)[-1]
        assert result["text"].startswith("Price PHP 90000.")
        assert "No local warranty." not in result["text"]
        assert result["text_truncated"] is True
        assert result["unreviewed_content"] is True
        view_ids.append(result["_research_view"]["view_id"])
        return _call(
            "complete_research_result",
            {"view_id": view_ids[-1], "retained_facts": ["Price PHP 90000."]},
        )

    def read_warning(items, handoffs):
        assert "Catalogue navigation. " * 20 not in json.dumps(items)
        return _call(
            "read_ikea_product",
            {"source_id": source_id, "start_char": 0, "focus": "No local warranty."},
        )

    def process_warning(items, handoffs):
        result = _tool_results(items)[-1]
        assert "No local warranty." in result["text"]
        view_ids.append(result["_research_view"]["view_id"])
        assert view_ids[0] != view_ids[1]
        return _call(
            "complete_research_result",
            {"view_id": view_ids[-1], "retained_facts": ["No local warranty."]},
        )

    def repeat(items, handoffs):
        text = json.dumps(items)
        assert "Catalogue navigation. " * 20 not in text
        assert "No local warranty." in text
        return _call(
            "read_ikea_product",
            {"source_id": source_id, "start_char": 0, "focus": None},
        )

    def change(items, handoffs):
        assert _tool_results(items)[-1]["status"] == "processed_unchanged"
        tools._records[source_id] = replace(
            record, text="Changed offer. No local warranty. " + "New material. " * 180
        )
        return _call(
            "read_ikea_product",
            {"source_id": source_id, "start_char": 0, "focus": None},
        )

    def finish(items, handoffs):
        result = _tool_results(items)[-1]
        assert result["status"] == "ok"
        assert result["text"].startswith("Changed offer. No local warranty.")
        assert result["_research_view"]["view_id"] not in view_ids
        assert len(result["text"]) == 2000
        return _message({"decision": "Do not assume local warranty."})

    model = _ScriptModel(
        [
            _call(
                "read_ikea_product",
                {"source_id": source_id, "start_char": 0, "focus": None},
            ),
            process_first,
            read_warning,
            process_warning,
            repeat,
            change,
            finish,
        ]
    )
    agent = Agent(
        name="IKEAStoreIntelligenceAgent",
        model="offline",
        instructions="Read and interpret sources.",
        tools=list(tools.sdk_tools()),
    )
    with context_scope(ContextBudget()):
        result = await BoundedRunner.run(
            agent,
            "Check this regional offer.",
            run_config=RunConfig(
                model_provider=_ScriptProvider({"offline": model}),
                tracing_disabled=True,
            ),
            max_turns=9,
        )
    assert json.loads(result.final_output) == {
        "decision": "Do not assume local warranty."
    }
    assert record.text != original
    assert len(model.inputs) == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["amazon", "ikea"])
async def test_typed_original_support_reloads_from_same_run_and_rejects_forgery(
    provider,
):
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.agents.extraction_tools import SnapshotInterpretationTools
    from app.db.base import Base
    from app.db.repositories.search_sources import SearchSourceRepository
    from app.db.repositories.source_intelligence import SourceIntelligenceRepository
    from app.db.session import create_session_factory
    from test_source_intelligence_repository import (
        create_run,
        make_amazon_fixture,
        make_ikea_fixture,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        _, run = await create_run(factory)
        _, other_run = await create_run(factory)
        snapshot, bundle = (
            make_amazon_fixture(new_id(), new_id())
            if provider == "amazon"
            else make_ikea_fixture(new_id())
        )
        typed = bundle.evidence[0]
        canonical = SourceEvidence(
            evidence_id=typed.evidence_id,
            source_id=typed.source_id,
            target=typed.target,
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim=typed.claim,
            confidence=typed.confidence,
            source_quality=typed.source_quality,
        )
        async with factory() as session:
            repository = SearchSourceRepository(session)
            await repository.add_source_snapshot(run.run_id, snapshot)
            await repository.add_source_evidence(run.run_id, canonical)
            source_repository = SourceIntelligenceRepository(session)
            if provider == "amazon":
                await source_repository.add_amazon_product_bundle(run.run_id, bundle)
            else:
                await source_repository.add_ikea_store_bundle(run.run_id, bundle)
            await session.commit()
            tools = SnapshotInterpretationTools(
                run_id=run.run_id,
                allowed_snapshot_ids=(snapshot.source_id,),
                shared_session=session,
                agent_name="VerifierCriticAgent",
                max_text_chars=1200,
            )
            support = await tools.canonical_support((canonical,))
            assert support[0]["status"] == "canonical_typed_support"
            projected = canonical_support_model_fields(support, (canonical,))
            assert projected["canonical_support"][0]["supporting_evidence_id"] == str(
                canonical.evidence_id
            )
            read = await tools.read(
                str(snapshot.source_id), focus=str(canonical.evidence_id)
            )
            assert read.status == "succeeded"
            assert canonical.claim in read.text
            assert canonical.evidence_id in read.source_part_ids
            assert len(read.text) <= 1200
            assert read.content_sha256
            if provider == "amazon":
                assert "amazon.com" in read.text
                assert "Third Party Seller" in read.text
            else:
                assert "IKEA US" in read.text
                assert "12345678" in read.text
            forged = canonical.model_copy(
                update={"claim": "An invented ten year warranty."}
            )
            assert (await tools.canonical_support((forged,)))[0]["status"] == "gap"
            other = SnapshotInterpretationTools(
                run_id=other_run.run_id,
                allowed_snapshot_ids=(snapshot.source_id,),
                shared_session=session,
                agent_name="VerifierCriticAgent",
            )
            assert (
                await other.read(str(snapshot.source_id))
            ).status == "unknown_snapshot"
            assert (await other.canonical_support((canonical,)))[0]["status"] == "gap"
            assert (
                await repository.get_source_snapshot_for_run(
                    run.run_id, snapshot.source_id
                )
            ) == snapshot
            await repository.save_source_snapshot(
                run.run_id,
                snapshot.model_copy(
                    update={"url": AnyHttpUrl("https://example.com/unrelated-original")}
                ),
            )
            assert (await tools.canonical_support((canonical,)))[0]["status"] == "gap"
            assert (await tools.read(str(snapshot.source_id))).status == "gap"
    finally:
        await engine.dispose()


def test_long_exact_explanations_share_only_when_smaller():
    repeated = (
        "A supported judgment depends on the stated candidate and seller evidence. " * 4
    )
    distinct = "A different seller has different unresolved warranty concerns. " * 3
    original = {
        "assessments": [
            {"rationale": repeated},
            {"rationale": repeated},
            {"rationale": distinct},
        ]
    }
    projected = model_input_json(original)
    assert len(projected.encode()) < len(json.dumps(original, sort_keys=True).encode())
    assert restore_explanations(json.loads(projected)) == original
    assert json.loads(projected)["assessments"][2]["rationale"] == distinct
    tiny = {"rationale": "Evidence is limited.", "summary": "Evidence is limited."}
    assert model_input_json(tiny) == json.dumps(tiny, sort_keys=True)
    marginal = {"rationale": "x" * 80, "summary": "x" * 80}
    assert model_input_json(marginal) == json.dumps(marginal, sort_keys=True)
    comparison = _comparison()
    restored = restore_explanations(json.loads(comparison_input(comparison)))
    assert restored["trust_assessments"] == [
        item.model_dump(mode="json") for item in comparison.trust_assessments
    ]
    assert restored["category_analyses"] == [
        item.model_dump(mode="json") for item in comparison.category_analyses
    ]


@pytest.mark.asyncio
async def test_real_nested_manager_bundle_retires_after_interpretation_and_reloads():
    from app.agents.contracts import AmazonProductIntelligenceAgentInput
    from app.agents.live_source_intelligence_manager import (
        SourceIntelligenceManagerAgent,
        SourceManagerInput,
    )
    from app.agents.workbench import (
        _WorkbenchAmazonProductIntelligenceProvider,
        _scenario_amazon_third_party_seller_region_gap,
    )
    from app.core.settings import Settings
    from app.schemas.search_sources import SourceIntelligenceCapability

    supplied = AmazonProductIntelligenceAgentInput.model_validate(
        _scenario_amazon_third_party_seller_region_gap().input
    )
    product_id = str(supplied.products[0].product_id)
    views, bundles = [], []

    def child_read(items, handoffs):
        result = _tool_results(items)[-1]
        return _call(
            "read_amazon_product",
            {
                "source_id": result["sources"][0]["source_id"],
                "start_char": 0,
                "focus": None,
            },
        )

    def child_decide(items, handoffs):
        result = _tool_results(items)[-1]
        assert result["listing_context"]["seller_name"]
        assert any(
            "seller" in item["claim"].lower() for item in result["provider_evidence"]
        )
        return _message(
            {
                "selected_sources": [
                    {
                        "product_id": product_id,
                        "source_id": result["source_reference"]["source_id"],
                        "identity": "match",
                        "identity_reason": "The supplied product and provider source identify the same item.",
                        "selected_evidence_ids": [
                            item["evidence_id"] for item in result["provider_evidence"]
                        ],
                    }
                ],
                "evidence_gaps": [],
                "retained_web_urls": [],
            }
        )

    def parent_process(items, handoffs):
        result = _tool_results(items)[-1]
        assert "bundle" in result
        bundle = result["bundle"]
        bundles.append(bundle)
        views.append(result["_research_view"]["view_id"])
        return _call(
            "complete_research_result",
            {"view_id": views[0], "retained_facts": [bundle["evidence"][0]["claim"]]},
        )

    def parent_lookup(items, handoffs):
        receipt = _tool_results(items)[0]
        assert receipt["status"] == "processed"
        assert "bundle" not in receipt
        assert receipt["retained"]["cautions"]
        assert any(
            "seller" in warning.lower() for warning in receipt["retained"]["cautions"]
        )
        assert "unreviewed" in receipt["retained"]["coverage"]
        return _call(
            "read_research_result",
            {"view_id": views[0], "start_char": 0, "focus": "seller"},
        )

    def parent_finish(items, handoffs):
        result = _tool_results(items)[-1]
        assert result["status"] == "succeeded"
        assert "seller" in result["text"].lower()
        return _message(
            {
                "summary": "Provider facts retained with seller and regional caution.",
                "skipped_sources": [],
            }
        )

    model = _ScriptModel(
        [
            _call(
                "consult_amazon_product_listing_review",
                {"input": "Check this marketplace seller and region."},
            ),
            _call("search_amazon_products", {"product_id": product_id}),
            child_read,
            child_decide,
            parent_process,
            parent_lookup,
            parent_finish,
        ]
    )

    class Provider(_ScriptProvider):
        def get_model(self, model_name):
            return model

    class SDKRunner:
        async def run(self, agent, model_input, *, run_config, max_turns):
            return await BoundedRunner.run(
                agent,
                model_input,
                run_config=replace(
                    run_config, model_provider=Provider({}), tracing_disabled=True
                ),
                max_turns=max_turns,
            )

    manager = SourceIntelligenceManagerAgent(
        settings=Settings(_env_file=None, environment="test"),
        amazon_provider=_WorkbenchAmazonProductIntelligenceProvider(),
        model_runner=SDKRunner(),
    )
    request = SourceManagerInput(
        run_id=supplied.run_id,
        brief=supplied.brief,
        products=supplied.products,
        listings=supplied.listings,
        source_snapshots=supplied.source_snapshots,
        query_hints=(),
        region_code="PH",
        allowed_capabilities=(
            SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
        ),
    )
    with context_scope(ContextBudget()):
        output = await manager.run(request)
    assert bundles, (output.notes, output.activity, model.inputs)
    assert output.amazon_bundles[0]
    assert [item.claim for item in output.amazon_bundles[0].evidence] == [
        item["claim"] for item in bundles[0]["evidence"]
    ]
    assert (
        output.amazon_bundles[0].listing_contexts[0].seller_name
        == bundles[0]["listing_contexts"][0]["seller_name"]
    )
    assert len(model.inputs) == 7
