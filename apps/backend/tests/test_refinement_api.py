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
from app.db.repositories.refinements import RefinementRepository
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
def refinement_api_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "refinement-api.sqlite3",
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
        json={"query": "Need quiet headphones"},
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
                scores={"fit": 0.3},
                evidence_ids=(evidence_id,),
                summary=reason,
            ),
        ),
    )
    return RecommendationBundle(
        no_strong_buy=True,
        no_strong_buy_reason=reason,
        comparison_matrix=comparison_matrix,
        evidence_ids=(evidence_id,),
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


async def load_result_version_and_refinement(
    settings: Settings,
    original_run_id: str,
    refinement_run_id: str,
) -> tuple[int, str, int, str]:
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            result_repository = ResultRepository(session)
            original = await result_repository.load_latest_result_bundle(
                UUID(original_run_id)
            )
            refined = await result_repository.load_latest_result_bundle(
                UUID(refinement_run_id)
            )
            refinement = await RefinementRepository(session).get_for_run(
                UUID(refinement_run_id)
            )
    finally:
        await engine.dispose()

    assert original is not None
    assert refined is not None
    assert refinement is not None
    return (
        original.result_version.version,
        original.recommendation_bundle.no_strong_buy_reason or "",
        refined.result_version.version,
        refinement.instruction,
    )


def test_create_refinement_stores_request_and_creates_new_stub_run(
    refinement_api_client: TestClient,
) -> None:
    session_id = create_session(refinement_api_client)

    response = refinement_api_client.post(
        f"/api/sessions/{session_id}/refinements",
        json={
            "instruction": "Tighten the budget and prioritize noise cancellation.",
            "budget": {
                "amount": {"amount": "200.00", "currency": "USD"},
                "mode": "hard_cap",
            },
            "preferences": [
                {
                    "text": "Prefer strong active noise cancellation.",
                    "mode": "soft",
                }
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    UUID(body["refinement"]["refinement_id"])
    assert body["refinement"]["session_id"] == session_id
    assert body["refinement"]["run_id"] == body["run"]["run_id"]
    assert body["refinement"]["instruction"] == (
        "Tighten the budget and prioritize noise cancellation."
    )
    assert body["run"]["session_id"] == session_id
    assert body["run"]["status"] == "pending"
    assert body["run"]["current_stage"] is None


def test_refinement_run_result_version_does_not_overwrite_original(
    refinement_api_client: TestClient,
) -> None:
    session_id = create_session(refinement_api_client)
    original_run_id = create_run(refinement_api_client, session_id)
    original_result = make_fixture_recommendation("Original result remains saved.")
    refined_result = make_fixture_recommendation("Refined result is separate.")
    asyncio.run(
        save_fixture_result(
            refinement_api_client.app.state.settings,
            original_run_id,
            original_result,
        )
    )

    refinement_response = refinement_api_client.post(
        f"/api/sessions/{session_id}/refinements",
        json={"instruction": "Prefer cheaper options."},
    )
    assert refinement_response.status_code == 201
    refinement_run_id = refinement_response.json()["run"]["run_id"]
    asyncio.run(
        save_fixture_result(
            refinement_api_client.app.state.settings,
            refinement_run_id,
            refined_result,
        )
    )

    original_version, original_reason, refined_version, instruction = asyncio.run(
        load_result_version_and_refinement(
            refinement_api_client.app.state.settings,
            original_run_id,
            refinement_run_id,
        )
    )

    assert original_version == 1
    assert original_reason == "Original result remains saved."
    assert refined_version == 1
    assert instruction == "Prefer cheaper options."


def test_create_refinement_rejects_missing_session(
    refinement_api_client: TestClient,
) -> None:
    response = refinement_api_client.post(
        "/api/sessions/00000000-0000-4000-8000-000000000000/refinements",
        json={"instruction": "Prefer cheaper options."},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "session_not_found"
