import json
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from agents import Agent, RunConfig
from agents.items import ModelResponse
from agents.models.interface import Model
from agents.usage import Usage
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import app.agents.context_management as context_management
from app.agents.context_management import (
    BoundedRunner,
    ContextBudget,
    ContextBudgetExceeded,
    context_scope,
)
from app.agents.context_metrics import measure
from app.agents.contracts import GeneralShoppingOutcome
from app.api.routes.results import SessionResultsResponse
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.base import Base
from app.db.session import create_session_factory, get_db_session
from app.main import create_app
from app.orchestration.shopping_runs import RepositoryShoppingRunPersistenceHooks
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.intake import ShoppingBrief
from app.schemas.ids import new_id
from app.schemas.runs import RunStage, RunStatus
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceType,
    SourceEvidence,
)
from test_context_decision_fidelity import (
    _ScriptProvider,
    _call,
    _message,
    _owner,
    _owner_bundle,
    _seed,
    _settings,
)


@pytest_asyncio.fixture
async def saved_research():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


class _SavedOwnerModel(Model):
    def __init__(self, *, consult: bool = False, actual_tokens: int = 450):
        self.consult = consult
        self.actual_tokens = actual_tokens
        self.inputs: list[Any] = []
        self.scopes = ()
        self.rationale: str | None = None
        self.source_gap: dict[str, Any] | None = None

    async def get_response(
        self,
        instructions,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing,
        **kwargs,
    ):
        self.inputs.append(input)
        self.scopes = context_management._allowances.get()
        if self.consult and len(self.inputs) == 1:
            output = _call(
                "consult_source_intelligence",
                {"capability": "video_review", "product_name": "Amber Desk Lamp PH"},
            )
        else:
            payload = json.loads(input[0]["content"])
            notes = []

            def retained_notes(value):
                if isinstance(value, dict):
                    if "source_note" in value and "evidence_id" in value:
                        if value not in notes:
                            notes.append(value)
                    for child in value.values():
                        retained_notes(child)
                elif isinstance(value, list):
                    for child in value:
                        retained_notes(child)

            retained_notes(payload)
            by_claim = {note["source_note"]: note for note in notes}
            benefit = "Amber Desk Lamp PH has even light for reading. Brightness is limited for detailed work."
            warning = "Amber Desk Lamp imported offer costs PHP 4999.00 and has no local warranty."
            assert benefit in by_claim
            assert warning in by_claim
            assert payload["brief"]["region"]["region"]["country_code"] == "PH"
            assert (
                payload["brief"]["preferences"][0]["text"]
                == "Budget is not a constraint."
            )
            assert not handoffs
            if self.consult:
                outputs = [
                    json.loads(item["output"])
                    for item in input
                    if item.get("type") == "function_call_output"
                ]
                self.source_gap = next(row for row in outputs if "retryable" in row)
                assert self.source_gap["retryable"] is True
                assert self.source_gap["status"] == "gap"
            self.rationale = f"For reading, {benefit} {warning} Choose the PH model; the imported offer has no local warranty."
            output = _message(
                {
                    "category": "reading lamp",
                    "candidates": [
                        {
                            "name": "Amber Desk Lamp PH",
                            "choice_group": "primary",
                            "evidence_ids": [note["evidence_id"] for note in notes],
                        }
                    ],
                    "selected_candidate_name": "Amber Desk Lamp PH",
                    "rationale": self.rationale,
                }
            )
        return ModelResponse(
            output=output,
            response_id=None,
            usage=Usage(
                requests=1,
                input_tokens=self.actual_tokens - 150,
                output_tokens=150,
                total_tokens=self.actual_tokens,
            ),
        )

    async def stream_response(self, *args, **kwargs):
        raise AssertionError(
            "Local controlled completion cannot stream or make live calls."
        )
        yield


class _RetainedContextRunner:
    def __init__(self, model, notes, snapshots, *, pressure: bool):
        self.provider = _ScriptProvider({"gpt-6-sol": model})
        self.notes = notes
        self.snapshots = snapshots
        self.pressure = pressure
        self.original_input_tokens = 0

    async def run(self, agent, model_input, *, run_config, max_turns):
        payload = json.loads(model_input)
        payload["saved_source_notes"] = self.notes
        if self.pressure:
            payload["source_snapshots"] = [
                item.model_dump(mode="json") for item in self.snapshots
            ]
        expanded = json.dumps(payload)
        self.original_input_tokens = measure(expanded)["estimated_tokens"]
        agent = agent.clone(
            tools=[
                tool
                for tool in agent.tools
                if tool.name == "consult_source_intelligence"
            ],
            handoffs=[],
        )
        return await BoundedRunner.run(
            agent,
            expanded,
            run_config=replace(
                run_config, model_provider=self.provider, tracing_disabled=True
            ),
            max_turns=max_turns,
        )


class _FundingFailureSource:
    calls = 0

    async def run(self, request):
        self.calls += 1
        raise ContextBudgetExceeded(
            "Local source consultation cannot fund metadata retrieval."
        )


async def _saved_inputs(factory):
    shopping_session, run, brief, sources, snapshots, claims = await _seed(
        factory, phone=False
    )
    captured = (
        Path(__file__).resolve().parents[3]
        / "data/artifacts/task221/phone3-inspection.json"
    )
    captured_brief = ShoppingBrief.model_validate(
        json.loads(captured.read_text())["brief"]
    )
    brief = brief.model_copy(update={"preferences": captured_brief.preferences[1:]})
    notes, activity = [], []
    async with factory() as session:
        await SessionRepository(session).update_current_brief(
            shopping_session.session_id, brief
        )
        repository = SearchSourceRepository(session)
        for source, snapshot, claim in zip(sources, snapshots, claims, strict=True):
            evidence = await repository.add_source_evidence(
                run.run_id,
                SourceEvidence(
                    source_id=snapshot.source_id,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.SOURCE_METADATA,
                        source_id=snapshot.source_id,
                    ),
                    evidence_type=EvidenceType.REVIEW_CLAIM,
                    claim=claim,
                    confidence=Confidence(score=0.8, level=ConfidenceLevel.HIGH),
                    source_quality=snapshot.quality,
                ),
            )
            notes.append(
                {
                    "source_id": str(source.source_id),
                    "snapshot_id": str(snapshot.source_id),
                    "evidence_id": str(evidence.evidence_id),
                    "source_note": claim,
                    "url": str(source.url),
                }
            )
            activity.append(
                {
                    "tool_name": "record_source_quote",
                    "status": "succeeded",
                    "output": {
                        "source_ids": [
                            str(source.source_id),
                            str(snapshot.source_id),
                            str(evidence.evidence_id),
                        ]
                    },
                }
            )
        await session.commit()
    return (
        shopping_session,
        run,
        brief,
        sources,
        snapshots,
        claims,
        notes,
        tuple(activity),
    )


async def _persist_and_reload(
    factory, shopping_session, run, brief, owner, draft, authored
):
    bundle, context = await _owner_bundle(
        factory, shopping_session, run, brief, owner, draft
    )
    context.recommendation_bundle = bundle
    async with factory() as session:
        prior = await ResultRepository(session).save_result_bundle(
            run.run_id,
            trust_assessments=(),
            category_analyses=(),
            agent_records=(),
            recommendation_bundle=bundle.model_copy(
                update={
                    "bundle_id": new_id(),
                    "final_rationale": "Previously saved advice remains available.",
                }
            ),
        )
        hooks = RepositoryShoppingRunPersistenceHooks(
            run_repository=RunRepository(session),
            result_repository=ResultRepository(session),
            search_source_repository=SearchSourceRepository(session),
            product_repository=ProductRepository(session),
        )
        await hooks.persist_live_output(context)
        await RunRepository(session).append_event(
            run.run_id,
            stage=RunStage.COMPLETE,
            status=RunStatus.SUCCEEDED,
            message="Local controlled saved-work completion.",
        )
        await session.commit()
    async with factory() as session:
        stored = await ResultRepository(session).load_latest_result_bundle(run.run_id)
        assert stored.recommendation_bundle.final_rationale == authored
        assert stored.recommendation_bundle.no_strong_buy is False
        version_id = stored.result_version.result_version_id
        assert stored.result_version.version == 2
        old_version = await ResultRepository(session).load_result_bundle_by_version(
            prior.result_version.result_version_id
        )
        assert (
            old_version.recommendation_bundle.final_rationale
            == "Previously saved advice remains available."
        )
        snapshots = await SearchSourceRepository(session).list_source_snapshots(
            run.run_id
        )
        assert all(
            len(snapshot.extracted_content.text) > 60000 for snapshot in snapshots
        )
    app = create_app(_settings())

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/sessions/{shopping_session.session_id}/results"
        )
        repeated = await client.get(
            f"/api/sessions/{shopping_session.session_id}/results"
        )
        historical = await client.get(
            f"/api/sessions/{shopping_session.session_id}/results/{prior.result_version.result_version_id}"
        )
    assert response.status_code == repeated.status_code == 200
    api = SessionResultsResponse.model_validate(response.json())
    assert repeated.json() == response.json()
    assert api.result_version.result_version_id == version_id
    assert api.recommendation_bundle == stored.recommendation_bundle
    assert api.recommendation_bundle.final_product_id == api.products[0].product_id
    assert api.recommendation_bundle.final_rationale == authored
    assert api.recommendation_bundle.result_author == "GeneralShoppingAgent"
    assert len(api.recommendation_bundle.evidence_ids) == 3
    assert set(api.recommendation_bundle.source_ids) == {
        identifier
        for item in draft.candidates[0].evidence
        for identifier in (item.source_id, item.snapshot_id)
    }
    assert historical.status_code == 200
    assert (
        historical.json()["recommendation_bundle"]["final_rationale"]
        == "Previously saved advice remains available."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "compaction_fails", [False, True], ids=["deterministic-cleanup", "cleanup-fallback"]
)
async def test_reduced_saved_owner_completion_authors_and_saves_useful_advice(
    saved_research, monkeypatch, compaction_fails, record_property
):
    factory = saved_research
    (
        shopping_session,
        run,
        brief,
        sources,
        snapshots,
        claims,
        notes,
        activity,
    ) = await _saved_inputs(factory)
    model = _SavedOwnerModel()
    runner = _RetainedContextRunner(model, notes, snapshots, pressure=True)
    owner, request, _ = _owner(factory, run, brief, sources, claims, phone=False)
    owner.model_runner = runner
    if compaction_fails:

        def fail_projection(*args, **kwargs):
            raise ValueError("Local controlled optional compaction failure.")

        monkeypatch.setattr(context_management, "compact_to_tokens", fail_projection)
    budget = ContextBudget()
    with context_scope(budget):
        draft = await owner.resume_saved(
            request, owner_agent_name="GeneralShoppingAgent", activity=activity
        )
    assert draft.outcome == GeneralShoppingOutcome.DRAFT
    assert draft.selected_candidate_name == "Amber Desk Lamp PH"
    assert draft.rationale == model.rationale
    assert runner.original_input_tokens > 60000
    assert len(model.inputs) == 1
    transported = json.dumps(model.inputs[0])
    assert (
        measure(model.inputs[0])["estimated_tokens"] < runner.original_input_tokens // 2
    )
    assert all(claim in transported for claim in claims)
    event = next(
        event for event in budget.events if event.get("tool_name") == "context_call"
    )
    assert event["output"]["estimated_input_tokens"] <= 25334
    assert event["output"]["actual_input_tokens"] == 300
    record_property("original_estimated_input_tokens", runner.original_input_tokens)
    record_property(
        "final_estimated_input_tokens", event["output"]["estimated_input_tokens"]
    )
    record_property("known_actual_input_tokens", event["output"]["actual_input_tokens"])
    record_property("compaction", json.dumps(event["output"]["compaction"]))
    assert "unreviewed" in transported
    await _persist_and_reload(
        factory, shopping_session, run, brief, owner, draft, model.rationale
    )


@pytest.mark.asyncio
async def test_paid_actual_overage_retains_normal_owner_completion_and_blocks_followup(
    saved_research, record_property
):
    factory = saved_research
    (
        shopping_session,
        run,
        brief,
        sources,
        snapshots,
        claims,
        notes,
        _,
    ) = await _saved_inputs(factory)
    model = _SavedOwnerModel(actual_tokens=200001)
    runner = _RetainedContextRunner(model, notes, snapshots, pressure=False)
    owner, request, _ = _owner(factory, run, brief, sources, claims, phone=False)
    owner.model_runner = runner
    budget = ContextBudget()
    with context_scope(budget):
        draft = await owner.run(request)
        assert draft.outcome == GeneralShoppingOutcome.DRAFT
        assert draft.rationale == model.rationale
        assert budget.spent == 200001
        assert budget.exhausted is True
        assert budget.reserved == 0
        assert len(model.scopes) == 1
        assert model.scopes[0].scope == "owner"
        assert model.scopes[0].spent == 200001
        assert model.scopes[0].reserved == 0
        assert model.scopes[0].exhausted is True
        event = next(
            event for event in budget.events if event.get("tool_name") == "context_call"
        )
        assert event["status"] == "completed_actual_overage"
        assert event["output"]["charged_tokens"] == 200001
        assert event["output"]["shared_spent_tokens"] == 200001
        assert event["output"]["exceeded_scopes"] == ["main", "owner"]
        with pytest.raises(ContextBudgetExceeded):
            await BoundedRunner.run(
                Agent(name="GeneralShoppingAgent", model="gpt-6-sol"),
                json.dumps(
                    {
                        "brief": brief.model_dump(mode="json"),
                        "saved_source_notes": notes,
                    }
                ),
                run_config=RunConfig(
                    model_provider=runner.provider, tracing_disabled=True
                ),
                max_turns=1,
            )
        assert len(model.inputs) == 1
        assert budget.spent == 200001
        assert budget.reserved == 0
    record_property("known_actual_total_tokens", budget.spent)
    record_property("main_limit_tokens", budget.limits.total_tokens)
    record_property("completed_transport_status", event["status"])
    record_property("exceeded_scopes", json.dumps(event["output"]["exceeded_scopes"]))
    record_property("followup_model_calls", len(model.inputs) - 1)
    await _persist_and_reload(
        factory, shopping_session, run, brief, owner, draft, model.rationale
    )


@pytest.mark.asyncio
async def test_optional_source_technical_failure_preserves_normal_owner_saved_advice(
    saved_research,
):
    factory = saved_research
    (
        shopping_session,
        run,
        brief,
        sources,
        snapshots,
        claims,
        notes,
        _,
    ) = await _saved_inputs(factory)
    model = _SavedOwnerModel(consult=True)
    source = _FundingFailureSource()
    owner, request, _ = _owner(factory, run, brief, sources, claims, phone=False)
    owner.source_intelligence_manager = source
    owner.model_runner = _RetainedContextRunner(model, notes, snapshots, pressure=False)
    budget = ContextBudget()
    with context_scope(budget):
        draft = await owner.run(request)
    assert source.calls == 1
    assert len(model.inputs) == 2
    assert model.source_gap["retryable"] is True
    assert draft.outcome == GeneralShoppingOutcome.DRAFT
    assert draft.selected_candidate_name == "Amber Desk Lamp PH"
    assert draft.rationale == model.rationale
    assert budget.spent == 900
    assert budget.reserved == 0
    await _persist_and_reload(
        factory, shopping_session, run, brief, owner, draft, model.rationale
    )
