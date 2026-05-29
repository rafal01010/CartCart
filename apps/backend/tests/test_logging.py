import json
import logging
from io import StringIO
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import REQUEST_ID_HEADER
from app.core.logging import StructuredJsonFormatter
from app.core.settings import Settings
from app.main import create_app


def make_logging_test_app() -> FastAPI:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    app = create_app(settings)

    @app.get("/test/sessions/{session_id}/runs/{run_id}")
    async def session_run_route(session_id: str, run_id: str) -> dict[str, str]:
        return {"session_id": session_id, "run_id": run_id}

    @app.get("/test/failure")
    async def failure_route() -> None:
        raise RuntimeError("example failure")

    return app


def capture_request_logs() -> tuple[StringIO, logging.Handler]:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredJsonFormatter())

    logger = logging.getLogger("cartcart.request")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return stream, handler


def parse_log_lines(stream: StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_request_log_is_structured_and_omits_sensitive_defaults() -> None:
    stream, handler = capture_request_logs()
    logger = logging.getLogger("cartcart.request")

    try:
        client = TestClient(make_logging_test_app())
        response = client.get(
            "/test/sessions/session-123/runs/run-456?api_key=secret",
            headers={
                REQUEST_ID_HEADER: "request-log-123",
                "Authorization": "Bearer secret",
            },
        )
    finally:
        logger.removeHandler(handler)

    assert response.status_code == 200
    records = parse_log_lines(stream)
    assert len(records) == 1

    record = records[0]
    assert record["timestamp"]
    assert record["level"] == "INFO"
    assert record["logger"] == "cartcart.request"
    assert record["event"] == "request_completed"
    assert record["request_id"] == "request-log-123"
    assert record["session_id"] == "session-123"
    assert record["run_id"] == "run-456"
    assert record["http"]["method"] == "GET"
    assert record["http"]["path"] == "/test/sessions/session-123/runs/run-456"
    assert record["http"]["status_code"] == 200
    assert "duration_ms" in record["http"]

    serialized = json.dumps(record)
    assert "secret" not in serialized
    assert "headers" not in record["http"]
    assert "query" not in record["http"]
    assert "body" not in record["http"]


def test_unhandled_exception_log_includes_exception_fields() -> None:
    stream, handler = capture_request_logs()
    logger = logging.getLogger("cartcart.request")

    try:
        client = TestClient(make_logging_test_app(), raise_server_exceptions=False)
        response = client.get(
            "/test/failure",
            headers={REQUEST_ID_HEADER: "request-log-500"},
        )
    finally:
        logger.removeHandler(handler)

    assert response.status_code == 500
    records = parse_log_lines(stream)
    assert len(records) == 1

    record = records[0]
    assert record["level"] == "ERROR"
    assert record["event"] == "request_failed"
    assert record["request_id"] == "request-log-500"
    assert record["http"]["status_code"] == 500
    assert record["exception"]["type"] == "RuntimeError"
    assert record["exception"]["message"] == "example failure"
