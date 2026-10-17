"""Local SDK/SQLite/API controls. None of this text is live caption evidence."""

import asyncio
import json
from dataclasses import replace
from hashlib import sha256

import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.agents.context_management import ContextBudget, context_scope
from app.agents.contracts import GeneralShoppingAgentInput
from app.agents.live_general_shopping import LiveGeneralShoppingAgent
from app.agents.live_source_intelligence_manager import (
    SourceIntelligenceManagerAgent,
    SourceManagerResult,
)
from app.agents.owner_research import OwnerResearchContext
from app.agents.research_tools import AgentResearchTools
from app.agents.source_consultation import SourceConsultationOutcome
from app.agents.youtube_review_intelligence_service import _bundle_from_video_snapshots
from app.agents.youtube_review_tools import YouTubeReviewTools
from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_session_factory, get_db_session
from app.main import create_app
from app.providers import (
    FakeExtractionProvider,
    FakeSearchProvider,
    FakeVideoSearchProvider,
)
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.runs import RunStage, RunStatus
from app.schemas.search_sources import (
    SourceIntelligenceCapability,
    VideoReviewEvidenceBundle,
)
from test_context_decision_fidelity import _BoundedSDKRunner, _owner_bundle, _settings
from test_task222_source_sdk import (
    _BoundedLocalRunner,
    _LocalModel,
    _LocalProvider,
    _call,
    _input,
    _message,
    _results,
    _settings as source_settings,
)
from test_task223_source_lifecycle import Captions


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_first", [False, True])
async def test_local_real_sdk_speech_reaches_normal_owner_sqlite_api_and_readonly_reload(
    tmp_path, failed_first
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'owner.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        brief = ShoppingBrief(original_query="Local monitor buying control")
        async with factory() as db:
            shopping = await SessionRepository(db).create(
                original_input=CreateSessionRequest(query=brief.original_query),
                current_brief=brief,
            )
            run = await RunRepository(db).create(shopping.session_id)
            await db.commit()
        payload = _input()
        captions = Captions()
        video_provider = FakeVideoSearchProvider(
            bundle=_bundle_from_video_snapshots(payload.source_snapshots)
        )
        failures = []

        def source_output(items):
            if failed_first and not failures:
                failures.append(True)
                raise RuntimeError("Local interrupted model interpretation")
            meta = next(r for r in _results(items) if "video" in r)
            transcript = next(r for r in _results(items) if "segments" in r)
            product = json.loads(items[0]["content"])["products"][0]
            segment = transcript["segments"][0]
            return _message(
                {
                    "selected_videos": [
                        {
                            "video_id": meta["video"]["video_id"],
                            "source_id": meta["source_id"],
                            "relevance_reason": "Local monitor review identity matches.",
                        }
                    ],
                    "claims": [
                        {
                            "video_id": meta["video"]["video_id"],
                            "source_id": meta["source_id"],
                            "product_id": product["product_id"],
                            "transcript_segment_id": segment["segment_id"],
                            "quote": segment["text"],
                            "interpretation": "Local reviewer describes readable text.",
                            "signal_kind": "pro",
                        }
                    ],
                }
            )

        parent = _LocalModel(
            [
                _call(
                    "consult_video_review", {"input": "Read the local monitor review."}
                ),
                _message(
                    {
                        "summary": "Local validated speech retained.",
                        "skipped_sources": [],
                    }
                ),
            ]
        )
        specialist = _LocalModel(
            [
                _call("search_videos", {"query": "local monitor review"}),
                _call("read_video_metadata", {"video_id": "ccMonitor01"}),
                _call("read_video_transcript", {"video_id": "ccMonitor01"}),
                source_output,
            ]
        )
        manager = SourceIntelligenceManagerAgent(
            settings=source_settings().model_copy(update={"artifact_dir": tmp_path}),
            video_provider=video_provider,
            transcript_provider=captions,
            model_runner=_BoundedLocalRunner(_LocalProvider(parent, specialist)),
        )
        received = {}

        def owner_output(items, handoffs):
            receipt = next(r for r in _results(items) if "consultation_id" in r)
            if failed_first and not received:
                assert receipt["status"] == "technical_failure"
                received.update(receipt)
                return _message(
                    {
                        "category": "monitor",
                        "candidates": [
                            {
                                "name": "Fixture Monitor",
                                "choice_group": "primary",
                                "rationale": "Local saved advice pending optional speech.",
                            }
                        ],
                        "rationale": "Local saved advice pending optional speech.",
                    }
                )
            assert receipt["status"] == "succeeded", receipt
            bundle = receipt["bundles"][0]
            segment = bundle["transcript_segments"][0]
            assert (
                segment["text"]
                == "Pro: the Fixture Monitor has sharp text and strong brightness for coding."
            )
            assert (
                segment["content_sha256"]
                == sha256(segment["text"].encode()).hexdigest()
            )
            assert segment["start_seconds"] == 15
            assert bundle["source_references"][0]["url"].startswith(
                "https://www.youtube.com/"
            )
            assert bundle["videos"][0]["video_id"] == segment["video_id"]
            received.update(receipt)
            evidence = next(e for e in bundle["evidence"] if not e["metadata_only"])
            return _message(
                {
                    "category": "monitor",
                    "candidates": [
                        {
                            "name": "Fixture Monitor",
                            "choice_group": "primary",
                            "evidence_ids": [evidence["evidence_id"]],
                            "source_ids": [evidence["source_id"]],
                            "rationale": "Choose it for readable text.",
                            "tradeoff": "The local control reports modest contrast.",
                        }
                    ],
                    "rationale": "Choose the local monitor for readable text.",
                }
            )

        from test_context_decision_fidelity import _ScriptModel

        model = _ScriptModel(
            [
                _call(
                    "consult_source_intelligence",
                    {"capability": "video_review", "product_name": "Fixture Monitor"},
                ),
                owner_output,
            ]
        )

        def research(run_id, region):
            return AgentResearchTools(
                agent_name="GeneralShoppingAgent",
                run_id=run_id,
                session_factory=factory,
                required_region_code=region,
                search_provider=FakeSearchProvider(),
                extraction_provider=FakeExtractionProvider(),
            )

        brief = ShoppingBrief.model_validate(
            {
                **brief.model_dump(mode="json"),
                "region": {
                    "region": {"country_code": "PH", "currency": "PHP"},
                    "source": "user_provided",
                },
            }
        )
        owner = LiveGeneralShoppingAgent(
            settings=_settings(),
            session_factory=factory,
            regional_research_tools_factory=research,
            technology_research_tools_factory=lambda run_id, region: AgentResearchTools(
                agent_name="TechnologyDomainAnalystAgent",
                run_id=run_id,
                session_factory=factory,
                required_region_code=region,
                search_provider=FakeSearchProvider(),
                extraction_provider=FakeExtractionProvider(),
            ),
            source_intelligence_manager=manager,
            model_runner=_BoundedSDKRunner({"gpt-6-sol": model}),
        )
        budget = ContextBudget()
        with context_scope(budget):
            draft = await owner.run(
                GeneralShoppingAgentInput(run_id=run.run_id, brief=brief)
            )
        assert received and not model.steps and not specialist.steps, (
            draft,
            owner.workbench_activity[-3:],
        )
        if not failed_first:
            assert not parent.steps
        assert captions.calls == 1
        if failed_first:
            assert received["status"] == "technical_failure"
            prior_draft = draft
            bundle, _ = await _owner_bundle(
                factory, shopping, run, brief, owner, prior_draft
            )
            async with factory() as db:
                prior = await ResultRepository(db).save_result_bundle(
                    run.run_id,
                    trust_assessments=(),
                    category_analyses=(),
                    agent_records=(),
                    recommendation_bundle=bundle,
                )
                await db.commit()
            source_retry = next(
                item["output"]
                for item in owner.workbench_activity
                if item["tool_name"] == "consult_source_intelligence"
            )
            parent.steps = [
                _call(
                    "consult_video_review", {"input": "Finish retained local captions."}
                ),
                _message(
                    {
                        "summary": "Local completed speech retained.",
                        "skipped_sources": [],
                    }
                ),
            ]
            parent.charges = [1000, 1000]
            specialist.steps = [
                _call("read_video_metadata", {"video_id": "ccMonitor01"}),
                _call("read_video_transcript", {"video_id": "ccMonitor01"}),
                source_output,
            ]
            specialist.charges = [1000, 1000, 1000]

            def resumed_output(items, handoffs):
                receipt = json.loads(items[0]["content"])["source_consultation"]
                assert receipt["prior_usage"] and receipt["status"] == "succeeded"
                return owner_output(
                    [{"type": "function_call_output", "output": json.dumps(receipt)}],
                    handoffs,
                )

            resumed_model = _ScriptModel([resumed_output])
            owner.model_runner = _BoundedSDKRunner({"gpt-6-sol": resumed_model})
            with context_scope(ContextBudget()):
                draft = await owner.resume_saved(
                    GeneralShoppingAgentInput(run_id=run.run_id, brief=brief),
                    owner_agent_name="GeneralShoppingAgent",
                    activity=owner.workbench_activity,
                    source_retry=source_retry,
                )
            assert received["status"] == "succeeded" and captions.calls == 1
            assert not parent.steps and not specialist.steps and not resumed_model.steps
        else:
            assert budget.spent == 6600
        assert draft.candidates[0].evidence[0].evidence_id
        bundle, context = await _owner_bundle(
            factory, shopping, run, brief, owner, draft
        )
        async with factory() as db:
            saved = await ResultRepository(db).save_result_bundle(
                run.run_id,
                trust_assessments=(),
                category_analyses=(),
                agent_records=(),
                recommendation_bundle=bundle,
            )
            evidence = await SearchSourceRepository(db).list_source_evidence(run.run_id)
            assert (
                evidence[0].transcript_support[0].text
                == received["bundles"][0]["transcript_segments"][0]["text"]
            )
            await RunRepository(db).append_event(
                run.run_id,
                stage=RunStage.COMPLETE,
                status=RunStatus.SUCCEEDED,
                message="Local control completion.",
            )
            if failed_first:
                old = await ResultRepository(db).load_result_bundle_by_version(
                    prior.result_version.result_version_id
                )
                assert (
                    old.recommendation_bundle.final_rationale
                    == "Local saved advice pending optional speech."
                )
            await db.commit()
        app = create_app(Settings(_env_file=None))

        async def db_session():
            async with factory() as db:
                yield db

        app.dependency_overrides[get_db_session] = db_session
        path = f"/api/sessions/{shopping.session_id}/results/{saved.result_version.result_version_id}"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://local"
        ) as client:
            first = await client.get(path)
            second = await client.get(path)
        assert first.status_code == 200 and first.json() == second.json()
        assert first.json()["source_evidence"][0]["transcript_support"][0][
            "content_sha256"
        ]
        assert captions.calls == 1 and not model.steps
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    ["technical_failure", "provider_gap", "partial", "no_attempt", "interrupted"],
)
async def test_local_empty_truthy_bundle_is_never_cached_success(tmp_path, status):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        async with factory() as db:
            brief = ShoppingBrief(original_query="Local failure classification")
            shopping = await SessionRepository(db).create(
                original_input=CreateSessionRequest(query=brief.original_query),
                current_brief=brief,
            )
            run = await RunRepository(db).create(shopping.session_id)
            await db.commit()

        class Manager:
            calls = 0

            async def run(self, data):
                self.calls += 1
                return SourceManagerResult(
                    video_bundles=(
                        VideoReviewEvidenceBundle(
                            transcript_gap_notes=("Local gap control",)
                        ),
                    ),
                    outcome=SourceConsultationOutcome(
                        status=status,
                        failure_type="RuntimeError"
                        if status == "technical_failure"
                        else None,
                    ),
                )

        manager = Manager()
        context = OwnerResearchContext(
            agent_name="GeneralShoppingAgent",
            run_id=run.run_id,
            brief=brief,
            region_code="PH",
            session_factory=factory,
            source_manager=manager,
        )
        result = await context.consult_source(
            SourceIntelligenceCapability.VIDEO_REVIEW, product_name="Local candidate"
        )
        assert result["status"] == status
        assert not context.research_state.completed_consultations
        assert context.activity[-1]["output"]["outcome"]["status"] == status
        again = await context.consult_source(
            SourceIntelligenceCapability.VIDEO_REVIEW, product_name="Local candidate"
        )
        assert again["status"] == "budget_exhausted" and manager.calls == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_local_caption_cancellation_records_start_and_durable_consumption():
    class Interrupted(Captions):
        async def fetch_transcript(self, video, options=None):
            raise asyncio.CancelledError()

    tools = YouTubeReviewTools(_input(), FakeVideoSearchProvider(), Interrupted())
    saved = []
    tools.checkpoint = lambda: saved.append(json.loads(json.dumps(tools.dump_state())))
    with pytest.raises(asyncio.CancelledError):
        await tools.transcript("ccMonitor01")
    assert [
        item["status"]
        for item in tools.workbench_activity
        if item["tool_name"] == "caption_retrieval"
    ] == ["started", "cancelled"]
    assert saved[-1]["transcripts_read"] == ["ccMonitor01"]
    restarted = YouTubeReviewTools(_input(), FakeVideoSearchProvider(), Captions())
    restarted.restore_state(saved[-1])
    assert (await restarted.transcript("ccMonitor01"))["status"] == "cancelled"
    assert restarted._transcripts_read == {"ccMonitor01"}


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", ["video_review", "community_discussion"])
async def test_local_api_requires_explicit_video_retry_and_freezes_old_result(
    tmp_path, monkeypatch, capability
):
    from app.schemas.analysis import RecommendationBundle
    from app.services.runs import RunService
    from app.db.repositories.products import ProductRepository
    from app.schemas.products import CanonicalProduct
    from test_task223_source_lifecycle import request

    settings = source_settings().model_copy(update={"artifact_dir": tmp_path})
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        data = request()
        async with factory() as db:
            shopping = await SessionRepository(db).create(
                original_input=CreateSessionRequest(query=data.brief.original_query),
                current_brief=data.brief,
            )
            run = await RunRepository(db).create(shopping.session_id)
            product = await ProductRepository(db).add_canonical_product(
                run.run_id, CanonicalProduct(name="Local retry control monitor")
            )
            saved = await ResultRepository(db).save_result_bundle(
                run.run_id,
                trust_assessments=(),
                category_analyses=(),
                agent_records=(),
                recommendation_bundle=RecommendationBundle(
                    primary_product_ids=(product.product_id,),
                    final_product_id=product.product_id,
                    final_rationale="Local useful saved advice.",
                ),
            )
            await RunRepository(db).append_event(
                run.run_id,
                stage=RunStage.COMPLETE,
                status=RunStatus.SUCCEEDED,
                message="Local API retry control.",
            )
            await db.commit()

        class Failed:
            async def run(self, *args, **kwargs):
                raise RuntimeError("Local source retry control.")

        manager = SourceIntelligenceManagerAgent(
            settings=settings, model_runner=Failed()
        )
        data = replace(
            data,
            run_id=run.run_id,
            allowed_capabilities=(SourceIntelligenceCapability(capability),),
        )
        failed = await manager.run(data)
        assert failed.outcome.status == "technical_failure"
        calls = []

        class Orchestrator:
            async def resume(self, run_id, brief, **kwargs):
                calls.append(kwargs)
                assert kwargs["source_retry"]["reuse_key"] == data.reuse_key
                async with factory() as db:
                    from app.db.models.results import ResultSourceProjectionRecord

                    assert (
                        await db.get(
                            ResultSourceProjectionRecord,
                            str(saved.result_version.result_version_id),
                        )
                        is not None
                    )
                    await RunRepository(db).append_event(
                        run_id,
                        stage=RunStage.COMPLETE,
                        status=RunStatus.SUCCEEDED,
                        message="Local explicit retry completed.",
                    )
                    await db.commit()

        monkeypatch.setattr(RunService, "_orchestrator", lambda self: Orchestrator())
        app = create_app(settings)

        async def db_session():
            async with factory() as db:
                yield db

        app.dependency_overrides[get_db_session] = db_session
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://local"
        ) as client:
            path = f"/api/sessions/{shopping.session_id}/runs/{run.run_id}/retry"
            prior_path = f"/api/sessions/{shopping.session_id}/results/{saved.result_version.result_version_id}"
            prior = (await client.get(prior_path)).json()
            assert (await client.post(path)).status_code == 409
            assert not calls
            response = await client.post(path + "?retry_source=true")
            assert response.status_code == (
                200 if capability == "video_review" else 409
            ), response.text
            assert len(calls) == (1 if capability == "video_review" else 0)
            after = await client.get(prior_path)
            assert after.json() == prior
        async with factory() as db:
            events = await RunRepository(db).list_events(run.run_id)
            assert any(
                "new bounded orchestration attempt" in event.message for event in events
            ) == (capability == "video_review")
    finally:
        await engine.dispose()


def test_local_owner_speech_stays_whole_when_video_description_is_large():
    from app.agents.owner_research import _bounded_owner_bundle

    text = "Local approved speech. " * 200 + "Local closing tradeoff remains exact."
    payload = {
        "bundle_id": "local-bundle",
        "videos": [
            {
                "video_id": "local-video",
                "url": "https://www.youtube.com/watch?v=local-video",
                "title": "Local long description control",
                "description": "Local metadata. " * 400,
                "channel_name": "Local creator",
            }
        ],
        "source_references": [
            {
                "source_id": "local-source",
                "url": "https://www.youtube.com/watch?v=local-video",
            }
        ],
        "transcript_segments": [
            {
                "segment_id": "local-segment",
                "video_id": "local-video",
                "start_seconds": 1,
                "end_seconds": 20,
                "text": text,
            }
        ],
        "evidence": [
            {
                "evidence_id": "local-evidence",
                "video_id": "local-video",
                "source_id": "local-source",
                "transcript_segment_ids": ["local-segment"],
                "claim": "Local closing tradeoff remains exact.",
                "metadata_only": False,
            }
        ],
    }
    result = _bounded_owner_bundle(
        payload, "local-bundle-hash", max_chars=9000, caution_details={}
    )
    assert result["transcript_segments"][0]["text"] == text
    assert (
        result["transcript_segments"][0]["content_sha256"]
        == sha256(text.encode()).hexdigest()
    )
    assert result["transcript_segments"][0]["source_id"] == "local-source"
    assert result["transcript_segments"][0]["url"].startswith(
        "https://www.youtube.com/"
    )
    assert result["video_descriptions_deferred"] and result["unreviewed_content"]
    assert result["reload_tool"] == "read_source_bundle"
    assert len(json.dumps(result)) < 9000
