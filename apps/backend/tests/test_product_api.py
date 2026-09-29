import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

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
from app.db.repositories.products import ProductRepository
from app.main import create_app
from uuid import UUID


async def _create_tables(settings: Settings) -> None:
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


@pytest.fixture
def product_api_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "product-api.sqlite3",
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
        json={"query": "Need a compact kettle"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user_added_products"] == []
    return body["session_id"]


def test_add_user_product_url_placeholder_persists_in_session_state(
    product_api_client: TestClient,
) -> None:
    session_id = create_session(product_api_client)

    add_response = product_api_client.post(
        f"/api/sessions/{session_id}/products",
        json={
            "url": "https://example.com/products/kettle-1",
            "notes": "This deal looked interesting.",
        },
    )

    assert add_response.status_code == 201
    added_state = add_response.json()
    assert len(added_state["user_added_products"]) == 1
    added = added_state["user_added_products"][0]
    assert added["url"] == "https://example.com/products/kettle-1"
    assert added["input_text"] is None
    assert added["product"] is None
    assert added["notes"] == "This deal looked interesting."

    load_response = product_api_client.get(f"/api/sessions/{session_id}")

    assert load_response.status_code == 200
    loaded_products = load_response.json()["user_added_products"]
    assert len(loaded_products) == 1
    assert loaded_products[0]["candidate_id"] == added["candidate_id"]
    assert loaded_products[0]["url"] == "https://example.com/products/kettle-1"


def test_add_manual_user_product_details_persist_in_session_state(
    product_api_client: TestClient,
) -> None:
    session_id = create_session(product_api_client)

    add_response = product_api_client.post(
        f"/api/sessions/{session_id}/products",
        json={
            "input_text": "I am considering the Acme Mini Kettle.",
            "name": "Acme Mini Kettle",
            "brand": "Acme",
            "model": "Mini",
            "category": "electric kettle",
            "notes": "Manual details only; no extraction yet.",
            "manual_fallback_reason": "user_correction",
            "manual_details": {"price": {"amount": "49.00", "currency": "USD"}},
        },
    )

    assert add_response.status_code == 201
    added_state = add_response.json()
    assert len(added_state["user_added_products"]) == 1
    added = added_state["user_added_products"][0]
    assert added["input_text"] == "I am considering the Acme Mini Kettle."
    assert added["url"] is None
    assert added["product"]["name"] == "Acme Mini Kettle"
    assert added["product"]["brand"] == "Acme"
    assert added["product"]["model"] == "Mini"
    assert added["product"]["category"] == "electric kettle"
    assert added["listing"] is None
    assert added["product"]["source_ids"] == []
    assert added["manual_evidence_status"]["source"] == "unknown"
    assert added["manual_evidence_status"]["price"] == "user_reported"
    assert added["manual_evidence_status"]["seller"] == "unknown"

    load_response = product_api_client.get(f"/api/sessions/{session_id}")

    assert load_response.status_code == 200
    loaded_products = load_response.json()["user_added_products"]
    assert len(loaded_products) == 1
    assert loaded_products[0]["candidate_id"] == added["candidate_id"]
    assert loaded_products[0]["product"]["name"] == "Acme Mini Kettle"


def test_manual_details_require_explicit_fallback_and_research_state(
    product_api_client: TestClient,
) -> None:
    session_id = create_session(product_api_client)
    path = f"/api/sessions/{session_id}/products"
    assert (
        product_api_client.post(
            path, json={"name": "Acme Mini", "brand": "Acme"}
        ).status_code
        == 422
    )
    hint = product_api_client.post(path, json={"input_text": "Acme Mini"})
    assert hint.status_code == 201
    candidate_id = hint.json()["user_added_products"][0]["candidate_id"]
    pending = product_api_client.post(
        path,
        json={
            "fallback_candidate_id": candidate_id,
            "name": "Acme Mini",
            "manual_fallback_reason": "retrieval_insufficient",
        },
    )
    assert pending.status_code == 409
    assert pending.json()["error"]["code"] == "manual_fallback_unavailable"

    async def mark_research_inconclusive(candidate_to_mark: str) -> None:
        settings = product_api_client.app.state.settings
        engine = create_database_engine(settings)
        try:
            session_factory = create_session_factory(engine)
            async with session_factory() as db_session:
                repo = ProductRepository(db_session)
                candidate = await repo.get_user_added_product(
                    UUID(session_id), UUID(candidate_to_mark)
                )
                assert candidate is not None
                await repo.replace_user_added_product(
                    UUID(session_id),
                    candidate.model_copy(update={"research_attempted": True}),
                )
                await db_session.commit()
        finally:
            await engine.dispose()

    asyncio.run(mark_research_inconclusive(candidate_id))
    manual = product_api_client.post(
        path,
        json={
            "fallback_candidate_id": candidate_id,
            "name": "Acme Mini Kettle",
            "manual_fallback_reason": "retrieval_insufficient",
            "manual_details": {"warranty": "Shop says one year"},
        },
    )
    assert manual.status_code == 201
    saved = manual.json()["user_added_products"]
    assert len(saved) == 1
    assert saved[0]["candidate_id"] == candidate_id
    assert saved[0]["manual_evidence_status"]["warranty"] == "user_reported"

    url_hint = product_api_client.post(
        path, json={"url": "https://example.com/products/missing-kettle"}
    )
    assert url_hint.status_code == 201
    url_candidate_id = url_hint.json()["user_added_products"][1]["candidate_id"]
    asyncio.run(mark_research_inconclusive(url_candidate_id))
    unavailable = product_api_client.post(
        path,
        json={
            "fallback_candidate_id": url_candidate_id,
            "name": "Missing Kettle",
            "manual_fallback_reason": "retrieval_unavailable",
        },
    )
    assert unavailable.status_code == 201
    url_fallback = unavailable.json()["user_added_products"][1]
    assert url_fallback["url"] == "https://example.com/products/missing-kettle"
    assert url_fallback["listing"] is None
    assert url_fallback["manual_evidence_status"]["source"] == "unknown"


def test_add_user_product_rejects_missing_session(
    product_api_client: TestClient,
) -> None:
    response = product_api_client.post(
        "/api/sessions/00000000-0000-4000-8000-000000000000/products",
        json={"url": "https://example.com/products/kettle-1"},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "session_not_found"
