import json
from hashlib import sha256
from pathlib import Path

import pytest

from app.agents.context_metrics import measure
from app.agents.decision_sources import (
    fit_owner_projection, input_projection, project_owner_sources, source_size,
    select_decision_sources,
)
from app.schemas.decision_sources import DecisionSourcePacket
from app.schemas.ids import new_id
from app.schemas.intake import ShoppingBrief


def independent_speech(claim, source_id, video_id):
    from app.schemas.search_sources import SourceEvidence
    row = claim.model_dump(mode="json")
    row.update(evidence_id=str(new_id()), source_id=str(source_id))
    row["video"].update(video_id=video_id, url=f"https://www.youtube.com/watch?v={video_id}")
    for support in row["transcript_support"]:
        support.update(segment_id=str(new_id()), video_id=video_id)
    row["transcript_segment_ids"] = [support["segment_id"] for support in row["transcript_support"]]
    return SourceEvidence.model_validate(row)


def packet(name, text, *, candidates=(), question=(), finding=(), perspective=None, caution=()):
    return DecisionSourcePacket(source_id=new_id(), url=f"https://example.org/{name}", title=name,
        content_kind="page", excerpts=(text,), candidate_names=candidates,
        buying_questions=question, findings=finding, perspective=perspective, material_cautions=caution,
        content_sha256=sha256(text.encode()).hexdigest())


def test_selects_meaningful_overlapping_coverage_and_distinct_perspectives_without_count_ceiling():
    brief = ShoppingBrief(original_query="Phone camera and battery for travel")
    guide = packet("guide", "Aster X has longer battery, Birch Y takes better night photos.",
        candidates=("Aster X", "Birch Y"), question=("travel battery", "night camera"))
    first = packet("first", "Aster X lasts a full day.", candidates=("Aster X",), question=("battery",), finding=("full-day battery",))
    repeat = packet("repeat", "During daily use Aster X runs until bedtime.", candidates=("Aster X",), question=("battery",), finding=("full-day battery",))
    test = packet("independent-test", "Aster X lasted 14 hours on a continuous navigation test.", candidates=("Aster X",), question=("battery",), finding=("full-day battery",), perspective="continuous navigation test")
    contrary = packet("contrary", "Aster X overheats during navigation.", candidates=("Aster X",), question=("battery",), caution=("Thermal risk during navigation.",))
    many = [packet(f"useful-{i}", f"Phone variant {i} has verified travel feature {i}.", candidates=(f"Variant {i}",), question=(f"travel feature {i}",)) for i in range(16)]
    result = select_decision_sources(brief, [repeat, first, guide, test, contrary, *many])
    assert result.selected_source_ids[0] == guide.source_id
    assert contrary.source_id in result.selected_source_ids
    assert guide.source_id in result.selected_source_ids and test.source_id in result.selected_source_ids
    assert first.source_id in result.selected_source_ids and repeat.source_id in result.deferred_source_ids
    assert len(result.selected_source_ids) == 20
    assert next(row for row in result.candidate_coverage if row.candidate_name == "Birch Y").source_ids == (guide.source_id,)
    assert result.measurements["meaningful_candidate_count"] == 18


def test_same_products_never_increase_candidate_breadth_and_fit_uses_existing_budget():
    brief = ShoppingBrief(original_query="A reading lamp for evening books")
    pages = [packet(str(i), f"Aster Lamp has useful reading test {i}. " * 20, candidates=("Aster Lamp",), question=(f"test {i}",)) for i in range(20)]
    result = select_decision_sources(brief, pages)
    assert len(result.selected_source_ids) == 20
    assert result.measurements["meaningful_candidate_count"] == 1
    original = json.dumps({"brief": brief.model_dump(mode="json"), "decision_sources": result.model_dump(mode="json")})
    fitted = fit_owner_projection(original, 1800)
    revised = input_projection(fitted)
    assert measure(fitted)["estimated_tokens"] <= 1800
    assert len(revised.selected_source_ids) < 20
    assert set(revised.selected_source_ids) | set(revised.deferred_source_ids) == {page.source_id for page in pages}
    assert input_projection(original) == result


def test_normal_projection_retires_duplicate_tool_bodies_and_preserves_exact_brief():
    brief = ShoppingBrief(original_query="A chair that fits a small desk")
    source = str(new_id())
    original = [{"role": "user", "content": json.dumps({"brief": brief.model_dump(mode="json")})},
        {"type": "function_call", "call_id": "fetch", "name": "fetch_source", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "fetch", "output": json.dumps({"status": "succeeded", "source_id": source, "url": "https://example.org/chair", "text": "Aster Chair fits a 65cm desk opening."})}]
    projected, selection = project_owner_sources(original)
    assert tuple(str(item) for item in selection.selected_source_ids) == (source,)
    assert json.loads(projected[0]["content"])["brief"] == brief.model_dump(mode="json")
    assert "text" not in json.loads(projected[2]["output"])
    assert json.dumps(projected).count("Aster Chair fits a 65cm desk opening.") == 1
    assert original[2]["output"] != projected[2]["output"]


@pytest.mark.asyncio
async def test_actual_saved_archive_reaches_sdk_http_request_with_exact_speech_and_receipt(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.db.base import Base
    from app.db.session import create_session_factory
    from app.db.repositories.search_sources import SearchSourceRepository
    from app.db.repositories.products import ProductRepository
    from app.agents.context_management import ContextBudget, context_scope
    from app.schemas.products import CanonicalProduct
    from app.schemas.search_sources import SearchResult, SourceSnapshot, SourceEvidence
    from test_context_decision_fidelity import _seed, _owner
    from test_task224_finalization import LocalResponsesProvider, LocalOwnerRunner, response_payload

    archive_path = Path(__file__).resolve().parents[3] / "data/artifacts/task221/resume-20261017/phone-attempt4-result-api.json"
    archive_bytes = archive_path.read_bytes()
    archive = json.loads(archive_bytes)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    _, run, _, sources, _, claims = await _seed(factory, phone=False)
    brief = ShoppingBrief.model_validate(archive["shopping_brief"])
    owner, request, _ = _owner(factory, run, brief, sources, claims, phone=False)
    async with factory() as session:
        repo = SearchSourceRepository(session)
        for row in archive["source_results"]:
            await repo.add_search_result(run.run_id, SearchResult.model_validate(row))
        for row in archive["source_snapshots"]:
            await repo.add_source_snapshot(run.run_id, SourceSnapshot.model_validate(row))
        for row in archive["source_evidence"]:
            await repo.add_source_evidence(run.run_id, SourceEvidence.model_validate(row))
        for row in archive["products"]:
            await ProductRepository(session).add_canonical_product(run.run_id, CanonicalProduct.model_validate(row))
        await session.commit()
        before = [item.model_dump(mode="json") for item in await repo.list_source_snapshots(run.run_id)]
    output = {"category": "smartphone", "rationale": "The camera comparison retains useful alternatives.",
        "candidates": [{"name": "iPhone 18 Pro Max", "choice_group": "primary", "evidence_ids": [row["evidence_id"] for row in archive["source_evidence"]]}],
        "selected_candidate_name": "iPhone 18 Pro Max"}
    provider = LocalResponsesProvider(response_payload(json.dumps(output), output_tokens=500))
    owner.model_runner = LocalOwnerRunner(provider)
    budget = ContextBudget()
    http_sizes = []
    async def capture_http_size(http_request):
        http_sizes.append({"utf8_bytes": len(http_request.content), "characters": len(http_request.content.decode()),
            "local_estimated_tokens": (len(http_request.content) + 2) // 3})
    provider.client._client.event_hooks.setdefault("request", []).append(capture_http_size)
    try:
        with context_scope(budget):
            draft = await owner.resume_saved(request, owner_agent_name="GeneralShoppingAgent", activity=())
        assert draft.candidates[0].name == "iPhone 18 Pro Max"
        assert len(provider.calls) == 1
        actual = input_projection(provider.calls[0]["input"])
        receipt = next(item["output"] for item in owner.workbench_activity if item["tool_name"] == "decision_source_selection")
        assert receipt["selected_source_ids"] == [str(item) for item in actual.selected_source_ids]
        assert receipt["projection_id"] == actual.projection_id
        encoded = json.dumps(provider.calls[0])
        assert "best-smartphones-of-2026-a-comprehensive-comparison" in encoded
        for evidence in archive["source_evidence"]:
            for support in evidence["transcript_support"]:
                assert any(segment.model_dump(mode="json") == support for packet in actual.sources for segment in packet.transcript_support)
        assert "saved_sources" not in encoded and "saved_video_bundles" not in encoded
        assert receipt["measurements"]["complete_request"]["utf8_bytes"] > receipt["measurements"]["selected_source_content"]["utf8_bytes"]
        async with factory() as session:
            after = [item.model_dump(mode="json") for item in await SearchSourceRepository(session).list_source_snapshots(run.run_id)]
        assert before == after and archive_path.read_bytes() == archive_bytes
        artifact = Path(__file__).resolve().parents[3] / "data/artifacts/task225/sdk-metrics-saved.json"
        artifact.write_text(json.dumps({"offline_control": True, "provider_usage_is_synthetic": True,
            "actual_local_http_requests": http_sizes, "context_calls": [event for event in budget.events if event["tool_name"] == "context_call"], "final_projection": receipt,
            "serialized_final_request": source_size(provider.calls[-1])}, ensure_ascii=False, indent=2) + "\n")
    finally:
        await provider.client.close()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["broad_phone", "exclusive", "soft_preference", "nontech", "no_category"])
async def test_effective_owner_sdk_discovers_without_seed_list_and_retains_new_coverage(case):
    from dataclasses import replace
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.db.base import Base
    from app.db.session import create_session_factory
    from app.db.repositories.products import ProductRepository
    from app.db.repositories.search_sources import SearchSourceRepository
    from app.agents.context_management import BoundedRunner, ContextBudget, context_scope
    from app.agents.research_tools import AgentResearchTools
    from app.providers.fakes import FakeSearchProvider, FakeExtractionProvider
    from app.schemas.intake import FieldSource, PreferenceConstraint, PreferenceMode
    from app.schemas.search_sources import SearchResult, SearchQuery, ProviderMetadata, SourceSnapshot, SourceType, ExtractionStatus, ExtractedPageContent, SourceQuality, SourceQualityLevel
    from test_context_decision_fidelity import _seed, _owner
    from test_task224_finalization import LocalResponsesProvider, response_payload

    category = "phone" if case in {"broad_phone", "exclusive", "soft_preference"} else "chair" if case == "nontech" else None
    queries = {"broad_phone": "Current phones for travel camera and battery with unlimited budget",
        "exclusive": "Only Aster phones for travel camera and battery",
        "soft_preference": "Phones for travel camera and battery, I prefer Aster but consider alternatives",
        "nontech": "Comfortable chairs that fit a small reading corner",
        "no_category": "Comfortable reading in a cramped corner without a clear product category"}
    initial_queries = {"broad_phone": "current flagship phones travel camera battery",
        "exclusive": "Aster current phones travel camera battery",
        "soft_preference": "current phones travel camera battery alternatives",
        "nontech": "compact comfortable reading chairs fit small corner",
        "no_category": "comfortable reading solutions cramped corner"}
    names = ("Aster X",) if case == "exclusive" else ("Aster X", "Birch Y")
    quote = "Aster X lasts longer between charges; Birch Y captures clearer night photos." if category == "phone" else "Aster X folds into a narrow corner; Birch Y provides a deeper supportive seat."
    if case == "exclusive":
        quote = "Aster X lasts longer between charges than previous Aster phones."
    preference = (PreferenceConstraint(text="I prefer Aster but consider alternatives", mode=PreferenceMode.SOFT),) if case == "soft_preference" else ()
    constraints = (PreferenceConstraint(text="Only Aster phones", mode=PreferenceMode.HARD),) if case == "exclusive" else ()
    brief = ShoppingBrief(original_query=queries[case], category=category,
        category_source=FieldSource.INFERRED if category else None, preferences=preference, constraints=constraints)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    _, run, _, seeded, _, claims = await _seed(factory, phone=False)
    owner, request, _ = _owner(factory, run, brief, seeded, claims, phone=False)
    source = SearchResult(query=SearchQuery(query=initial_queries[case], intent="discovery"), url="https://example.org/independent-comparison", title="Independent suitability comparison", snippet=quote,
        source_type=SourceType.PROFESSIONAL_REVIEW, provider=ProviderMetadata(provider_name="offline-search"), quality=SourceQuality(level=SourceQualityLevel.ADEQUATE))
    snapshot = SourceSnapshot(url=source.url, title=source.title, source_type=source.source_type, provider=ProviderMetadata(provider_name="offline-page"),
        extraction_status=ExtractionStatus.SUCCEEDED, extracted_content=ExtractedPageContent(text=quote, extractor="offline", word_count=20), quality=source.quality)
    search = FakeSearchProvider(results=(source,))
    owner.regional_research_tools_factory = lambda run_id, region_code: AgentResearchTools(agent_name="GeneralShoppingAgent", run_id=run_id, session_factory=factory,
        search_provider=search, extraction_provider=FakeExtractionProvider(snapshot=snapshot), required_region_code=region_code)

    def call(name, arguments, index):
        response = response_payload(None, output_tokens=20)
        response["output"] = [{"type": "function_call", "id": f"fc_{index}", "call_id": f"call_{index}", "name": name, "arguments": json.dumps(arguments)}]
        return response

    authored = {"category": category or "reading comfort", "rationale": "Aster X meets the main need; the comparison preserves its useful tradeoff.",
        "candidates": [{"name": "Aster X", "choice_group": "primary"}], "selected_candidate_name": "Aster X"}
    steps = [call("search_sources", {"query": initial_queries[case]}, 1),
        call("fetch_source", {"source_id": str(source.source_id)}, 2),
        call("record_source_quote", {"source_id": str(source.source_id), "quote": quote, "candidate_names": list(names), "buying_question": "buyer suitability", "finding": "distinct practical tradeoffs", "perspective": "comparative test"}, 3)]
    if case == "no_category":
        steps.append(response_payload("{}", status="incomplete", output_tokens=50))
    steps.append(response_payload(json.dumps(authored), output_tokens=100))
    provider = LocalResponsesProvider(*steps)

    class Runner:
        async def run(self, agent, model_input, *, run_config, max_turns):
            self.initial_input = json.loads(model_input)
            self.instructions = agent.instructions
            if case == "no_category":
                payload = json.loads(model_input)
                payload["older_context"] = [{"text": "Earlier irrelevant repeated navigation. " * 18000}]
                model_input = json.dumps(payload)
            return await BoundedRunner.run(agent, model_input, run_config=replace(run_config, model_provider=provider, tracing_disabled=True), max_turns=max_turns)

    runner = Runner()
    owner.model_runner = runner
    budget = ContextBudget()
    http_sizes = []
    async def capture_http_size(http_request):
        http_sizes.append({"utf8_bytes": len(http_request.content), "characters": len(http_request.content.decode()),
            "local_estimated_tokens": (len(http_request.content) + 2) // 3})
    provider.client._client.event_hooks.setdefault("request", []).append(capture_http_size)
    try:
        async with factory() as session:
            before_products = await ProductRepository(session).list_canonical_products_for_run(run.run_id)
            assert not any(item.name in names for item in before_products)
        with context_scope(budget):
            draft = await owner.run(request)
        assert draft.candidates[0].name == "Aster X", owner.workbench_activity
        actual = input_projection(provider.calls[-1]["input"])
        assert actual is not None
        assert actual.selected_source_ids == (source.source_id,)
        assert {row.candidate_name for row in actual.candidate_coverage} == set(names)
        assert actual.sources[0].excerpts == (quote,)
        assert actual.sources[0].source_quality.level.value == "adequate"
        assert "Aster X" not in json.dumps(runner.initial_input) and "Birch Y" not in json.dumps(runner.initial_input)
        assert "useful variety in candidate products and source content" in runner.instructions
        assert "Category-first discovery is optional" in runner.instructions
        assert provider.calls[0]["input"][0]["content"]
        if case != "exclusive":
            assert "Aster" not in initial_queries[case] and "Birch" not in initial_queries[case]
        if case == "no_category":
            assert provider.calls[-1]["tools"] == []
            assert any(event.get("output", {}).get("compaction") for event in budget.events if event["tool_name"] == "context_call")
        async with factory() as session:
            saved = await SearchSourceRepository(session).get_snapshot_for_search_result(run.run_id, source.source_id)
            assert saved.extracted_content.text == quote
            assert saved.provider.raw["candidate_coverage"][0]["candidate_names"] == list(names)
        receipts = [event["output"] for event in owner.workbench_activity if event["tool_name"] == "decision_source_selection" and event["status"] == "transported"]
        artifact = Path(__file__).resolve().parents[3] / f"data/artifacts/task225/sdk-metrics-{case}.json"
        artifact.write_text(json.dumps({"offline_control": True, "provider_usage_is_synthetic": True,
            "actual_local_http_requests": http_sizes, "context_calls": [event for event in budget.events if event["tool_name"] == "context_call"], "final_projection": receipts[-1],
            "serialized_final_request": source_size(provider.calls[-1])}, ensure_ascii=False, indent=2) + "\n")
    finally:
        await provider.client.close()
        await engine.dispose()


def test_distinct_speech_sources_keep_exact_claim_targets_without_shared_source_credit():
    from app.schemas.search_sources import SourceEvidence
    archive = json.loads((Path(__file__).resolve().parents[3] / "data/artifacts/task221/resume-20261017/phone-attempt4-result-api.json").read_text())
    claim = SourceEvidence.model_validate(archive["source_evidence"][0])
    first = DecisionSourcePacket(source_id=claim.source_id, url=str(claim.video.url), title="First test",
        content_kind="accepted_speech", candidate_names=("Exact A",), evidence=(claim,), content_sha256="a" * 64)
    second_claim = independent_speech(claim, new_id(), "another-test")
    second = DecisionSourcePacket(source_id=second_claim.source_id, url="https://www.youtube.com/watch?v=another-test", title="Independent test",
        content_kind="accepted_speech", candidate_names=("Exact A",), evidence=(second_claim,), content_sha256="b" * 64)
    result = select_decision_sources(ShoppingBrief(original_query="A phone camera comparison"), [first, second])
    assert set(result.selected_source_ids) == {first.source_id, second.source_id}
    assert result.sources[0].evidence[0].target == claim.target
    assert result.sources[1].evidence[0].target == second_claim.target
    assert {row.candidate_name for row in result.candidate_coverage} == {"Exact A"}


@pytest.mark.asyncio
async def test_candidate_annotations_reject_title_only_incidental_and_unobserved_identity(tmp_path):
    from app.agents.research_tools import AgentResearchTools, FetchSourceRequest
    from app.db.repositories.search_sources import SearchSourceRepository
    from app.schemas.search_sources import SourceSnapshot, SourceType, ProviderMetadata, ExtractionStatus, ExtractedPageContent
    from test_agent_research_tools import _database, _generic_result, RecordingSearchProvider, RecordingExtractionProvider
    engine, factory, run_id, _ = await _database(tmp_path)
    source = _generic_result()
    quote = "Aster Pro has a long battery life."
    snapshot = SourceSnapshot(url=source.url, title="Birch Y and Aster Pro Max product index", source_type=SourceType.PRODUCT_PAGE,
        provider=ProviderMetadata(provider_name="offline"), extraction_status=ExtractionStatus.SUCCEEDED,
        extracted_content=ExtractedPageContent(text=quote + "\nUnrelated names include Birch Y.", extractor="offline", word_count=15))
    try:
        async with factory() as session:
            repo = SearchSourceRepository(session)
            await repo.add_search_result(run_id, source)
            await repo.add_source_snapshot(run_id, snapshot, search_result_id=source.source_id)
            await session.commit()
        tools = AgentResearchTools(agent_name="GeneralShoppingAgent", run_id=run_id, session_factory=factory,
            search_provider=RecordingSearchProvider(), extraction_provider=RecordingExtractionProvider())
        args = {"buying_question": "battery life", "finding": "long battery"}
        assert (await tools.record_quote(source.source_id, quote, candidate_names=("Aster Pro",), **args)).status.value == "invalid_request"
        await tools.fetch(FetchSourceRequest(source_id=source.source_id))
        assert (await tools.record_quote(source.source_id, quote, candidate_names=("Birch Y",), **args)).status.value == "invalid_request"
        assert (await tools.record_quote(source.source_id, quote, candidate_names=("Aster Pro Max",), **args)).status.value == "invalid_request"
        assert (await tools.record_quote(source.source_id, quote, candidate_names=("Aster Pro",), **args)).status.value == "succeeded"
    finally:
        await engine.dispose()


def test_existing_context_pressure_preserves_broad_guide_before_repeated_single_candidate_speech():
    from app.schemas.search_sources import SourceEvidence
    archive = json.loads((Path(__file__).resolve().parents[3] / "data/artifacts/task221/resume-20261017/phone-attempt4-result-api.json").read_text())
    claim = SourceEvidence.model_validate(archive["source_evidence"][0])
    guide = packet("broad-guide", "Exact A offers a compact body; Exact B has longer battery; Exact C provides better video.",
        candidates=("Exact A", "Exact B", "Exact C"), question=("travel suitability",))
    speech = []
    for i in range(1, 7):
        source_id = new_id()
        evidence = independent_speech(claim, source_id, f"independent-{i}")
        speech.append(DecisionSourcePacket(source_id=source_id, url=str(evidence.video.url), title=f"Independent video {i}",
            content_kind="accepted_speech", candidate_names=("Exact A",), buying_questions=("travel suitability",),
            evidence=(evidence,), content_sha256=sha256(evidence.transcript_support[0].text.encode()).hexdigest()))
    brief = ShoppingBrief(original_query="A phone for travel battery camera and video")
    selected = select_decision_sources(brief, [*speech, guide])
    assert selected.selected_source_ids[0] == guide.source_id
    original = json.dumps({"brief": brief.model_dump(mode="json"), "decision_sources": selected.model_dump(mode="json")})
    minimum = select_decision_sources(brief, [speech[0], guide])
    tokens = measure(json.dumps({"brief": brief.model_dump(mode="json"), "decision_sources": minimum.model_dump(mode="json")}))["estimated_tokens"] + 250
    fitted = fit_owner_projection(original, tokens)
    actual = input_projection(fitted)
    assert guide.source_id in actual.selected_source_ids
    assert any(item.content_kind == "accepted_speech" for item in actual.sources)
    assert len(actual.sources) < len(selected.sources)
    assert measure(fitted)["estimated_tokens"] <= tokens


def test_exact_note_pairs_do_not_invent_cross_product_questions_and_unrelated_pages_stay_deferred():
    from app.agents.decision_sources import coverage_pairs
    from app.schemas.decision_sources import CandidateCoverageNote
    guide = packet("guide", "Aster X has long battery. Birch Y has a better camera.",
        candidates=("Aster X", "Birch Y"), question=("battery", "camera"))
    guide = guide.model_copy(update={"coverage_notes": (
        CandidateCoverageNote(candidate_names=("Aster X",), buying_question="battery", finding="long battery", quote="Aster X has long battery.", evidence_id=new_id()),
        CandidateCoverageNote(candidate_names=("Birch Y",), buying_question="camera", finding="better camera", quote="Birch Y has a better camera.", evidence_id=new_id()),
    )})
    assert coverage_pairs(guide) == {("Aster X", "battery"), ("Birch Y", "camera")}
    unrelated = packet("unrelated-cooking", "A different recipe uses more butter.", candidates=("Butter",))
    result = select_decision_sources(ShoppingBrief(original_query="A phone with good camera and battery"), [unrelated, guide])
    assert result.selected_source_ids == (guide.source_id,)
    assert result.deferred_source_ids == (unrelated.source_id,)
    assert [(row.candidate_name, row.buying_questions) for row in result.candidate_coverage] == [("Aster X", ("battery",)), ("Birch Y", ("camera",))]


@pytest.mark.asyncio
async def test_retained_comparison_sdk_uses_late_guide_and_more_than_fifteen_sources():
    from dataclasses import replace
    from app.agents.context_management import BoundedRunner, ContextBudget, context_scope
    from app.agents.contracts import ComparisonDecisionAgentInput
    from app.agents.live_comparison_decision import LiveComparisonDecisionAgent
    from app.core.settings import Settings
    from app.schemas.analysis import RecommendationBundle
    from app.schemas.products import CanonicalProduct
    from app.schemas.search_sources import SearchResult, SearchQuery, SourceSnapshot, SourceEvidence
    from test_task224_finalization import LocalResponsesProvider, response_payload

    products = (CanonicalProduct(name="Aster X"), CanonicalProduct(name="Birch Y"))
    brief = ShoppingBrief(original_query="Compare phone travel battery and camera")
    results, snapshots, evidence = [], [], []
    for index in range(19):
        quote = f"Aster X has a useful phone travel feature {index}."
        names = ("Aster X",)
        if index == 18:
            quote = "Aster X has better phone camera control; Birch Y has longer travel battery life."
            names = ("Aster X", "Birch Y")
        lead = SearchResult(query=SearchQuery(query="phone travel battery camera", intent="discovery"),
            url=f"https://example.org/{index:02d}-comparison", title=f"Phone suitability test {index}", snippet=quote,
            source_type="professional_review", provider={"provider_name": "offline-test"}, quality={"level": "adequate"})
        claim = SourceEvidence(source_id=lead.source_id,
            target={"target_type": "source_metadata", "source_id": lead.source_id},
            evidence_type="review_claim", claim=quote, confidence={"level": "medium", "score": 0.6}, source_quality={"level": "adequate"})
        snapshot = SourceSnapshot(source_id=lead.source_id, url=lead.url, title=lead.title,
            source_type=lead.source_type, extraction_status="succeeded", quality=lead.quality,
            provider={"provider_name": "offline-test", "raw": {"candidate_coverage": [{
                "candidate_names": names, "buying_question": f"travel suitability {index}", "finding": quote,
                "quote": quote, "evidence_id": str(claim.evidence_id), "perspective": "independent practical test",
            }]}}, extracted_content={"text": quote, "extractor": "offline-test", "word_count": len(quote.split())})
        results.append(lead)
        snapshots.append(snapshot)
        evidence.append(claim)
    archive = json.loads((Path(__file__).resolve().parents[3] / "data/artifacts/task221/resume-20261017/phone-attempt4-result-api.json").read_text())
    speech = SourceEvidence.model_validate(archive["source_evidence"][0])
    snapshots.append(SourceSnapshot.model_validate(next(row for row in archive["source_snapshots"] if row["source_id"] == str(speech.source_id))))
    evidence.append(speech)
    request = ComparisonDecisionAgentInput(run_id=new_id(), brief=brief, products=products,
        source_results=tuple(results), source_snapshots=tuple(snapshots), evidence=tuple(evidence))
    authored = RecommendationBundle(primary_product_ids=(products[0].product_id,), final_product_id=products[0].product_id,
        final_rationale="Aster X offers the useful camera control.")
    provider = LocalResponsesProvider(response_payload(authored.model_dump_json(), output_tokens=100))

    class Runner:
        async def run(self, agent, model_input, *, run_config, max_turns):
            payload = json.loads(model_input)
            payload["old_navigation"] = "Irrelevant repeated navigation. " * 18000
            return await BoundedRunner.run(agent, json.dumps(payload),
                run_config=replace(run_config, model_provider=provider, tracing_disabled=True), max_turns=max_turns)

    owner = LiveComparisonDecisionAgent(settings=Settings(_env_file=None, environment="test"), model_runner=Runner())
    budget = ContextBudget()
    try:
        with context_scope(budget):
            decision = await owner.run(request)
        assert decision.primary_product_ids == authored.primary_product_ids
        actual = input_projection(provider.calls[0]["input"])
        assert actual is not None
        assert len(actual.selected_source_ids) == 20
        assert results[-1].source_id in actual.selected_source_ids
        assert next(row for row in actual.candidate_coverage if row.candidate_name == "Birch Y").source_ids == (results[-1].source_id,)
        packet = next(row for row in actual.sources if speech.evidence_id in row.evidence_ids)
        assert packet.evidence[0].target == speech.target
        assert packet.transcript_support == speech.transcript_support
        encoded = json.dumps(provider.calls[0])
        assert "available_source_context" not in encoded
        assert "\"source_evidence\"" not in encoded
        receipts = [row for row in owner.workbench_activity if row["tool_name"] == "decision_source_selection" and row["status"] == "transported"]
        assert receipts[-1]["output"]["selected_source_ids"] == [str(identifier) for identifier in actual.selected_source_ids]
        assert any(row.get("output", {}).get("compaction") for row in budget.events if row["tool_name"] == "context_call")
    finally:
        await provider.client.close()
