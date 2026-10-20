import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.models  # noqa: F401
from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.runs import RunRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import (
    create_database_engine,
    create_session_factory,
    get_db_session,
)
from app.main import create_app
from app.agents.contracts import (
    GeneralShoppingAgentInput,
    GeneralShoppingDecisionDraft,
    GeneralShoppingOutcome,
    ShoppingScopeGuardrailInput,
)
from app.core.settings import AgentWorkflowMode
from app.orchestration.shopping_runs import ShoppingRunOrchestrator
from app.services.runs import RunService
from app.services.guided_intake import _fixture_sessions
from app.agents.live_general_shopping import LiveGeneralShoppingAgent
from app.agents.live_guardrails import (
    LiveShoppingScopeGuardrail,
    MockShoppingGuardrailModelRunner,
)
from app.providers import FakeExtractionProvider, FakeSearchProvider
from app.schemas.guided_intake import (
    ShoppingGuardrailDecision,
    ShoppingGuardrailReason,
    ShoppingGuardrailResult,
)
from app.schemas.runs import RunStage


async def _create_tables(settings: Settings) -> None:
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


@pytest.fixture
def run_api_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "run-api.sqlite3",
    )
    asyncio.run(_create_tables(settings))

    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    app = create_app(settings)

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session

    try:
        with TestClient(app) as client:
            yield client
    finally:
        asyncio.run(engine.dispose())


def create_session(client: TestClient) -> str:
    response = client.post(
        "/api/sessions",
        json={"query": "Need a travel laptop"},
    )

    assert response.status_code == 201
    return response.json()["session_id"]


def test_fixture_agents_with_live_search_block_before_any_research(
    run_api_client: TestClient,
) -> None:
    settings = run_api_client.app.state.settings
    settings.search_provider = "tavily"
    settings.search_provider_enabled = True
    session_id = create_session(run_api_client)
    response = run_api_client.post(f"/api/sessions/{session_id}/runs")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "research_mode_mismatch"
    assert run_api_client.get(f"/api/sessions/{session_id}/results").status_code == 404


def test_technical_research_failure_is_failed_run_without_buying_result(
    run_api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailedOwner:
        workbench_activity = (
            {
                "tool_name": "general_owner",
                "status": "research_failed",
                "input": {},
                "output": {"gap": "Offline model unavailable"},
            },
        )

        async def run(self, input_data):
            return GeneralShoppingDecisionDraft(
                category="smartphone",
                outcome=GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE,
                rationale="Research failed.",
            )

    async def skip_scope_model(self, user_input):
        pass

    run_api_client.app.state.settings.agent_workflow_mode = AgentWorkflowMode.LIVE
    monkeypatch.setattr(RunService, "_check_live_agent_start", skip_scope_model)
    monkeypatch.setattr(
        RunService,
        "_live_agent_kwargs",
        lambda self: {"general_shopping_agent": FailedOwner()},
    )
    session_id = create_session(run_api_client)
    response = run_api_client.post(f"/api/sessions/{session_id}/runs")
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    run_id = response.json()["run_id"]
    status = run_api_client.get(f"/api/sessions/{session_id}/runs/{run_id}").json()
    assert status["current_stage"] == "general_owner"
    assert status["error"]["error"]["message"] == (
        "The shopping advice could not finish. Please retry using the saved research."
    )
    assert run_api_client.get(f"/api/sessions/{session_id}/results").status_code == 404


def parse_sse_payloads(body: str) -> list[dict[str, str]]:
    payloads: list[dict[str, str]] = []
    for raw_event in body.strip().split("\n\n"):
        payload: dict[str, str] = {}
        for line in raw_event.splitlines():
            key, value = line.split(": ", maxsplit=1)
            payload[key] = value
        payloads.append(payload)
    return payloads


@pytest.mark.parametrize(
    "query,corrected_category,expected_owner",
    (
        ("Find a comfortable wooden cane", "mobility aid", "GeneralShoppingAgent"),
        (
            "Which smartphone should I buy?",
            "smartphone",
            "SmartphoneSpecialistAgent",
        ),
    ),
)
def test_guided_live_run_enters_general_owner_before_category_routing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    corrected_category: str,
    expected_owner: str,
) -> None:
    class RecordingGeneralOwner:
        workbench_activity: tuple[dict[str, object], ...] = ()

        def __init__(self) -> None:
            self.calls: list[GeneralShoppingAgentInput] = []

        async def run(
            self, input_data: GeneralShoppingAgentInput
        ) -> GeneralShoppingDecisionDraft:
            self.calls.append(input_data)
            if input_data.brief.category == "smartphone":
                # Synthetic SDK activity tests API persistence; the SDK transfer
                # itself is exercised in test_live_general_shopping_agent.py.
                self.workbench_activity = (
                    {
                        "tool_name": "sdk_handoff",
                        "status": "completed",
                        "input": {
                            "source_agent": "GeneralShoppingAgent",
                            "reason": "Technology fit needs review.",
                        },
                        "output": {
                            "target_agent": "TechnologyDomainAnalystAgent",
                            "last_agent": "TechnologyDomainAnalystAgent",
                        },
                    },
                    {
                        "tool_name": "sdk_handoff",
                        "status": "completed",
                        "input": {
                            "source_agent": "TechnologyDomainAnalystAgent",
                            "reason": "Phone-specific review is useful.",
                        },
                        "output": {
                            "target_agent": "SmartphoneSpecialistAgent",
                            "last_agent": "SmartphoneSpecialistAgent",
                        },
                    },
                    {
                        "tool_name": "general_owner",
                        "status": "insufficient_evidence",
                        "input": {"agent": "GeneralShoppingAgent"},
                        "output": {"last_agent_model": "gpt-recording", "usage": {}},
                    },
                )
            return GeneralShoppingDecisionDraft(
                owner_agent_name=(
                    "SmartphoneSpecialistAgent"
                    if input_data.brief.category == "smartphone"
                    else "GeneralShoppingAgent"
                ),
                category=input_data.brief.category or "general shopping",
                outcome=GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE,
                evidence_gaps=("No research in this offline route test.",),
                rationale="There is not enough checked evidence to choose a product yet.",
            )

    owner = RecordingGeneralOwner()
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "general-owner-api.sqlite3",
        agent_workflow_mode=AgentWorkflowMode.LIVE,
    )
    asyncio.run(_create_tables(settings))
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    app = create_app(settings)

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    async def skip_live_scope_model(
        self: RunService, input_data: ShoppingScopeGuardrailInput
    ) -> None:
        del self, input_data

    def owner_only_dependencies(self: RunService) -> dict[str, object]:
        del self
        return {"general_shopping_agent": owner}

    async def reject_category_route(self: ShoppingRunOrchestrator, *args: object):
        del self, args
        raise AssertionError("Category routing ran before GeneralShoppingAgent.")

    monkeypatch.setattr(RunService, "_check_live_agent_start", skip_live_scope_model)
    guide_scope_classifier = MockShoppingGuardrailModelRunner()
    monkeypatch.setattr(
        "app.api.routes.guided_intake.LiveShoppingScopeGuardrail",
        lambda *, settings: LiveShoppingScopeGuardrail(
            settings=settings, model_runner=guide_scope_classifier
        ),
    )
    monkeypatch.setattr(RunService, "_live_agent_kwargs", owner_only_dependencies)
    monkeypatch.setattr(
        ShoppingRunOrchestrator, "_category_route", reject_category_route
    )
    monkeypatch.setattr(
        ShoppingRunOrchestrator,
        "_STAGES",
        ShoppingRunOrchestrator._STAGES[:2],
    )
    app.dependency_overrides[get_db_session] = override_get_db_session

    try:
        with TestClient(app) as client:
            created = client.post("/api/sessions/guided", json={"query": query})
            assert created.status_code == 201
            session_id = created.json()["session_id"]
            ready = client.post(f"/api/sessions/{session_id}/guide/skip-all")
            assert ready.status_code == 200
            assert guide_scope_classifier.calls == 1
            corrected = client.patch(
                f"/api/sessions/{session_id}/brief",
                json={
                    "category": corrected_category,
                    "category_source": "user_provided",
                },
            )
            assert corrected.status_code == 200
            run_response = client.post(f"/api/sessions/{session_id}/runs")
            assert run_response.status_code == 201
            run_id = run_response.json()["run_id"]
            events = client.get(f"/api/sessions/{session_id}/runs/{run_id}/events")
            assert events.status_code == 200
            stages = [
                json.loads(item["data"])["stage"]
                for item in parse_sse_payloads(events.text)
            ]
            assert stages == ["intake", "general_owner", "complete"]
            assert len(owner.calls) == 1
            assert owner.calls[0].brief.original_query == query
            assert owner.calls[0].brief.category == corrected_category
            assert str(owner.calls[0].run_id) == run_id

        async def read_owner_record():
            async with session_factory() as session:
                records = await ResultRepository(session).list_agent_records(
                    UUID(run_id)
                )
                return next(
                    record
                    for record in records
                    if record.stage == RunStage.GENERAL_OWNER
                )

        record = asyncio.run(read_owner_record())
        assert record.agent_name == expected_owner
        if expected_owner == "SmartphoneSpecialistAgent":
            transfers = [
                item
                for item in record.tool_activity
                if item["tool_name"] == "sdk_handoff"
            ]
            assert [item["output"]["target_agent"] for item in transfers] == [
                "TechnologyDomainAnalystAgent",
                "SmartphoneSpecialistAgent",
            ]
            assert transfers[-1]["output"]["last_agent"] == expected_owner
    finally:
        asyncio.run(engine.dispose())


@pytest.mark.asyncio
async def test_live_run_service_wires_regional_general_research(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "general-owner-wiring.sqlite3",
        agent_workflow_mode=AgentWorkflowMode.LIVE,
    )
    engine = create_database_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            service = RunService(
                session_repository=SessionRepository(session),
                run_repository=RunRepository(session),
                search_source_repository=SearchSourceRepository(session),
                search_provider=FakeSearchProvider(),
                extraction_provider=FakeExtractionProvider(),
                settings=settings,
            )
            owner = service._live_agent_kwargs()["general_shopping_agent"]
            assert isinstance(owner, LiveGeneralShoppingAgent)
            assert owner.shared_session is session
            assert owner.regional_research_tools_factory is not None
            tools = owner.regional_research_tools_factory(uuid4(), "PH")
            assert tools.required_region_code == "PH"
            assert tools._shared_session is session
            assert owner.technology_research_tools_factory is not None
            technology_tools = owner.technology_research_tools_factory(uuid4(), "PH")
            assert technology_tools.required_region_code == "PH"
            assert technology_tools._shared_session is session
    finally:
        await engine.dispose()


def test_create_run_runs_stub_orchestrator_synchronously(
    run_api_client: TestClient,
) -> None:
    session_id = create_session(run_api_client)

    response = run_api_client.post(f"/api/sessions/{session_id}/runs")

    assert response.status_code == 201
    body = response.json()
    UUID(body["run_id"])
    assert body["session_id"] == session_id
    assert body["status"] == "succeeded"
    assert body["current_stage"] == "complete"
    assert body["started_at"] is not None
    assert body["completed_at"] is not None
    assert body["error"] is None


def test_default_fixture_run_never_calls_general_model(
    run_api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unexpected_live_owner(
        self: LiveGeneralShoppingAgent, input_data: GeneralShoppingAgentInput
    ) -> GeneralShoppingDecisionDraft:
        del self, input_data
        raise AssertionError("Fixture run called the live GeneralShoppingAgent")

    monkeypatch.setattr(LiveGeneralShoppingAgent, "run", unexpected_live_owner)
    session_id = create_session(run_api_client)
    response = run_api_client.post(f"/api/sessions/{session_id}/runs")
    assert response.status_code == 201
    assert response.json()["status"] == "succeeded"


def test_create_run_uses_user_provided_region_without_failing(
    run_api_client: TestClient,
) -> None:
    create_response = run_api_client.post(
        "/api/sessions",
        json={
            "query": "Need a monitor for coding",
            "region": {
                "region": {
                    "country_code": "PH",
                    "currency": "PHP",
                    "locale": "en-PH",
                },
                "source": "user_provided",
            },
        },
    )
    assert create_response.status_code == 201

    response = run_api_client.post(
        f"/api/sessions/{create_response.json()['session_id']}/runs"
    )

    assert response.status_code == 201
    assert response.json()["status"] == "succeeded"


def test_create_run_rejects_invalid_session(run_api_client: TestClient) -> None:
    session_id = uuid4()

    response = run_api_client.post(f"/api/sessions/{session_id}/runs")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "session_not_found"
    assert body["error"]["details"] == {"session_id": str(session_id)}


def test_create_run_uses_mocked_classifier_block_before_run_start(
    run_api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classifier = MockShoppingGuardrailModelRunner(
        output=ShoppingGuardrailResult(
            decision=ShoppingGuardrailDecision.BLOCKED,
            reason=ShoppingGuardrailReason.UNSAFE_PRODUCT,
            message="This request is outside ordinary shopping help.",
        )
    )
    run_api_client.app.state.settings.agent_workflow_mode = AgentWorkflowMode.LIVE
    monkeypatch.setattr(
        "app.services.runs.require_live_openai_agent_configuration",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.runs.LiveShoppingScopeGuardrail",
        lambda *, settings: LiveShoppingScopeGuardrail(
            settings=settings, model_runner=classifier
        ),
    )
    create_response = run_api_client.post(
        "/api/sessions",
        json={"query": "A request for the classifier to review"},
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["session_id"]

    response = run_api_client.post(f"/api/sessions/{session_id}/runs")

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "shopping_guardrail_blocked"
    assert body["error"]["details"] == {"reason": "unsafe_product"}
    assert classifier.calls == 1
    assert run_api_client.get(f"/api/sessions/{session_id}/results").status_code == 404


@pytest.mark.parametrize("context", ("clarified", "blocked_reanswer", "recovered_guide"))
def test_run_independently_checks_effective_guided_goal_before_creating_run(
    run_api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    context: str,
) -> None:
    inputs: list[ShoppingScopeGuardrailInput] = []

    class RecordingGuardrail(LiveShoppingScopeGuardrail):
        async def run(
            self, input_data: ShoppingScopeGuardrailInput
        ) -> ShoppingGuardrailResult:
            inputs.append(input_data)
            return await super().run(input_data)

    classifier = MockShoppingGuardrailModelRunner()
    settings = run_api_client.app.state.settings
    settings.agent_workflow_mode = AgentWorkflowMode.LIVE
    guardrail = RecordingGuardrail(settings=settings, model_runner=classifier)
    for target in (
        "app.api.routes.guided_intake.LiveShoppingScopeGuardrail",
        "app.services.runs.LiveShoppingScopeGuardrail",
    ):
        monkeypatch.setattr(target, lambda *, settings: guardrail)
    monkeypatch.setattr(
        "app.services.runs.require_live_openai_agent_configuration",
        lambda *args, **kwargs: None,
    )
    original_query = "https://shop.example/items/laptop"
    created = run_api_client.post(
        "/api/sessions/guided", json={"query": original_query}
    )
    assert created.status_code == 201
    session_id = created.json()["session_id"]
    clarified_goal = "Help me choose a laptop for homework."
    clarified = run_api_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "shopping-goal",
            "answer": {"answer_type": "natural_language", "text": clarified_goal},
        },
    )
    assert clarified.status_code == 200
    assert classifier.calls == 1
    blocked = ShoppingGuardrailResult(
        decision="blocked",
        reason="unsafe_product",
        message="I can help with ordinary consumer purchases.",
    )
    classifier.output = blocked
    expected_goal = clarified_goal
    if context == "blocked_reanswer":
        reopened = run_api_client.post(
            f"/api/sessions/{session_id}/guide/reanswer",
            json={"question_id": "shopping-goal"},
        )
        assert reopened.status_code == 200
        expected_goal = "Help me buy firearms."
        revised = run_api_client.post(
            f"/api/sessions/{session_id}/answers",
            json={
                "question_id": "shopping-goal",
                "answer": {"answer_type": "natural_language", "text": expected_goal},
            },
        )
        assert revised.status_code == 200
        assert revised.json()["status"] == "blocked"
    elif context == "recovered_guide":
        del _fixture_sessions[UUID(session_id)]
        recovered = run_api_client.get(f"/api/sessions/{session_id}/guide")
        assert recovered.status_code == 200
        assert recovered.json()["status"] == "blocked"
        assert recovered.json()["current_question"] is None
        assert inputs[-1].user_input == clarified_goal
        assert inputs[-1].prior_answers[0].answer.text == clarified_goal
    calls_before_run = classifier.calls

    response = run_api_client.post(f"/api/sessions/{session_id}/runs")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "shopping_guardrail_blocked"
    assert classifier.calls == calls_before_run + 1
    assert inputs[-1].user_input == expected_goal
    assert inputs[-1].prior_answers[0].answer.text == expected_goal
    saved = run_api_client.get(f"/api/sessions/{session_id}").json()
    assert saved["original_input"]["query"] == original_query
    assert saved["current_brief"]["original_query"] == clarified_goal
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM shopping_runs WHERE session_id = ?", (session_id,)
        ).fetchone() == (0,)


def test_get_run_status_returns_persisted_run(run_api_client: TestClient) -> None:
    session_id = create_session(run_api_client)
    create_response = run_api_client.post(f"/api/sessions/{session_id}/runs")
    assert create_response.status_code == 201
    created = create_response.json()

    response = run_api_client.get(
        f"/api/sessions/{session_id}/runs/{created['run_id']}"
    )

    assert response.status_code == 200
    loaded = response.json()
    assert loaded == created


def test_get_run_status_rejects_run_outside_session(
    run_api_client: TestClient,
) -> None:
    first_session_id = create_session(run_api_client)
    second_session_id = create_session(run_api_client)
    create_response = run_api_client.post(f"/api/sessions/{first_session_id}/runs")
    assert create_response.status_code == 201
    run_id = create_response.json()["run_id"]

    response = run_api_client.get(f"/api/sessions/{second_session_id}/runs/{run_id}")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "run_not_found"
    assert body["error"]["details"] == {
        "session_id": second_session_id,
        "run_id": run_id,
    }


def test_stream_run_events_returns_persisted_events_in_order(
    run_api_client: TestClient,
) -> None:
    session_id = create_session(run_api_client)
    create_response = run_api_client.post(f"/api/sessions/{session_id}/runs")
    assert create_response.status_code == 201
    run_id = create_response.json()["run_id"]

    with run_api_client.stream(
        "GET",
        f"/api/sessions/{session_id}/runs/{run_id}/events",
    ) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    payloads = parse_sse_payloads(body)
    event_data = [json.loads(payload["data"]) for payload in payloads]
    assert [payload["id"] for payload in payloads] == [
        str(index) for index in range(11)
    ]
    assert {payload["event"] for payload in payloads} == {"run_event"}
    assert [event["stage"] for event in event_data] == [
        "intake",
        "general_owner",
        "query_planning",
        "discovery",
        "extraction",
        "deduplication",
        "source_intelligence",
        "listing_trust",
        "category_analysis",
        "comparison_decision",
        "complete",
    ]
    assert event_data[-1]["status"] == "succeeded"
    assert event_data[-1]["message"] == "Fixture shopping run completed."


def test_create_run_streams_events_and_fetches_fixture_results(
    run_api_client: TestClient,
) -> None:
    session_id = create_session(run_api_client)
    create_response = run_api_client.post(f"/api/sessions/{session_id}/runs")
    assert create_response.status_code == 201
    run_id = create_response.json()["run_id"]

    with run_api_client.stream(
        "GET",
        f"/api/sessions/{session_id}/runs/{run_id}/events",
    ) as events_response:
        events_body = events_response.read().decode()
    results_response = run_api_client.get(f"/api/sessions/{session_id}/results")

    assert events_response.status_code == 200
    assert parse_sse_payloads(events_body)[-1]["id"] == "10"
    assert results_response.status_code == 200
    result_body = results_response.json()
    assert result_body["result_version"]["run_id"] == run_id
    bundle = result_body["recommendation_bundle"]
    assert bundle["no_strong_buy"] is True
    assert bundle["no_strong_buy_reason"]
    assert bundle["final_product_id"] is None
    assert bundle["final_listing_id"] is None
    assert len(result_body["agent_records"]) == 10
