import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.models  # noqa: F401
from app.core.settings import Settings
from app.db.base import Base
from app.db.session import (
    create_database_engine,
    create_session_factory,
    get_db_session,
)
from app.main import create_app


async def _create_tables(settings: Settings) -> None:
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


@pytest.fixture
def guided_api_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "guided-intake-api.sqlite3",
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


def _create_guided_session(client: TestClient, query: str) -> dict:
    response = client.post("/api/sessions/guided", json={"query": query})

    assert response.status_code == 201
    body = response.json()
    UUID(body["session_id"])
    return body


def test_create_guided_session_starts_from_single_question_and_loads_state(
    guided_api_client: TestClient,
) -> None:
    created = guided_api_client.post(
        "/api/sessions/guided",
        json={
            "query": "Which laptop should I buy?",
            "region_setup": {
                "status": "provided",
                "region": {"country_code": "us", "currency": "usd"},
            },
        },
    )

    assert created.status_code == 201
    body = created.json()
    guide = body["guide"]
    assert guide["status"] == "collecting"
    assert guide["current_question"]["question_id"] == "budget"
    assert guide["current_question"]["answer_surface"] == "textbox"
    assert guide["region_setup"]["status"] == "provided"
    assert guide["region_setup"]["region"]["country_code"] == "US"
    assert "link" not in guide["current_question"]["text"].lower()

    loaded = guided_api_client.get(f"/api/sessions/{body['session_id']}/guide")

    assert loaded.status_code == 200
    assert loaded.json() == guide


def test_submit_followup_answer_captures_budget_and_known_product_without_links(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(
        guided_api_client,
        "Which laptop should I buy for travel?",
    )
    session_id = created["session_id"]

    budget_response = guided_api_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "budget",
            "answer": {
                "answer_type": "natural_language",
                "text": "Around $1,200.",
            },
        },
    )
    assert budget_response.status_code == 200
    assert budget_response.json()["status"] == "collecting"
    assert budget_response.json()["current_question"]["question_id"] == "considered-products"

    response = guided_api_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "considered-products",
            "answer": {
                "answer_type": "natural_language",
                "text": "ThinkPad X1 Carbon. I need long battery life.",
            },
        },
    )

    assert response.status_code == 200
    guide = response.json()
    assert guide["status"] == "ready_for_analysis"
    assert guide["ready_brief"]["category"] == "laptop"
    assert guide["ready_brief"]["budget"]["amount"]["amount"] == "1200"
    assert guide["ready_brief"]["budget"]["mode"] == "preferred"
    assert guide["ready_brief"]["constraints"][0]["text"].endswith(
        "long battery life."
    )

    session = guided_api_client.get(f"/api/sessions/{session_id}").json()
    assert session["current_brief"] == guide["ready_brief"]
    assert session["user_added_products"][0]["input_text"].startswith("ThinkPad X1")


def test_skip_question_readies_existing_brief(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(guided_api_client, "Which camera should I buy?")

    first_skip = guided_api_client.post(
        f"/api/sessions/{created['session_id']}/guide/skip",
    )
    assert first_skip.status_code == 200
    assert first_skip.json()["status"] == "collecting"
    assert first_skip.json()["current_question"]["question_id"] == "considered-products"

    response = guided_api_client.post(
        f"/api/sessions/{created['session_id']}/guide/skip",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready_for_analysis"
    assert body["ready_brief"]["category"] == "camera"


def test_skip_all_starts_analysis_when_enough_information_exists(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(guided_api_client, "Which desk should I buy?")

    guide_response = guided_api_client.post(
        f"/api/sessions/{created['session_id']}/guide/skip-all",
    )
    loaded_response = guided_api_client.get(
        f"/api/sessions/{created['session_id']}/guide",
    )
    run_response = guided_api_client.post(
        f"/api/sessions/{created['session_id']}/runs",
    )

    assert guide_response.status_code == 200
    assert guide_response.json()["status"] == "ready_for_analysis"
    assert loaded_response.status_code == 200
    assert loaded_response.json()["status"] == "ready_for_analysis"
    assert run_response.status_code == 201
    assert run_response.json()["status"] == "succeeded"


def test_yes_no_choice_answers_move_to_next_prompt(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(
        guided_api_client,
        "Need a portable monitor for travel",
    )
    guide = created["guide"]
    assert guide["current_question"]["answer_surface"] == "inline_choice"
    assert guide["current_question"]["inline_choice"]["control_type"] == "yes_no"

    response = guided_api_client.post(
        f"/api/sessions/{created['session_id']}/answers",
        json={
            "question_id": "monitor-connection",
            "answer": {"answer_type": "yes_no", "value": False},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "collecting"
    assert body["current_question"]["question_id"] == "budget"
    assert body["navigation"]["can_go_back"] is True


def test_two_option_plus_type_answer_is_supported_when_justified(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(
        guided_api_client,
        "Between an iPhone and a Samsung, which is better?",
    )
    guide = created["guide"]
    control = guide["current_question"]["inline_choice"]
    assert control["control_type"] == "two_option_plus_type_answer"
    assert control["custom_answer_label"] == "Type my answer"

    response = guided_api_client.post(
        f"/api/sessions/{created['session_id']}/answers",
        json={
            "question_id": "comparison-priority",
            "answer": {
                "answer_type": "choice_with_text",
                "choice_id": "something-else",
                "text": "Camera quality matters most.",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "collecting"
    assert body["current_question"]["question_id"] == "budget"


def test_reanswer_prior_question_before_analysis(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(
        guided_api_client,
        "Need a portable monitor for travel",
    )
    session_id = created["session_id"]
    first_answer = guided_api_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "monitor-connection",
            "answer": {"answer_type": "yes_no", "value": True},
        },
    )
    assert first_answer.status_code == 200

    reanswer = guided_api_client.post(
        f"/api/sessions/{session_id}/guide/reanswer",
        json={"question_id": "monitor-connection"},
    )

    assert reanswer.status_code == 200
    assert reanswer.json()["current_question"]["question_id"] == "monitor-connection"
    assert (
        reanswer.json()["navigation"]["current_reanswer_question_id"]
        == "monitor-connection"
    )

    revised = guided_api_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "monitor-connection",
            "answer": {"answer_type": "yes_no", "value": False},
        },
    )

    assert revised.status_code == 200
    assert revised.json()["status"] == "ready_for_analysis"
    assert revised.json()["current_question"] is None


def test_region_setup_can_be_refused_or_supplied_after_creation(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(guided_api_client, "Which phone should I buy?")
    session_id = created["session_id"]
    assert created["guide"]["region_setup"]["status"] == "needs_answer"

    refused = guided_api_client.post(
        f"/api/sessions/{session_id}/guide/region",
        json={"status": "refused"},
    )
    assert refused.status_code == 200
    assert refused.json()["region_setup"]["status"] == "refused"

    supplied = guided_api_client.post(
        f"/api/sessions/{session_id}/guide/region",
        json={
            "status": "provided",
            "region": {"country_code": "ph", "currency": "php"},
        },
    )
    assert supplied.status_code == 200
    assert supplied.json()["region_setup"]["region"]["country_code"] == "PH"


def test_guardrail_blocks_off_topic_and_unsafe_requests(
    guided_api_client: TestClient,
) -> None:
    off_topic = _create_guided_session(
        guided_api_client,
        "Write a poem about a laptop",
    )
    unsafe = _create_guided_session(
        guided_api_client,
        "Which gun should I buy?",
    )

    assert off_topic["guide"]["status"] == "blocked"
    assert off_topic["guide"]["guardrail"]["reason"] == "off_topic"
    assert "shopping decisions" in off_topic["guide"]["guardrail"]["message"]
    assert unsafe["guide"]["status"] == "blocked"
    assert unsafe["guide"]["guardrail"]["reason"] == "unsafe_product"
