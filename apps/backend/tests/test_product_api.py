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
from app.schemas.ids import new_id
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
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


def test_listing_correction_adds_one_candidate_and_refreshes_same_session_result(
    product_api_client: TestClient,
) -> None:
    session_id = create_session(product_api_client)
    first_run = product_api_client.post(f"/api/sessions/{session_id}/runs")
    assert first_run.status_code == 201
    first_result = product_api_client.get(f"/api/sessions/{session_id}/results").json()

    first_add = product_api_client.post(
        f"/api/sessions/{session_id}/products",
        json={"url": "https://shop.example/items/kettle-42?utm_source=one"},
    )
    assert first_add.status_code == 201
    candidate_id = first_add.json()["user_added_products"][0]["candidate_id"]
    duplicate = product_api_client.post(
        f"/api/sessions/{session_id}/products",
        json={"url": "https://shop.example/items/kettle-42?utm_source=two"},
    )
    assert duplicate.status_code == 201
    assert [item["candidate_id"] for item in duplicate.json()["user_added_products"]] == [candidate_id]

    second_run = product_api_client.post(f"/api/sessions/{session_id}/runs")
    assert second_run.status_code == 201
    assert second_run.json()["run_id"] != first_run.json()["run_id"]
    refreshed = product_api_client.get(f"/api/sessions/{session_id}/results").json()
    assert refreshed["result_version"]["run_id"] == second_run.json()["run_id"]
    assert refreshed["result_version"]["run_id"] != first_result["result_version"]["run_id"]
    candidate = product_api_client.get(f"/api/sessions/{session_id}").json()["user_added_products"][0]
    assert candidate["research_attempted"] is True
    assert any(
        source["provider"]["raw"].get("user_added_candidate_id") == candidate_id
        for source in refreshed["source_snapshots"]
    )


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


def test_manual_fallback_reruns_in_same_session_without_a_verified_offer(
    product_api_client: TestClient,
) -> None:
    session_id = create_session(product_api_client)
    path = f"/api/sessions/{session_id}/products"
    added = product_api_client.post(path, json={"input_text": "Acme Mini Kettle"})
    candidate_id = added.json()["user_added_products"][0]["candidate_id"]
    first_run = product_api_client.post(f"/api/sessions/{session_id}/runs")
    assert first_run.status_code == 201
    researched = product_api_client.get(f"/api/sessions/{session_id}").json()["user_added_products"][0]
    assert researched["research_attempted"] is True
    assert researched["listing"] is None

    saved = product_api_client.post(path, json={
        "fallback_candidate_id": candidate_id,
        "input_text": "Acme Mini Kettle",
        "name": "Acme Mini Kettle",
        "manual_fallback_reason": "retrieval_insufficient",
        "manual_details": {"seller": "Local shop", "price": {"amount": "49.00", "currency": "USD"}},
    })
    assert saved.status_code == 201
    assert len(saved.json()["user_added_products"]) == 1
    assert saved.json()["user_added_products"][0]["candidate_id"] == candidate_id

    second_run = product_api_client.post(f"/api/sessions/{session_id}/runs")
    assert second_run.status_code == 201
    assert second_run.json()["run_id"] != first_run.json()["run_id"]
    result = product_api_client.get(f"/api/sessions/{session_id}/results").json()
    assert result["result_version"]["run_id"] == second_run.json()["run_id"]
    assert result["recommendation_bundle"]["no_strong_buy"] is True
    candidate = product_api_client.get(f"/api/sessions/{session_id}").json()["user_added_products"][0]
    assert candidate["candidate_id"] == candidate_id
    assert candidate["manual_evidence_status"]["seller"] == "user_reported"
    assert candidate["manual_evidence_status"]["warranty"] == "unknown"
    assert candidate["listing"] is None
    manual_products = [item for item in result["products"] if item["name"] == "Acme Mini Kettle"]
    assert manual_products
    assert not manual_products[0]["source_ids"]
    assert all(item["product_id"] != manual_products[0]["product_id"] for item in result["listings"])
    assert any(
        row["product_id"] == manual_products[0]["product_id"] and row["listing_id"] is None
        for row in result["comparison_matrix"]["rows"]
    )
    assert any(item["product_id"] == manual_products[0]["product_id"] and item["listing_id"] is None for item in result["shortlist"])
    assert result["considered_products"][0]["status"] == "manual"
    assert result["considered_products"][0]["candidate"]["candidate_id"] == candidate_id


def test_wrong_matched_product_can_be_corrected_on_the_same_candidate(
    product_api_client: TestClient,
) -> None:
    session_id = create_session(product_api_client)
    path = f"/api/sessions/{session_id}/products"
    added = product_api_client.post(path, json={"input_text": "Acme Mini Kettle"})
    candidate_id = added.json()["user_added_products"][0]["candidate_id"]

    async def mark_wrong_match() -> None:
        settings = product_api_client.app.state.settings
        engine = create_database_engine(settings)
        try:
            async with create_session_factory(engine)() as db_session:
                repo = ProductRepository(db_session)
                candidate = await repo.get_user_added_product(UUID(session_id), UUID(candidate_id))
                assert candidate is not None
                product = CanonicalProduct(name="Wrong Kettle")
                listing = ProductListing(
                    product_id=product.product_id,
                    title="Wrong Kettle listing",
                    url="https://shop.example/wrong-kettle",
                    seller=SellerProfile(seller_name="Unknown seller"),
                    source_ids=(new_id(),),
                )
                await repo.replace_user_added_product(UUID(session_id), candidate.model_copy(update={
                    "product": product, "listing": listing, "research_attempted": True,
                }))
                await db_session.commit()
        finally:
            await engine.dispose()

    asyncio.run(mark_wrong_match())
    corrected = product_api_client.post(path, json={
        "fallback_candidate_id": candidate_id,
        "input_text": "Acme Mini Kettle",
        "name": "Acme Mini Kettle",
        "manual_fallback_reason": "user_correction",
        "manual_details": {"warranty": "Shop says one year"},
    })
    assert corrected.status_code == 201
    candidate = corrected.json()["user_added_products"][0]
    assert candidate["candidate_id"] == candidate_id
    assert candidate["product"]["name"] == "Acme Mini Kettle"
    assert candidate["listing"] is None
    assert candidate["manual_evidence_status"]["warranty"] == "user_reported"
    assert candidate["manual_evidence_status"]["source"] == "unknown"
