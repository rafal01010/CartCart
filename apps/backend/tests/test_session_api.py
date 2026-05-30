import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID, uuid4

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
def session_api_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "session-api.sqlite3",
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


def test_create_session_persists_and_loads_session(
    session_api_client: TestClient,
) -> None:
    create_response = session_api_client.post(
        "/api/sessions",
        json={
            "query": "Need a portable monitor for travel",
            "region": {
                "region": {"country_code": "us", "currency": "usd"},
                "source": "user_provided",
            },
            "budget": {
                "amount": {"amount": "250.00", "currency": "usd"},
                "mode": "preferred",
            },
            "preferences": [
                {
                    "text": "Prefer USB-C single cable power.",
                    "mode": "soft",
                }
            ],
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    session_id = UUID(created["session_id"])
    assert created["original_input"]["query"] == "Need a portable monitor for travel"
    assert created["current_brief"]["original_query"] == (
        created["original_input"]["query"]
    )
    assert created["current_brief"]["region"]["region"]["country_code"] == "US"
    assert created["current_brief"]["budget"]["amount"]["currency"] == "USD"
    assert created["current_brief"]["preferences"][0]["text"] == (
        "Prefer USB-C single cable power."
    )

    load_response = session_api_client.get(f"/api/sessions/{session_id}")

    assert load_response.status_code == 200
    loaded = load_response.json()
    assert loaded["session_id"] == str(session_id)
    assert loaded["created_at"] == created["created_at"]
    assert loaded["updated_at"] == created["updated_at"]
    assert loaded["current_brief"] == created["current_brief"]


def test_update_session_brief_persists_changes(
    session_api_client: TestClient,
) -> None:
    create_response = session_api_client.post(
        "/api/sessions",
        json={"query": "Need headphones for work calls"},
    )
    assert create_response.status_code == 201
    created = create_response.json()

    update_response = session_api_client.patch(
        f"/api/sessions/{created['session_id']}/brief",
        json={
            "category": "headphones",
            "category_source": "user_provided",
            "budget": {
                "amount": {"amount": "180.00", "currency": "USD"},
                "mode": "hard_cap",
            },
            "constraints": [
                {
                    "text": "Must have a clear microphone.",
                    "mode": "hard",
                }
            ],
        },
    )

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["session_id"] == created["session_id"]
    assert updated["original_input"] == created["original_input"]
    assert updated["created_at"] == created["created_at"]
    assert updated["updated_at"] >= created["updated_at"]
    assert updated["current_brief"]["original_query"] == (
        "Need headphones for work calls"
    )
    assert updated["current_brief"]["category"] == "headphones"
    assert updated["current_brief"]["category_source"] == "user_provided"
    assert updated["current_brief"]["budget"]["amount"]["amount"] == "180.00"
    assert updated["current_brief"]["constraints"][0]["text"] == (
        "Must have a clear microphone."
    )

    load_response = session_api_client.get(f"/api/sessions/{created['session_id']}")

    assert load_response.status_code == 200
    assert load_response.json()["current_brief"] == updated["current_brief"]

    clear_response = session_api_client.patch(
        f"/api/sessions/{created['session_id']}/brief",
        json={"category": None},
    )

    assert clear_response.status_code == 200
    cleared_brief = clear_response.json()["current_brief"]
    assert cleared_brief["category"] is None
    assert cleared_brief["category_source"] is None


def test_session_api_returns_not_found_for_missing_session(
    session_api_client: TestClient,
) -> None:
    response = session_api_client.get(f"/api/sessions/{uuid4()}")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "session_not_found"
    assert body["error"]["message"] == "Session not found."


def test_session_api_validates_create_request(
    session_api_client: TestClient,
) -> None:
    response = session_api_client.post("/api/sessions", json={"query": ""})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"][0]["loc"] == ["body", "query"]


def test_session_api_validates_path_session_id(
    session_api_client: TestClient,
) -> None:
    response = session_api_client.get("/api/sessions/not-a-uuid")

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"][0]["loc"] == ["path", "session_id"]


def test_session_api_validates_brief_patch(
    session_api_client: TestClient,
) -> None:
    create_response = session_api_client.post(
        "/api/sessions",
        json={"query": "Need a quiet fan"},
    )
    assert create_response.status_code == 201

    response = session_api_client.patch(
        f"/api/sessions/{create_response.json()['session_id']}/brief",
        json={"category": "fan"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "category_source is required" in body["error"]["details"][0]["msg"]
