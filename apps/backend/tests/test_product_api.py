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
from app.main import create_app


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

    load_response = product_api_client.get(f"/api/sessions/{session_id}")

    assert load_response.status_code == 200
    loaded_products = load_response.json()["user_added_products"]
    assert len(loaded_products) == 1
    assert loaded_products[0]["candidate_id"] == added["candidate_id"]
    assert loaded_products[0]["product"]["name"] == "Acme Mini Kettle"


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
