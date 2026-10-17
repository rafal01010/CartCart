import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from agents import Agent, ModelSettings, RunConfig, Runner
from agents.exceptions import ModelBehaviorError
from agents.models.interface import ModelProvider
from agents.models.openai_responses import OpenAIResponsesModel
from openai import AsyncOpenAI

from app.agents.live_general_shopping import GeneralModelOutput


_CAPTURED = Path(__file__).parent / "fixtures/providers/task224_final_outputs.json"


def captured_output(attempt):
    document = json.loads(_CAPTURED.read_text())
    return next(case["output_text"] for case in document["cases"] if case["attempt"] == attempt)


def response_payload(text, *, status="completed", message_status="completed", output_tokens=2000, reasoning_tokens=0):
    return {
        "id": "resp_local", "object": "response", "created_at": 1,
        "model": "gpt-6-luna", "status": status,
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "output": [] if text is None else [{
            "type": "message", "id": "msg_local", "role": "assistant", "status": message_status,
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }],
        "usage": {"input_tokens": 100, "output_tokens": output_tokens, "total_tokens": 100 + output_tokens,
                  "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": reasoning_tokens}},
        "parallel_tool_calls": False, "tool_choice": "auto", "tools": [], "temperature": 1,
        "top_p": 1, "truncation": "disabled",
    }


class LocalResponsesProvider(ModelProvider):
    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = []
        self.ledger_snapshots = []

        async def respond(request):
            self.calls.append(json.loads(request.content))
            import app.agents.context_management as cm
            self.ledger_snapshots.append((cm.active_budget(), cm._allowances.get()))
            assert self.steps, "Unplanned local model request."
            step = self.steps.pop(0)
            if callable(step):
                step = step(self.calls[-1])
            if isinstance(step, BaseException):
                raise step
            return httpx.Response(200, json=step)

        self.client = AsyncOpenAI(api_key="local-no-network", max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))

    def get_model(self, model_name):
        return OpenAIResponsesModel(model_name, self.client)


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt", [1, 2], ids=["captured-tool-shaped-prose", "captured-eof"])
async def test_captured_failures_reproduce_in_actual_sdk(attempt):
    text = captured_output(attempt)
    provider = LocalResponsesProvider(response_payload(text))
    try:
        with pytest.raises(ModelBehaviorError, match="Invalid JSON"):
            await Runner.run(
                Agent(name="GeneralShoppingAgent", model="gpt-6-luna", output_type=GeneralModelOutput, model_settings=ModelSettings(max_tokens=2000)),
                "Captured offline final output reproduction.",
                run_config=RunConfig(model_provider=provider, tracing_disabled=True), max_turns=1,
            )
        assert len(provider.calls) == 1
    finally:
        await provider.client.close()


def complete_output(primary=2, runner=False):
    names = ["Amber Desk Lamp PH", "Cobalt Reading Lamp", "Cedar Table Light"][:primary]
    candidates = [{"name": name, "choice_group": "primary", "rationale": "Even light makes reading comfortable.", "tradeoff": "Its shade is larger than the compact alternative."} for name in names]
    if runner:
        candidates.append({"name": "Amber Desk Lamp Compact", "choice_group": "runner_up", "rationale": "The smaller shade fits a narrow desk.", "tradeoff": "It illuminates less of the reading area."})
    return {"category": "reading lamp", "rationale": "Choose Amber Desk Lamp PH for comfortable reading. Cobalt Reading Lamp offers a smaller shade.", "candidates": candidates, "selected_candidate_name": names[0]}


async def bounded_run(provider, budget, *, agent_name="GeneralShoppingAgent", output=2000, text="Saved buyer preferences and reviewed research."):
    from app.agents.context_management import BoundedRunner, context_scope

    with context_scope(budget):
        return await BoundedRunner.run(
            Agent(name=agent_name, model="gpt-6-luna", output_type=GeneralModelOutput, model_settings=ModelSettings(max_tokens=output)),
            text, run_config=RunConfig(model_provider=provider, tracing_disabled=True), max_turns=1,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["tool-shaped", "eof", "incomplete-message", "valid-message-incomplete-envelope", "reasoning-only", "empty", "in-progress", "in-progress-message"])
async def test_actual_responses_reject_partial_and_recover_once_on_same_ledger(failure, record_property):
    from app.agents.context_management import ContextBudget

    final = json.dumps(complete_output())
    first = response_payload(captured_output(1 if failure == "tool-shaped" else 2))
    if failure == "incomplete-message":
        first = response_payload(captured_output(2), status="incomplete", message_status="incomplete")
    if failure == "valid-message-incomplete-envelope":
        first = response_payload(final, status="incomplete")
    if failure in {"reasoning-only", "empty"}:
        first = response_payload(None, status="incomplete", reasoning_tokens=2000 if failure == "reasoning-only" else 0)
    if failure == "reasoning-only":
        first["output"] = [{"id": "reasoning_local", "type": "reasoning", "summary": []}]
    if failure == "in-progress":
        first = response_payload(final, status="in_progress")
    if failure == "in-progress-message":
        first = response_payload(final, message_status="in_progress")
    provider = LocalResponsesProvider(first, response_payload(final, output_tokens=550))
    budget = ContextBudget(spent=700)
    try:
        result = await bounded_run(provider, budget)
        assert result.final_output.model_dump(mode="json")["candidates"][0]["name"] == "Amber Desk Lamp PH"
        assert budget.spent == 3450 and budget.reserved == 0
        assert result.context_wrapper.usage.total_tokens == 2750
        assert result.context_wrapper.usage.requests == 2
        assert len(provider.calls) == 2
        assert provider.calls[1]["tools"] == []
        assert "Further research is closed" in provider.calls[1]["instructions"]
        assert "Saved buyer preferences" in json.dumps(provider.calls[1]["input"])
        assert all(call["max_output_tokens"] == 2000 for call in provider.calls)
        assert [event["status"] for event in budget.events] == ["rejected_final_output", "completed"]
        assert budget.events[0]["output"]["charged_tokens"] == 2100
        assert budget.events[1]["output"]["charged_tokens"] == 650
        if failure == "reasoning-only":
            assert budget.events[0]["output"]["reasoning_tokens"] == 2000
        record_property("transport_events", json.dumps(budget.events))
        record_property("spent_tokens", budget.spent)
        record_property("output_caps", json.dumps([call["max_output_tokens"] for call in provider.calls]))
    finally:
        await provider.client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["invalid-again", "transport", "overage", "unfunded", "non-owner"])
async def test_failed_completion_is_technical_bounded_and_preserves_spent(failure, record_property):
    from app.agents.context_management import ContextBudget, ContextBudgetExceeded, FinalOutputFailure

    first = response_payload(captured_output(2), output_tokens=200001 if failure == "overage" else 2000)
    second = httpx.ReadError("Local controlled transport failure.") if failure == "transport" else response_payload(captured_output(2))
    provider = LocalResponsesProvider(first, second)
    budget = ContextBudget()
    if failure == "unfunded":
        budget.limits = replace(budget.limits, total_tokens=14000)
        first["usage"]["output_tokens"] = 9900
        first["usage"]["total_tokens"] = 10000
    try:
        with pytest.raises((ContextBudgetExceeded, FinalOutputFailure)):
            await bounded_run(provider, budget, agent_name="VerifierCriticAgent" if failure == "non-owner" else "GeneralShoppingAgent")
        expected_calls = 2 if failure in {"invalid-again", "transport"} else 1
        assert len(provider.calls) == expected_calls
        assert budget.reserved == 0
        assert budget.spent >= 2100
        record_property("transport_events", json.dumps(budget.events))
        record_property("spent_tokens", budget.spent)
        record_property("model_calls", len(provider.calls))
        if failure == "overage":
            assert budget.spent == 200101 and budget.exhausted
            assert budget.events[0]["status"] == "blocked_actual_usage"
        if failure == "invalid-again":
            assert budget.spent == 4200
        if failure == "transport":
            assert budget.events[-1]["status"] == "failed_reserved"
            assert budget.events[-1]["output"]["charged_tokens"] > 0
            assert budget.spent == 2100 + budget.events[-1]["output"]["charged_tokens"]
    finally:
        await provider.client.close()


@pytest.mark.asyncio
async def test_complete_valid_contract_at_exact_cap_is_not_retried():
    from app.agents.context_management import ContextBudget

    provider = LocalResponsesProvider(response_payload(json.dumps(complete_output()), output_tokens=2000))
    budget = ContextBudget()
    try:
        result = await bounded_run(provider, budget)
        assert len(result.final_output.candidates) == 2
        assert len(provider.calls) == 1 and budget.spent == 2100
    finally:
        await provider.client.close()


class LocalOwnerRunner:
    def __init__(self, provider, *, pressure=False):
        self.provider = provider
        self.pressure = pressure
        self.original_input = None

    async def run(self, agent, model_input, *, run_config, max_turns):
        from app.agents.context_management import BoundedRunner

        self.original_input = model_input
        if self.pressure:
            payload = json.loads(model_input)
            payload["saved_sources"] = [{"page_text": "Redundant navigation. " * 18000, "source_id": "unreviewed-navigation"}]
            model_input = json.dumps(payload)
        return await BoundedRunner.run(agent, model_input, run_config=replace(run_config, model_provider=self.provider, tracing_disabled=True), max_turns=max_turns)


class SavedSpeechSource:
    def __init__(self, bundle):
        self.bundle = bundle
        self.calls = 0

    async def run(self, request):
        from app.agents.live_source_intelligence_manager import SourceManagerResult
        from app.agents.source_consultation import SourceConsultationOutcome

        self.calls += 1
        return SourceManagerResult(outcome=SourceConsultationOutcome(status="succeeded"), video_bundles=(self.bundle,))


def source_call_payload():
    response = response_payload(None, output_tokens=20)
    response["output"] = [{"id": "fc_source", "type": "function_call", "call_id": "call_source", "name": "consult_source_intelligence", "arguments": json.dumps({"capability": "video_review", "product_name": "Amber Desk Lamp PH"})}]
    return response


async def persist_groups_and_read_api(factory, shopping_session, run, brief, owner, draft, authored):
    from app.api.routes.results import SessionResultsResponse
    from app.db.repositories.results import ResultRepository
    from app.db.repositories.runs import RunRepository
    from app.db.session import get_db_session
    from app.main import create_app
    from app.schemas.ids import new_id
    from app.schemas.runs import RunStage, RunStatus
    from test_context_decision_fidelity import _owner_bundle, _settings

    bundle, context = await _owner_bundle(factory, shopping_session, run, brief, owner, draft)
    context.recommendation_bundle = bundle
    primary_names = [item["name"] for item in authored["candidates"] if item["choice_group"] == "primary"]
    runner_names = [item["name"] for item in authored["candidates"] if item["choice_group"] == "runner_up"]
    by_id = {item.product_id: item.name for item in context.owner_products}
    assert [by_id[item] for item in bundle.primary_product_ids] == primary_names
    assert [by_id[item] for item in bundle.runner_up_product_ids] == runner_names
    async with factory() as session:
        prior = await ResultRepository(session).save_result_bundle(run.run_id, trust_assessments=(), category_analyses=(), agent_records=(), recommendation_bundle=bundle.model_copy(update={"bundle_id": new_id(), "final_rationale": "Previous immutable advice."}))
        from app.orchestration.shopping_runs import RepositoryShoppingRunPersistenceHooks
        from app.db.repositories.products import ProductRepository
        from app.db.repositories.search_sources import SearchSourceRepository
        hooks = RepositoryShoppingRunPersistenceHooks(run_repository=RunRepository(session), result_repository=ResultRepository(session), search_source_repository=SearchSourceRepository(session), product_repository=ProductRepository(session))
        await hooks.persist_live_output(context)
        await RunRepository(session).append_event(run.run_id, stage=RunStage.COMPLETE, status=RunStatus.SUCCEEDED, message="Offline local Task 224 completion.")
        await session.commit()
    async with factory() as session:
        stored = await ResultRepository(session).load_latest_result_bundle(run.run_id)
        old = await ResultRepository(session).load_result_bundle_by_version(prior.result_version.result_version_id)
        assert stored.result_version.version == 2
        assert old.recommendation_bundle.final_rationale == "Previous immutable advice."
        assert stored.recommendation_bundle == bundle
    app = create_app(_settings())

    async def sessions():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = sessions
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
        response = await client.get(f"/api/sessions/{shopping_session.session_id}/results")
        historical = await client.get(f"/api/sessions/{shopping_session.session_id}/results/{prior.result_version.result_version_id}")
    assert response.status_code == historical.status_code == 200
    api = SessionResultsResponse.model_validate(response.json())
    assert api.recommendation_bundle == bundle
    products = {item.product_id: item.name for item in api.products}
    assert [products[item] for item in api.recommendation_bundle.primary_product_ids] == primary_names
    assert [products[item] for item in api.recommendation_bundle.runner_up_product_ids] == runner_names
    assert historical.json()["recommendation_bundle"]["final_rationale"] == "Previous immutable advice."


@pytest.mark.asyncio
@pytest.mark.parametrize("saved", [False, True], ids=["normal", "saved"])
@pytest.mark.parametrize("primary,runner", [(2, False), (3, False), (2, True), (3, True)], ids=["two-primary", "three-primary", "two-with-same-company-runner", "three-with-same-company-runner"])
async def test_owner_completion_uses_saved_speech_and_preserves_groups_in_sqlite_api(saved, primary, runner, record_property):
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.db.base import Base
    from app.db.session import create_session_factory
    from app.agents.context_management import ContextBudget, context_scope
    from app.agents.owner_research import OwnerResearchContext
    from test_context_decision_fidelity import _seed, _owner
    from test_task224_caption_focus import accepted_saved_speech_bundle, CAUTION

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    shopping_session, run, brief, sources, _, claims = await _seed(factory, phone=False)
    owner, request, _ = _owner(factory, run, brief, sources, claims, phone=False)
    bundle, speech = await accepted_saved_speech_bundle()
    source = SavedSpeechSource(bundle)
    owner.source_intelligence_manager = source
    authored = complete_output(primary, runner)
    authored["candidates"][0]["evidence_ids"] = [str(e.evidence_id) for e in bundle.evidence if not e.metadata_only]
    steps = [response_payload(captured_output(2 if saved else 1), status="incomplete" if saved else "completed"), response_payload(json.dumps(authored), output_tokens=750)]
    if not saved:
        steps.insert(0, source_call_payload())
    provider = LocalResponsesProvider(*steps)
    owner.model_runner = LocalOwnerRunner(provider, pressure=saved)
    budget = ContextBudget(spent=600)
    try:
        if saved:
            helpers = OwnerResearchContext(agent_name="GeneralShoppingAgent", run_id=run.run_id, brief=brief, region_code="PH", session_factory=factory)
            await helpers._persist_video_bundles((bundle,))
        with context_scope(budget):
            draft = await owner.resume_saved(request, owner_agent_name="GeneralShoppingAgent", activity=()) if saved else await owner.run(request)
        assert draft.outcome.value == "draft", (draft, owner.workbench_activity)
        assert [(item.name, item.choice_group) for item in draft.candidates] == [(item["name"], item["choice_group"]) for item in authored["candidates"]]
        assert len(provider.calls) == (2 if saved else 3)
        assert provider.calls[-1]["tools"] == []
        assert provider.calls[-1]["max_output_tokens"] == (6667 if saved else 3334)
        assert source.calls == (0 if saved else 1)
        main_ledgers = [snapshot[0] for snapshot in provider.ledger_snapshots]
        owner_ledgers = [snapshot[1][-1] for snapshot in provider.ledger_snapshots]
        assert all(item is budget for item in main_ledgers)
        assert all(item is owner_ledgers[0] for item in owner_ledgers)
        assert owner_ledgers[0].spent == budget.spent - 600
        assert owner_ledgers[0].reserved == budget.reserved == 0
        assert owner_ledgers[0].limits.total_tokens == 120000
        assert budget.limits.total_tokens == 200000
        assert all(call["model"] == provider.calls[0]["model"] for call in provider.calls)
        transported = json.dumps(provider.calls[-1]["input"])
        assert CAUTION in transported
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

        received = list(received_objects(provider.calls[-1]["input"]))
        for expected in speech:
            unit = next(item for item in received if item.get("segment_id") == expected["segment_id"] and "text" in item)
            for key in ("text", "video_id", "source_id", "segment_id", "start_seconds", "end_seconds", "url", "content_sha256"):
                assert unit[key] == expected[key]
        assert len(draft.candidates[0].evidence) == 2
        assert all(item.quote for item in draft.candidates[0].evidence)
        await persist_groups_and_read_api(factory, shopping_session, run, brief, owner, draft, authored)
        record_property("transport_events", json.dumps(budget.events))
        record_property("authored_groups", json.dumps([(item.name, item.choice_group) for item in draft.candidates]))
        record_property("owner_scope_spent", owner_ledgers[0].spent)
        record_property("output_caps", json.dumps([call["max_output_tokens"] for call in provider.calls]))
    finally:
        await provider.client.close()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["chat-completions", "responses-subclass"])
async def test_openai_transports_that_drop_completion_envelope_are_blocked(transport):
    from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
    from app.agents.context_management import BudgetedProvider, ContextBudget, ContextBudgetExceeded

    provider = LocalResponsesProvider()

    class UnmeasuredResponses(OpenAIResponsesModel):
        pass

    class UnsupportedProvider(ModelProvider):
        def get_model(self, model_name):
            model_class = OpenAIChatCompletionsModel if transport == "chat-completions" else UnmeasuredResponses
            return model_class(model_name, provider.client)

    try:
        with pytest.raises(ContextBudgetExceeded, match="completion status"):
            BudgetedProvider(UnsupportedProvider(), ContextBudget()).get_model("gpt-6-luna")
        assert provider.calls == []
    finally:
        await provider.client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("saved", [False, True], ids=["normal", "saved"])
@pytest.mark.parametrize("transport_error", [False, True], ids=["rejected-output", "local-transport-failure"])
async def test_failed_owner_reports_consumed_transport_usage_without_fallback(saved, transport_error, record_property):
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.db.base import Base
    from app.db.session import create_session_factory
    from app.agents.context_management import ContextBudget, context_scope
    from test_context_decision_fidelity import _seed, _owner

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    _, run, brief, sources, _, claims = await _seed(factory, phone=False)
    owner, request, _ = _owner(factory, run, brief, sources, claims, phone=False)
    last = httpx.ReadError("Local controlled finalization failure.") if transport_error else response_payload(captured_output(2))
    provider = LocalResponsesProvider(response_payload(captured_output(1)), last)
    owner.model_runner = LocalOwnerRunner(provider)
    budget = ContextBudget()
    try:
        with context_scope(budget):
            if saved:
                with pytest.raises(RuntimeError, match="saved shopping advice could not finish"):
                    await owner.resume_saved(request, owner_agent_name="GeneralShoppingAgent", activity=())
            else:
                await owner.run(request)
        activity = owner.workbench_activity[-1]
        assert activity["status"] == ("failed" if saved else "research_failed")
        assert len(provider.calls) == 2 and budget.reserved == 0
        if transport_error:
            assert all(value is None for value in activity["output"]["usage"].values())
            if not saved:
                assert activity["output"]["usage_complete"] is False
                assert activity["output"]["accounted_owner_tokens"] == budget.spent
        else:
            assert activity["output"]["usage"] == {"input_tokens": 200, "output_tokens": 4000, "total_tokens": 4200}
            assert budget.spent == 4200
            if not saved:
                assert activity["output"]["usage_complete"] is True
                assert activity["output"]["accounted_owner_tokens"] == 4200
        record_property("owner_activity", json.dumps(activity))
        record_property("spent_tokens", budget.spent)
        record_property("model_calls", len(provider.calls))
    finally:
        await provider.client.close()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("detail", ["missing", "null", "present"])
async def test_reasoning_detail_requires_actual_response_provenance(detail):
    from app.agents.context_management import ContextBudget

    response = response_payload(json.dumps(complete_output()), reasoning_tokens=77)
    if detail == "missing":
        response["usage"].pop("output_tokens_details")
    elif detail == "null":
        response["usage"]["output_tokens_details"] = None
    provider = LocalResponsesProvider(response)
    budget = ContextBudget()
    try:
        await bounded_run(provider, budget)
        assert budget.events[0]["output"]["reasoning_tokens"] == (77 if detail == "present" else None)
    finally:
        await provider.client.close()


def test_frozen_rejected_output_strings_match_recorded_hashes():
    from hashlib import sha256

    document = json.loads(_CAPTURED.read_text())
    assert len(document["cases"]) == 2
    for case in document["cases"]:
        assert sha256(case["output_text"].encode()).hexdigest() == case["output_sha256"]
        assert len(case["artifact_sha256"]) == 64


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False], ids=["same-specialist-completion", "no-technology-fallback-after-failure"])
async def test_actual_handoffs_keep_terminal_owner_and_one_completion_bound(success, record_property):
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.db.base import Base
    from app.db.session import create_session_factory
    from app.agents.context_management import ContextBudget, context_scope
    from test_context_decision_fidelity import _seed, _owner

    def transfer(target, arguments):
        def response(request):
            tool_name = next(tool["name"] for tool in request["tools"] if tool.get("type") == "function" and tool["name"].replace("_", "").endswith(target.lower()))
            result = response_payload(None, output_tokens=20)
            result["output"] = [{"id": "fc_" + target, "type": "function_call", "call_id": "call_" + target, "name": tool_name, "arguments": json.dumps(arguments)}]
            return result
        return response

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    _, run, brief, sources, _, claims = await _seed(factory, phone=True)
    owner, request, _ = _owner(factory, run, brief, sources, claims, phone=True)
    final = complete_output()
    final["category"] = "smartphone"
    provider = LocalResponsesProvider(
        transfer("TechnologyDomainAnalystAgent", {"technology_category": "smartphone", "reason": "Compare the useful camera and battery tradeoffs."}),
        transfer("SmartphoneSpecialistAgent", {"product_category": "phone", "reason": "Compare the useful camera and battery tradeoffs."}),
        response_payload(captured_output(1)),
        response_payload(json.dumps(final) if success else captured_output(2)),
    )
    owner.model_runner = LocalOwnerRunner(provider)
    budget = ContextBudget()
    try:
        with context_scope(budget):
            draft = await owner.run(request)
        assert len(provider.calls) == 4
        assert provider.calls[-1]["tools"] == []
        assert provider.calls[-1]["model"] == provider.calls[-2]["model"] == "gpt-6-luna"
        assert provider.calls[-1]["max_output_tokens"] == provider.calls[-2]["max_output_tokens"] == 2000
        assert draft.owner_agent_name == "SmartphoneSpecialistAgent"
        activity = owner.workbench_activity[-1]
        assert activity["status"] == ("draft" if success else "research_failed")
        assert activity["output"]["usage"]["total_tokens"] == 4440
        assert activity["output"]["accounted_owner_tokens"] == budget.spent == 4440
        assert not any(item.get("tool_name") == "owner_recovery" for item in owner.workbench_activity)
        assert len([item for item in owner.workbench_activity if item.get("tool_name") == "sdk_handoff" and item["status"] == "completed"]) == 2
        assert budget.reserved == 0
        record_property("transport_events", json.dumps(budget.events))
        record_property("owner_activity", json.dumps(activity))
    finally:
        await provider.client.close()
        await engine.dispose()
