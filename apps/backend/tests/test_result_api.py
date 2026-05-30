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
from app.db.repositories.results import ResultRepository
from app.db.session import (
    create_database_engine,
    create_session_factory,
    get_db_session,
)
from app.main import create_app
from app.schemas.analysis import (
    ComparisonCriterion,
    ComparisonMatrix,
    ComparisonRow,
    RecommendationBundle,
)
from app.schemas.ids import new_id


async def _create_tables(settings: Settings) -> None:
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


@pytest.fixture
def result_api_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "result-api.sqlite3",
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
        json={"query": "Need a reliable kettle"},
    )

    assert response.status_code == 201
    return response.json()["session_id"]


def create_run(client: TestClient, session_id: str) -> str:
    response = client.post(f"/api/sessions/{session_id}/runs")

    assert response.status_code == 201
    return response.json()["run_id"]


def make_fixture_recommendation(reason: str) -> RecommendationBundle:
    product_id = new_id()
    evidence_id = new_id()
    comparison_matrix = ComparisonMatrix(
        criteria=(ComparisonCriterion(name="fit", weight=1.0),),
        rows=(
            ComparisonRow(
                product_id=product_id,
                scores={"fit": 0.2},
                evidence_ids=(evidence_id,),
                summary="Fixture evidence is too weak for a strong buy.",
            ),
        ),
    )
    return RecommendationBundle(
        no_strong_buy=True,
        no_strong_buy_reason=reason,
        comparison_matrix=comparison_matrix,
        evidence_ids=(evidence_id,),
        source_ids=(new_id(),),
    )


async def save_fixture_result(
    settings: Settings,
    run_id: str,
    recommendation: RecommendationBundle,
) -> None:
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            await ResultRepository(session).save_result_bundle(
                UUID(run_id),
                trust_assessments=(),
                category_analyses=(),
                agent_records=(),
                recommendation_bundle=recommendation,
            )
            await session.commit()
    finally:
        await engine.dispose()


def test_get_session_results_returns_not_ready_for_empty_session(
    result_api_client: TestClient,
) -> None:
    session_id = create_session(result_api_client)

    response = result_api_client.get(f"/api/sessions/{session_id}/results")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "result_not_ready"
    assert body["error"]["details"] == {"session_id": session_id}


def test_get_session_results_returns_latest_persisted_fixture_bundle(
    result_api_client: TestClient,
) -> None:
    session_id = create_session(result_api_client)
    run_id = create_run(result_api_client, session_id)
    first = make_fixture_recommendation("First fixture result is stale.")
    latest = make_fixture_recommendation("Latest fixture result is still too weak.")
    asyncio.run(
        save_fixture_result(result_api_client.app.state.settings, run_id, first)
    )
    asyncio.run(
        save_fixture_result(result_api_client.app.state.settings, run_id, latest)
    )

    response = result_api_client.get(f"/api/sessions/{session_id}/results")

    assert response.status_code == 200
    body = response.json()
    assert body["result_version"]["run_id"] == run_id
    assert body["result_version"]["version"] == 2
    assert body["trust_assessments"] == []
    assert body["category_analyses"] == []
    assert body["agent_records"] == []
    assert body["recommendation_bundle"]["bundle_id"] == str(latest.bundle_id)
    assert body["recommendation_bundle"]["no_strong_buy"] is True
    assert body["recommendation_bundle"]["no_strong_buy_reason"] == (
        "Latest fixture result is still too weak."
    )
    assert body["comparison_matrix"] == body["recommendation_bundle"][
        "comparison_matrix"
    ]
