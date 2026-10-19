import asyncio
from copy import deepcopy
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from app.agents.contracts import ShoppingScopeGuardrailInput
from app.api.routes.guided_intake import DbSession, _guided_service
from app.db.repositories.runs import RunRepository
from app.db.session import get_db_session
from app.schemas.errors import ErrorBody, ErrorEnvelope
from app.schemas.ids import new_id
from app.schemas.guided_intake import ShoppingGuardrailDecision, ShoppingGuardrailResult
from app.schemas.runs import RunStage, RunStatus
from app.services.guided_intake import GuidedIntakeService, _fixture_sessions
import test_guided_intake_api as guided_fixtures


guided_api_client = guided_fixtures.guided_api_client


async def _admit_run(
    client: TestClient, session_id: str, status: RunStatus
) -> None:
    async for db_session in client.app.dependency_overrides[get_db_session]():
        repository = RunRepository(db_session)
        run = await repository.create(UUID(session_id))
        if status != RunStatus.PENDING:
            await repository.append_event(
                run.run_id,
                stage=(
                    RunStage.COMPLETE
                    if status == RunStatus.SUCCEEDED
                    else RunStage.INTAKE
                ),
                status=status,
                message="Saved offline analysis state.",
                error=(
                    ErrorEnvelope(
                        error=ErrorBody(
                            code="offline_analysis_failed",
                            message="The saved analysis failed.",
                            request_id="offline-boundary-test",
                        )
                    )
                    if status == RunStatus.FAILED
                    else None
                ),
            )
        await db_session.commit()


async def _has_run(client: TestClient, session_id: str) -> bool:
    async for db_session in client.app.dependency_overrides[get_db_session]():
        return await RunRepository(db_session).has_for_session(UUID(session_id))
    raise AssertionError("The test database session was not opened.")


def _answer_budget(client: TestClient, session_id: str, text: str) -> dict:
    response = client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "budget",
            "answer": {"answer_type": "natural_language", "text": text},
        },
    )
    assert response.status_code == 200
    return response.json()


def _assert_mutations_rejected(client: TestClient, session_id: str) -> None:
    requests = (
        (
            "answers",
            {
                "question_id": "budget",
                "answer": {
                    "answer_type": "natural_language",
                    "text": "$200 and https://example.com/replacement",
                },
            },
        ),
        ("guide/reanswer", {"question_id": "budget"}),
        ("guide/skip", None),
        ("guide/skip-all", None),
        (
            "guide/region",
            {"status": "provided", "region": {"country_code": "PH"}},
        ),
    )
    for path, payload in requests:
        response = client.post(f"/api/sessions/{session_id}/{path}", json=payload)
        assert response.status_code == 409, (path, response.text)
        error = response.json()["error"]
        assert error["code"] == "guided_intake_not_collecting"
        assert error["message"] == (
            "This shopping question is not waiting for another answer."
        )
        assert error["details"] == {"session_id": session_id}


def _assert_started_projection(client: TestClient, session_id: str, brief: dict) -> None:
    response = client.get(f"/api/sessions/{session_id}/guide")
    assert response.status_code == 200
    guide = response.json()
    assert guide["status"] == "analysis_started"
    assert guide["ready_brief"] == brief
    assert guide["current_question"] is None
    assert guide["navigation"] == {
        "can_go_back": False,
        "current_reanswer_question_id": None,
        "reanswerable_questions": [],
    }
    assert guide["skippable_question"]["can_skip"] is False
    assert guide["analysis_start"]["enough_information"] is False
    assert guide["analysis_start"]["can_skip_all_and_start_analysis"] is False
    assert guide["region_setup"] == {
        "status": "not_needed",
        "prompt_text": None,
        "region": None,
        "can_refuse": False,
        "resumes_pending_question": False,
    }


@pytest.mark.parametrize("status", tuple(RunStatus))
@pytest.mark.parametrize("cold_cache", (False, True))
def test_admitted_run_closes_intake_for_every_status_and_cache_state(
    guided_api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    status: RunStatus,
    cold_cache: bool,
) -> None:
    created = guided_fixtures._create_guided_session(
        guided_api_client, "Which laptop should I buy for travel?"
    )
    session_id = created["session_id"]
    _answer_budget(guided_api_client, session_id, "$1,200.")
    reanswer = guided_api_client.post(
        f"/api/sessions/{session_id}/guide/reanswer", json={"question_id": "budget"}
    )
    assert reanswer.status_code == 200
    assert reanswer.json()["current_question"]["question_id"] == "budget"
    asyncio.run(_admit_run(guided_api_client, session_id, status))
    if cold_cache:
        _fixture_sessions.pop(UUID(session_id))
    cache_before = deepcopy(_fixture_sessions.get(UUID(session_id)))
    before = guided_api_client.get(f"/api/sessions/{session_id}").json()
    assert before["current_brief"]["budget"]["amount"]["amount"] == "1200"

    async def unexpected_guardrail(*args: object, **kwargs: object) -> None:
        raise AssertionError("Started intake must not run its classifier.")

    monkeypatch.setattr(
        GuidedIntakeService, "_check_effective_request", unexpected_guardrail
    )
    _assert_started_projection(guided_api_client, session_id, before["current_brief"])
    _assert_mutations_rejected(guided_api_client, session_id)
    assert guided_api_client.get(f"/api/sessions/{session_id}").json() == before
    assert _fixture_sessions.get(UUID(session_id)) == cache_before


def test_ready_intake_remains_revisable_until_run_is_admitted(
    guided_api_client: TestClient,
) -> None:
    created = guided_fixtures._create_guided_session(
        guided_api_client, "Which laptop should I buy for travel?"
    )
    session_id = created["session_id"]
    _answer_budget(guided_api_client, session_id, "$1,200.")
    skipped = guided_api_client.post(f"/api/sessions/{session_id}/guide/skip-all")
    assert skipped.status_code == 200
    assert skipped.json()["status"] == "ready_for_analysis"
    loaded = guided_api_client.get(f"/api/sessions/{session_id}/guide")
    assert loaded.status_code == 200
    assert loaded.json()["status"] == "ready_for_analysis"
    assert asyncio.run(_has_run(guided_api_client, session_id)) is False
    reopened = guided_api_client.post(
        f"/api/sessions/{session_id}/guide/reanswer", json={"question_id": "budget"}
    )
    assert reopened.status_code == 200
    assert reopened.json()["navigation"]["current_reanswer_question_id"] == "budget"
    revised = _answer_budget(guided_api_client, session_id, "$900.")
    assert revised["status"] == "ready_for_analysis"
    assert revised["ready_brief"]["budget"]["amount"]["amount"] == "900"
    saved = guided_api_client.get(f"/api/sessions/{session_id}").json()
    assert saved["current_brief"]["budget"]["amount"]["amount"] == "900"
    assert asyncio.run(_has_run(guided_api_client, session_id)) is False


def test_run_admitted_during_classifier_rejects_answer_without_saved_changes(
    guided_api_client: TestClient,
) -> None:
    created = guided_fixtures._create_guided_session(
        guided_api_client, "Which laptop should I buy for travel?"
    )
    session_id = created["session_id"]
    _answer_budget(guided_api_client, session_id, "$1,200.")
    reopened = guided_api_client.post(
        f"/api/sessions/{session_id}/guide/reanswer", json={"question_id": "budget"}
    )
    assert reopened.status_code == 200
    assert reopened.json()["current_question"]["question_id"] == "budget"
    before = guided_api_client.get(f"/api/sessions/{session_id}").json()
    cache_before = deepcopy(_fixture_sessions[UUID(session_id)])

    class AdmissionGuardrail:
        async def run(
            self, input_data: ShoppingScopeGuardrailInput
        ) -> ShoppingGuardrailResult:
            await _admit_run(guided_api_client, session_id, RunStatus.PENDING)
            return ShoppingGuardrailResult(decision=ShoppingGuardrailDecision.ALLOWED)

    def admission_service(db_session: DbSession) -> GuidedIntakeService:
        return GuidedIntakeService(db_session, guardrail=AdmissionGuardrail())

    guided_api_client.app.dependency_overrides[_guided_service] = admission_service
    response = guided_api_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "budget",
            "answer": {
                "answer_type": "natural_language",
                "text": "$200 and https://example.com/replacement",
            },
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "guided_intake_not_collecting"
    assert asyncio.run(_has_run(guided_api_client, session_id)) is True
    assert guided_api_client.get(f"/api/sessions/{session_id}").json() == before
    assert _fixture_sessions[UUID(session_id)] == cache_before


@pytest.mark.parametrize("cold_cache", (False, True))
def test_completed_fixture_run_keeps_saved_details_candidates_and_result_versions(
    guided_api_client: TestClient, cold_cache: bool
) -> None:
    created = guided_fixtures._create_guided_session(
        guided_api_client, "Which laptop should I buy for travel?"
    )
    session_id = created["session_id"]
    _answer_budget(guided_api_client, session_id, "$1,200.")
    product = guided_api_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "considered-products",
            "answer": {
                "answer_type": "natural_language",
                "text": "ThinkPad X1 Carbon. I need long battery life.",
            },
        },
    )
    assert product.status_code == 200
    run = guided_api_client.post(f"/api/sessions/{session_id}/runs")
    assert run.status_code == 201
    assert run.json()["status"] == "succeeded"
    before = guided_api_client.get(f"/api/sessions/{session_id}").json()
    result = guided_api_client.get(f"/api/sessions/{session_id}/results")
    history = guided_api_client.get(f"/api/sessions/{session_id}/results/history")
    events_url = f"/api/sessions/{session_id}/runs/{run.json()['run_id']}/events"
    events = guided_api_client.get(events_url)
    assert result.status_code == 200
    assert history.status_code == 200
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    assert result.json()["result_version"]["run_id"] == run.json()["run_id"]
    assert before["user_added_products"][0]["input_text"].startswith("ThinkPad X1")
    if cold_cache:
        _fixture_sessions.pop(UUID(session_id))

    _assert_started_projection(guided_api_client, session_id, before["current_brief"])
    _assert_mutations_rejected(guided_api_client, session_id)
    assert guided_api_client.get(f"/api/sessions/{session_id}").json() == before
    assert (
        guided_api_client.get(f"/api/sessions/{session_id}/results").json()
        == result.json()
    )
    assert (
        guided_api_client.get(f"/api/sessions/{session_id}/results/history").json()
        == history.json()
    )
    assert guided_api_client.get(events_url).text == events.text


def test_missing_session_keeps_not_found_for_guide_and_every_mutation(
    guided_api_client: TestClient,
) -> None:
    session_id = str(new_id())
    requests = (
        ("GET", "guide", None),
        (
            "POST",
            "answers",
            {
                "question_id": "budget",
                "answer": {"answer_type": "natural_language", "text": "$200"},
            },
        ),
        ("POST", "guide/reanswer", {"question_id": "budget"}),
        ("POST", "guide/skip", None),
        ("POST", "guide/skip-all", None),
        ("POST", "guide/region", {"status": "refused"}),
    )
    for method, path, payload in requests:
        response = guided_api_client.request(
            method, f"/api/sessions/{session_id}/{path}", json=payload
        )
        assert response.status_code == 404, (path, response.text)
        assert response.json()["error"]["code"] == "session_not_found"
