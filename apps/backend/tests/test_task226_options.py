import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.agents.context_management import BoundedRunner, ContextBudget, context_scope
from app.agents.context_metrics import measure
from app.agents.contracts import GeneralShoppingAgentInput, GeneralShoppingDecisionDraft, GeneralShoppingOutcome
from app.agents.decision_sources import (
    fit_owner_projection,
    input_projection,
    project_owner_sources,
    select_decision_sources,
    source_size,
)
from app.agents.live_general_shopping import LiveGeneralShoppingAgent
from app.agents.research_tools import AgentResearchTools
from app.core.settings import Settings
from app.db.base import Base
from app.db.models.results import RecommendationBundleRecord
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_session_factory, get_db_session
from app.main import create_app
from app.orchestration.shopping_runs import RepositoryShoppingRunPersistenceHooks
from app.schemas.decision_sources import DecisionSourcePacket
from app.schemas.ids import new_id
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.products import CanonicalProduct
from app.schemas.runs import RunStage, RunStatus
from app.schemas.search_sources import SearchResult, SourceEvidence, SourceSnapshot
from test_context_decision_fidelity import _owner_bundle
from test_task224_finalization import LocalResponsesProvider, response_payload


ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / "data/artifacts/task226"
CAPTURED = ROOT / "data/artifacts/task221/resume-20261017"
FIXTURE = Path(__file__).parent / "fixtures/providers/task226_options.json"
CASES = json.loads(FIXTURE.read_text())["cases"]
SAMSUNG = "e854ae15-a34b-4116-a854-37ae51af4883"
SPEECH = "ee69aaf2-48c2-4dd9-8b9d-275ee330c473"
COMPARISON = "c8e57809-3a17-49c4-9779-2181eaf0a781"


class RejectResearchProviders:
    async def search(self, *args, **kwargs):
        pytest.fail("Task 226 must not search providers.")

    async def extract(self, *args, **kwargs):
        pytest.fail("Task 226 must not fetch sources.")


class OfflineOwnerRunner:
    def __init__(self, provider, *, archive=None, noise=False):
        self.provider = provider
        self.archive = archive
        self.noise = noise
        self.original_input = None

    async def run(self, agent, model_input, *, run_config, max_turns):
        self.original_input = json.loads(model_input)
        payload = dict(self.original_input)
        if self.noise:
            payload["unreviewed_navigation"] = {
                "text": "Repeated navigation without buying information. " * 18000
            }
        supplied = json.dumps(payload)
        if self.archive is not None:
            supplied = archived_history(supplied, self.archive)
        return await BoundedRunner.run(
            agent,
            supplied,
            run_config=replace(
                run_config, model_provider=self.provider, tracing_disabled=True
            ),
            max_turns=max_turns,
        )


def archived_history(model_input, archive):
    result = [{"role": "user", "content": model_input}]
    bodies = [("search_sources", {"results": archive["source_results"]})]
    bodies.extend(
        (
            "fetch_source",
            {
                "status": "succeeded",
                "source_id": row["source_id"],
                "url": row["url"],
                "title": row["title"],
                "text": row["extracted_content"]["text"],
                "source_quality": row["quality"],
            },
        )
        for row in archive["source_snapshots"]
        if row.get("extracted_content") and row["extracted_content"].get("text")
    )
    claims = archive["source_evidence"]
    bodies.append(
        (
            "consult_source_intelligence",
            {
                "status": "succeeded",
                "videos": list({row["video"]["video_id"]: row["video"] for row in claims}.values()),
                "transcript_segments": list({segment["segment_id"]: segment for row in claims for segment in row["transcript_support"]}.values()),
                "evidence": [
                    {**{key: value for key, value in row.items() if key not in {"video", "transcript_support", "evidence_type"}}, "video_id": row["video"]["video_id"]}
                    for row in claims
                ],
            },
        )
    )
    for index, (name, body) in enumerate(bodies):
        result.extend(
            [
                {
                    "type": "function_call",
                    "call_id": f"archive-{index}",
                    "name": name,
                    "arguments": "{}",
                },
                {
                    "type": "function_call_output",
                    "call_id": f"archive-{index}",
                    "output": json.dumps(body),
                },
            ]
        )
    return result


def received_objects(value):
    if isinstance(value, str):
        try:
            yield from received_objects(json.loads(value))
        except ValueError:
            return
    elif isinstance(value, dict):
        yield value
        for child in value.values():
            yield from received_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from received_objects(child)


def settings(tmp_path):
    return Settings(
        _env_file=None,
        environment="test",
        live_agents_enabled=True,
        openai_api_key="local-no-network",
        database_path=tmp_path / "task226.sqlite3",
        artifact_dir=tmp_path / "artifacts",
    )


async def database(tmp_path, brief):
    configuration = settings(tmp_path)
    engine = create_async_engine(f"sqlite+aiosqlite:///{configuration.database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as db:
        shopping_session = await SessionRepository(db).create(
            original_input=CreateSessionRequest(query=brief.original_query),
            current_brief=brief,
        )
        run = await RunRepository(db).create(shopping_session.session_id)
        await db.commit()
    return configuration, engine, factory, shopping_session, run


def owner_for(factory, configuration, provider, *, archive=None, noise=False):
    def tools(run_id, region_code):
        rejecting = RejectResearchProviders()
        return AgentResearchTools(
            agent_name="GeneralShoppingAgent",
            run_id=run_id,
            session_factory=factory,
            required_region_code=region_code,
            search_provider=rejecting,
            extraction_provider=rejecting,
        )

    owner = LiveGeneralShoppingAgent(
        settings=configuration,
        session_factory=factory,
        regional_research_tools_factory=tools,
        technology_research_tools_factory=tools,
        model_runner=OfflineOwnerRunner(provider, archive=archive, noise=noise),
    )
    return owner


async def seed_case(factory, run, case):
    async with factory() as db:
        repository = SearchSourceRepository(db)
        for row in case["sources"]:
            source = SearchResult(
                source_id=row["source_id"],
                query={"query": case["brief"]["original_query"], "intent": "discovery"},
                url=row["url"], title=row["title"], snippet=row["text"],
                source_type="professional_review", provider={"provider_name": "scripted-offline"},
                quality={"level": "adequate"},
            )
            annotation = {
                key: row[key] for key in (
                    "candidate_names", "buying_question", "finding", "perspective", "evidence_id"
                )
            }
            annotation["quote"] = row["text"]
            snapshot = SourceSnapshot(
                source_id=row["snapshot_id"], url=row["url"], title=row["title"],
                source_type=source.source_type,
                provider={"provider_name": "scripted-offline", "raw": {"candidate_coverage": [annotation]}},
                quality=source.quality, extraction_status="succeeded",
                extracted_content={"text": row["text"], "extractor": "scripted-offline", "word_count": len(row["text"].split())},
            )
            await repository.add_search_result(run.run_id, source)
            await repository.add_source_snapshot(run.run_id, snapshot, search_result_id=source.source_id)
        await ProductRepository(db).add_canonical_product(
            run.run_id, CanonicalProduct(name="Previously saved unrelated item")
        )
        await db.commit()


async def persist_and_project(factory, configuration, shopping_session, run, brief, owner, draft, expected):
    bundle, context = await _owner_bundle(factory, shopping_session, run, brief, owner, draft)
    by_name = {product.name: str(product.product_id) for product in context.owner_products}
    assert [str(item) for item in bundle.primary_product_ids] == [by_name[name] for name in expected["primary_names"]]
    assert [str(item) for item in bundle.runner_up_product_ids] == [by_name[name] for name in expected["runner_names"]]
    assert (str(bundle.final_product_id) if bundle.final_product_id else None) == by_name.get(expected["winner_name"])
    assert bundle.final_rationale == expected["rationale"]
    for advice in expected["advice"]:
        mode = next(item for item in bundle.mode_results if str(item.product_id) == by_name[advice["name"]])
        assert mode.rationale == advice["rationale"]
        assert mode.tradeoffs == (advice["tradeoff"],)
        assert [str(item) for item in mode.source_ids] == advice["source_ids"]
    async with factory() as db:
        hooks = RepositoryShoppingRunPersistenceHooks(
            run_repository=RunRepository(db), result_repository=ResultRepository(db),
            search_source_repository=SearchSourceRepository(db), product_repository=ProductRepository(db),
        )
        context.recommendation_bundle = bundle
        await hooks.record_stage_trace(
            run_id=run.run_id, stage=RunStage.GENERAL_OWNER, agent_name=draft.owner_agent_name,
            status=RunStatus.SUCCEEDED, trace_id="task226-offline",
            started_at="2026-10-18T00:00:00Z", ended_at="2026-10-18T00:00:01Z",
            tool_activity=owner.workbench_activity,
        )
        await hooks.persist_live_output(context)
        await RunRepository(db).append_event(
            run.run_id, stage=RunStage.COMPLETE, status=RunStatus.SUCCEEDED,
            message="Task 226 scripted offline option-set control.",
        )
        await db.commit()
        stored = await db.get(RecommendationBundleRecord, str(bundle.bundle_id))
        assert stored.bundle == bundle.model_dump(mode="json")
    app = create_app(configuration)

    async def sessions():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db_session] = sessions
    prefix = f"/api/sessions/{shopping_session.session_id}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as client:
        result = await client.get(f"{prefix}/results")
        session = await client.get(prefix)
        run_response = await client.get(f"{prefix}/runs/{run.run_id}")
        assert (result.status_code, session.status_code, run_response.status_code) == (200, 200, 200)
        payload = result.json()
        assert payload["recommendation_bundle"] == bundle.model_dump(mode="json")
        receipts = [item["output"] for item in owner.workbench_activity
                    if item.get("tool_name") == "decision_source_selection" and item.get("status") == "transported"]
        assert payload["decision_sources"] == receipts[-1]
        version_path = f'{prefix}/results/{payload["result_version"]["result_version_id"]}'
        async with factory() as db:
            await ResultRepository(db).save_result_bundle(
                run.run_id, trust_assessments=(), category_analyses=(), agent_records=(),
                recommendation_bundle=bundle.model_copy(update={"bundle_id": new_id(), "final_rationale": "A later scripted result."}),
            )
            await db.commit()
        assert (await client.get(version_path)).json() == payload
        assert (await client.get(f"{prefix}/results")).json()["recommendation_bundle"]["final_rationale"] == "A later scripted result."
    return payload, session.json(), run_response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda value: value["case_id"])
async def test_scripted_option_sets_survive_sdk_validation_sqlite_api_and_later_versions(tmp_path, case):
    brief = ShoppingBrief.model_validate(case["brief"])
    configuration, engine, factory, shopping_session, run = await database(tmp_path, brief)
    provider = LocalResponsesProvider(response_payload(json.dumps(case["authored"]), output_tokens=700))
    owner = owner_for(factory, configuration, provider)
    budget = ContextBudget()
    try:
        await seed_case(factory, run, case)
        with context_scope(budget):
            draft = await owner.resume_saved(
                GeneralShoppingAgentInput(run_id=run.run_id, brief=brief),
                owner_agent_name="GeneralShoppingAgent", activity=(),
            )
        assert len(provider.calls) == 1
        assert provider.calls[0]["max_output_tokens"] == 6667
        actual = input_projection(provider.calls[0]["input"])
        assert actual is not None
        objects = list(received_objects(provider.calls[0]["input"]))
        assert any(row.get("brief") == brief.model_dump(mode="json") for row in objects)
        assert all(row["name"] not in {product["name"] for product in owner.model_runner.original_input["saved_products"]} for row in case["authored"]["candidates"])
        assert {item.candidate_name for item in actual.candidate_coverage} >= set(case["expected"]["primary_names"] + case["expected"]["runner_names"])
        for row in case["sources"]:
            assert any(row["text"] in packet.excerpts for packet in actual.sources)
        assert [(item.name, item.choice_group) for item in draft.candidates] == [(item["name"], item["choice_group"]) for item in case["authored"]["candidates"]]
        assert draft.selected_candidate_name == case["expected"]["winner_name"]
        payload, session, run_response = await persist_and_project(
            factory, configuration, shopping_session, run, brief, owner, draft, case["expected"]
        )
        if case["case_id"] in {"two-primary", "three-primary-two-runners", "constrained-one"}:
            target = ARTIFACTS / "browser-cases.json"
            previous = json.loads(target.read_text()) if target.exists() else []
            exported = {
                "case_id": case["case_id"], "session_id": str(shopping_session.session_id),
                "result": payload, "session": session, "run": run_response,
                "primary_names": case["expected"]["primary_names"],
                "runner_names": case["expected"]["runner_names"],
                "rationale": case["expected"]["rationale"],
                "candidate_advice": case["expected"]["advice"],
            }
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps([item for item in previous if item["case_id"] != case["case_id"]] + [exported], indent=2) + "\n")
        (ARTIFACTS / f'sdk-{case["case_id"]}.json').write_text(json.dumps({
            "scripted_output": True, "claims_are_synthetic_controls": True,
            "serialized_request_estimate": source_size(provider.calls[0]),
            "selected_sources": actual.model_dump(mode="json"),
            "authored": case["authored"], "transport_events": budget.events,
        }, indent=2) + "\n")
    finally:
        await provider.client.close()
        await engine.dispose()


def captured_outputs():
    older = json.loads((CAPTURED / "phone-attempt3-result-api.json").read_text())
    latest = json.loads((CAPTURED / "phone-attempt4-result-api.json").read_text())
    assert older["shopping_brief"] == latest["shopping_brief"]
    assert older["recommendation_bundle"]["primary_product_ids"] == ["d701cfa8-7845-48ce-9b38-3c743367da0c", "8dfde622-6b57-40b0-a98e-e75538db7e4c"]
    assert latest["recommendation_bundle"]["primary_product_ids"] == ["879ec4c6-81e3-4e88-ade3-3f58e3c98a64"]
    assert older["recommendation_bundle"]["runner_up_product_ids"] == latest["recommendation_bundle"]["runner_up_product_ids"] == []
    return latest


async def seed_archive(factory, run, archive):
    async with factory() as db:
        repository = SearchSourceRepository(db)
        for row in archive["source_results"]:
            await repository.add_search_result(run.run_id, SearchResult.model_validate(row))
        for row in archive["source_snapshots"]:
            await repository.add_source_snapshot(run.run_id, SourceSnapshot.model_validate(row))
        for row in archive["source_evidence"]:
            await repository.add_source_evidence(run.run_id, SourceEvidence.model_validate(row))
        for row in archive["products"]:
            await ProductRepository(db).add_canonical_product(run.run_id, CanonicalProduct.model_validate(row))
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["normal", "saved", "funded", "rejected-output"])
async def test_captured_regression_keeps_alternative_facts_exact_speech_and_brief_in_actual_http(tmp_path, path):
    originals = [CAPTURED / f"phone-attempt{attempt}-result-api.json" for attempt in (3, 4)]
    hashes = {str(item): sha256(item.read_bytes()).hexdigest() for item in originals}
    archive = captured_outputs()
    brief = ShoppingBrief.model_validate(archive["shopping_brief"])
    configuration, engine, factory, _, run = await database(tmp_path, brief)
    authored = {
        "category": "phone", "rationale": "The iPhone offers camera control, while the Galaxy offers a different zoom arrangement.",
        "candidates": [
            {"name": "Apple iPhone 18 Pro Max", "choice_group": "primary", "evidence_ids": [row["evidence_id"] for row in archive["source_evidence"]], "rationale": "The captured reviewer describes variable-aperture camera control.", "tradeoff": "The reviewer describes the remaining camera setup as similar to the previous generation."},
            {"name": "Samsung Galaxy S26 Ultra", "choice_group": "primary", "source_ids": [SAMSUNG, COMPARISON], "rationale": "The captured comparison gives the Galaxy a different telephoto arrangement.", "tradeoff": "The available camera and battery figures include manufacturer claims and conflicting variant figures."},
        ],
        "selected_candidate_name": None,
    }
    steps = [response_payload(json.dumps(authored), output_tokens=600)]
    if path == "rejected-output":
        steps.insert(0, response_payload("{invalid final output", output_tokens=200))
    provider = LocalResponsesProvider(*steps)
    owner = owner_for(factory, configuration, provider, archive=archive if path != "saved" else None, noise=True)
    budget = ContextBudget(spent=165000 if path == "funded" else 500)
    wire_sizes = []

    async def wire(request):
        wire_sizes.append({"utf8_bytes": len(request.content), "characters": len(request.content.decode())})

    provider.client._client.event_hooks.setdefault("request", []).append(wire)
    try:
        await seed_archive(factory, run, archive)
        async with factory() as db:
            before = [(row.source_id, row.claim) for row in await SearchSourceRepository(db).list_source_evidence(run.run_id)]
        request = GeneralShoppingAgentInput(run_id=run.run_id, brief=brief)
        with context_scope(budget):
            draft = await owner.resume_saved(request, owner_agent_name="TechnologyDomainAnalystAgent", activity=()) if path == "saved" else await owner.run(request)
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        (ARTIFACTS / f"captured-{path}-requests.json").write_text(json.dumps({
            "offline_control": True, "outputs_are_scripted": True,
            "requests": provider.calls, "context_events": budget.events,
        }, indent=2) + "\n")
        assert draft.outcome.value == "draft", owner.workbench_activity
        assert [item.name for item in draft.candidates] == ["Apple iPhone 18 Pro Max", "Samsung Galaxy S26 Ultra"]
        assert len(provider.calls) == (2 if path == "rejected-output" else 1)
        for call in provider.calls:
            projection = input_projection(call["input"])
            assert projection is not None
            assert projection.candidate_coverage == ()
            packets = {str(identifier): item for item in projection.sources for identifier in (item.source_id, *item.equivalent_source_ids)}
            assert SAMSUNG in packets and COMPARISON in packets and SPEECH in packets, [(str(p.source_id), p.title, p.content_kind) for p in projection.sources]
            assert any("5000 mAh" in text and "31 hours of video playback" in text for text in packets[SAMSUNG].excerpts)
            assert any("50MP, f/2.9, 5x (periscope telephoto)" in text for text in packets[COMPARISON].excerpts)
            received = list(received_objects(call["input"]))
            assert any(row.get("brief") == brief.model_dump(mode="json") for row in received)
            speech = packets[SPEECH]
            expected_support = {segment["segment_id"]: segment for claim in archive["source_evidence"] for segment in claim["transcript_support"]}
            assert {str(segment.segment_id): segment.model_dump(mode="json") for segment in speech.transcript_support} == expected_support
            for claim in archive["source_evidence"]:
                received_claim = next(item for item in speech.evidence if str(item.evidence_id) == claim["evidence_id"])
                for field in ("source_id", "target", "claim", "transcript_segment_ids", "timestamp_references"):
                    assert received_claim.model_dump(mode="json")[field] == claim[field]
            assert "Repeated navigation without buying information." * 20 not in json.dumps(call["input"])
        context_calls = [item["output"] for item in budget.events if item["tool_name"] == "context_call"]
        assert context_calls and all(item["estimated_input_tokens"] <= budget.limits.input_tokens for item in context_calls)
        assert any(item.get("compaction") for item in context_calls)
        if path in {"funded", "rejected-output"}:
            assert provider.calls[-1]["tools"] == []
            assert "Further research is closed" in provider.calls[-1]["instructions"]
        if path == "rejected-output":
            assert any(event["status"] == "rejected_final_output" for event in budget.events)
        async with factory() as db:
            after = [(row.source_id, row.claim) for row in await SearchSourceRepository(db).list_source_evidence(run.run_id)]
        assert before == after
        assert {str(item): sha256(item.read_bytes()).hexdigest() for item in originals} == hashes
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        (ARTIFACTS / f"captured-{path}.json").write_text(json.dumps({
            "offline_control": True, "outputs_are_scripted": True,
            "normal_input_is_archived_native_tool_history": path != "saved",
            "original_artifact_hashes": hashes, "actual_http_requests": wire_sizes,
            "final_projection": input_projection(provider.calls[-1]["input"]).model_dump(mode="json"),
            "context_calls": context_calls, "model": provider.calls[-1]["model"],
            "output_caps": [call["max_output_tokens"] for call in provider.calls],
            "funding_is_synthetic_control": path == "funded",
        }, indent=2) + "\n")
    finally:
        await provider.client.close()
        await engine.dispose()


def test_existing_bound_keeps_only_useful_alternative_before_additional_shared_coverage():
    brief = ShoppingBrief(original_query="Compare phone camera, battery and carrying comfort")

    def packet(index, names, questions, text):
        return DecisionSourcePacket(
            source_id=UUID(int=226900 + index), url=f"https://example.org/{index}",
            title="Phone camera and battery comparison", content_kind="page", excerpts=(text,),
            candidate_names=names, buying_questions=questions, content_sha256=sha256(text.encode()).hexdigest(),
        )

    shared = packet(0, ("Aster", "Birch"), ("camera", "battery"), "Aster has longer battery while Birch takes clearer night photographs. " * 10)
    additional = packet(1, ("Aster", "Birch"), ("comfort",), "Aster and Birch have wide frames that are comfortable with two hands. " * 10)
    alternative = packet(2, ("Cedar",), ("camera",), "Cedar has an optical zoom lens useful for distant subjects. " * 10)
    projection = select_decision_sources(brief, (shared, additional, alternative))
    original = json.dumps({"brief": brief.model_dump(mode="json"), "decision_sources": projection.model_dump(mode="json")})
    bound = measure(original)["estimated_tokens"] - 1
    fitted = fit_owner_projection(original, bound)
    actual = input_projection(fitted)
    assert measure(fitted)["estimated_tokens"] <= bound
    assert {item.candidate_name for item in actual.candidate_coverage} == {"Aster", "Birch", "Cedar"}
    assert alternative.source_id in actual.selected_source_ids
    assert additional.source_id in actual.deferred_source_ids
    assert json.loads(fitted)["brief"] == brief.model_dump(mode="json")


def test_normal_projection_keeps_snippet_kind_and_merges_later_page_without_losing_facts():
    source_id, snapshot_id = new_id(), new_id()
    brief = ShoppingBrief(original_query="Compare phone camera and battery")
    url = "https://example.org/comparison"
    history = [
        {"role": "user", "content": json.dumps({"brief": brief.model_dump(mode="json")})},
        {"type": "function_call", "call_id": "search", "name": "search_sources", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "search", "output": json.dumps({
            "results": [{"source_id": str(source_id), "url": url, "title": "Phone comparison", "snippet": "Aster has longer battery life while Birch has a wider camera lens."}],
        })},
    ]
    projected, first = project_owner_sources(history)
    assert len(first.sources) == 1
    assert first.sources[0].content_kind == "search_lead"
    assert first.sources[0].excerpts == ("Aster has longer battery life while Birch has a wider camera lens.",)
    assert first.candidate_coverage == ()
    projected, repeated = project_owner_sources(projected)
    assert repeated == first
    projected.extend([
        {"type": "function_call", "call_id": "page", "name": "fetch_source", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "page", "output": json.dumps({
            "source_id": str(snapshot_id), "url": url, "title": "Phone comparison",
            "text": "Birch has stronger low-light camera detail than Aster during the reported test.",
        })},
    ])
    _, updated = project_owner_sources(projected)
    assert len(updated.sources) == 1
    assert updated.sources[0].source_id == source_id
    assert updated.sources[0].equivalent_source_ids == (snapshot_id,)
    assert updated.sources[0].content_kind == "page"
    assert updated.sources[0].excerpts == (
        "Aster has longer battery life while Birch has a wider camera lens.",
        "Birch has stronger low-light camera detail than Aster during the reported test.",
    )
    assert updated.candidate_coverage == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(("winner", "primary", "runner"), [
    (None, "Legacy reading lamp", "Legacy desk lamp"),
    ("Legacy desk lamp", "Legacy desk lamp", "Legacy reading lamp"),
])
async def test_legacy_ungrouped_materialization_keeps_its_existing_winner_fallback(tmp_path, winner, primary, runner):
    brief = ShoppingBrief(original_query="A lamp for reading")
    configuration, engine, factory, shopping_session, run = await database(tmp_path, brief)
    provider = LocalResponsesProvider()
    owner = owner_for(factory, configuration, provider)
    draft = GeneralShoppingDecisionDraft(
        category="lamp", outcome=GeneralShoppingOutcome.DRAFT,
        candidates=({"name": "Legacy reading lamp", "rationale": "An adjustable reading beam."},
                    {"name": "Legacy desk lamp", "rationale": "A wider desk beam."}),
        selected_candidate_name=winner, rationale="Compare the reading and desk beams.",
    )
    try:
        bundle, context = await _owner_bundle(factory, shopping_session, run, brief, owner, draft)
        names = {item.product_id: item.name for item in context.owner_products}
        assert names[bundle.final_product_id] == primary
        assert tuple(names[item] for item in bundle.primary_product_ids) == (primary,)
        assert tuple(names[item] for item in bundle.runner_up_product_ids) == (runner,)
        assert bundle.final_rationale == "Compare the reading and desk beams."
        assert provider.calls == []
    finally:
        await provider.client.close()
        await engine.dispose()
