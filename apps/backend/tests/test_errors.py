from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.errors import REQUEST_ID_HEADER
from app.core.errors import ApplicationError
from app.core.settings import Settings
from app.main import create_app


class ExamplePayload(BaseModel):
    quantity: int


def make_error_test_app() -> FastAPI:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    app = create_app(settings)

    @app.post("/test/validation")
    async def validation_route(payload: ExamplePayload) -> dict[str, int]:
        return {"quantity": payload.quantity}

    @app.get("/test/application-error")
    async def application_error_route() -> None:
        raise ApplicationError(
            "candidate_conflict",
            "Candidate conflict.",
            status_code=409,
            details={"candidate_id": "test-candidate"},
        )

    return app


def make_test_client() -> TestClient:
    return TestClient(make_error_test_app())


def assert_error_envelope(body: dict[str, Any], code: str, request_id: str) -> None:
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == request_id
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["message"]


def test_request_id_is_returned_on_success() -> None:
    client = make_test_client()

    response = client.post("/test/validation", json={"quantity": 3})

    assert response.status_code == 200
    UUID(response.headers[REQUEST_ID_HEADER])


def test_validation_error_uses_error_envelope_and_request_id() -> None:
    client = make_test_client()

    response = client.post(
        "/test/validation",
        json={"quantity": "many"},
        headers={REQUEST_ID_HEADER: "request-test-123"},
    )

    assert response.status_code == 422
    assert response.headers[REQUEST_ID_HEADER] == "request-test-123"
    body = response.json()
    assert_error_envelope(body, "validation_error", "request-test-123")
    assert body["error"]["details"][0]["loc"] == ["body", "quantity"]


def test_application_error_uses_error_envelope_and_request_id() -> None:
    client = make_test_client()

    response = client.get(
        "/test/application-error",
        headers={REQUEST_ID_HEADER: "request-test-456"},
    )

    assert response.status_code == 409
    assert response.headers[REQUEST_ID_HEADER] == "request-test-456"
    body = response.json()
    assert_error_envelope(body, "candidate_conflict", "request-test-456")
    assert body["error"]["message"] == "Candidate conflict."
    assert body["error"]["details"] == {"candidate_id": "test-candidate"}
