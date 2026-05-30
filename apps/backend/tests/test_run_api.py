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
from app.db.repositories.runs import RunRepository
from app.db.session import (
    create_database_engine,
    create_session_factory,
    get_db_session,
)
from app.main import create_app
from app.schemas.runs import RunStage, RunStatus


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


async def append_run_events(settings: Settings, run_id: str) -> None:
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repository = RunRepository(session)
            await repository.append_event(
                UUID(run_id),
                stage=RunStage.INTAKE,
                status=RunStatus.RUNNING,
                message="Intake started.",
            )
            await repository.append_event(
                UUID(run_id),
                stage=RunStage.QUERY_PLANNING,
                status=RunStatus.RUNNING,
                message="Query planning started.",
            )
            await session.commit()
    finally:
        await engine.dispose()


def parse_sse_payloads(body: str) -> list[dict[str, str]]:
    payloads: list[dict[str, str]] = []
    for raw_event in body.strip().split("\n\n"):
        payload: dict[str, str] = {}
        for line in raw_event.splitlines():
            key, value = line.split(": ", maxsplit=1)
            payload[key] = value
        payloads.append(payload)
    return payloads


def test_create_run_records_pending_stub_run(run_api_client: TestClient) -> None:
    session_id = create_session(run_api_client)

    response = run_api_client.post(f"/api/sessions/{session_id}/runs")

    assert response.status_code == 201
    body = response.json()
    UUID(body["run_id"])
    assert body["session_id"] == session_id
    assert body["status"] == "pending"
    assert body["current_stage"] is None
    assert body["started_at"] is None
    assert body["completed_at"] is None
    assert body["error"] is None


def test_create_run_rejects_invalid_session(run_api_client: TestClient) -> None:
    session_id = uuid4()

    response = run_api_client.post(f"/api/sessions/{session_id}/runs")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "session_not_found"
    assert body["error"]["details"] == {"session_id": str(session_id)}


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
    asyncio.run(append_run_events(run_api_client.app.state.settings, run_id))

    with run_api_client.stream(
        "GET",
        f"/api/sessions/{session_id}/runs/{run_id}/events",
    ) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    payloads = parse_sse_payloads(body)
    assert [payload["id"] for payload in payloads] == ["0", "1"]
    assert [payload["event"] for payload in payloads] == [
        "run_event",
        "run_event",
    ]
    assert '"sequence":0' in payloads[0]["data"]
    assert '"stage":"intake"' in payloads[0]["data"]
    assert '"message":"Intake started."' in payloads[0]["data"]
    assert '"sequence":1' in payloads[1]["data"]
    assert '"stage":"query_planning"' in payloads[1]["data"]
    assert '"message":"Query planning started."' in payloads[1]["data"]
