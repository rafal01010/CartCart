import json
import logging
import sys
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, TextIO


_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_session_id: ContextVar[str | None] = ContextVar("session_id", default=None)
_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)

_LOG_RECORD_BUILTINS = set(logging.makeLogRecord({}).__dict__)
_SAFE_EXTRA_FIELDS = {"event", "http"}


class StructuredJsonFormatter(logging.Formatter):
    """Format application logs as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = _record_value(record, "request_id") or _request_id.get()
        session_id = _record_value(record, "session_id") or _session_id.get()
        run_id = _record_value(record, "run_id") or _run_id.get()

        if request_id:
            payload["request_id"] = request_id
        if session_id:
            payload["session_id"] = session_id
        if run_id:
            payload["run_id"] = run_id

        for field in _SAFE_EXTRA_FIELDS:
            value = _record_value(record, field)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = _exception_payload(record.exc_info)

        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(level: str = "INFO", stream: TextIO | None = None) -> None:
    handler = _get_or_create_handler(stream or sys.stdout)
    handler.setLevel(level.upper())
    handler.setFormatter(StructuredJsonFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level.upper())

    logging.getLogger("cartcart").setLevel(level.upper())

    for logger_name in ("uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.setLevel(level.upper())
        logger.propagate = True

    logging.getLogger("uvicorn.access").disabled = True


def bind_log_context(
    *, request_id: str, session_id: str | None = None, run_id: str | None = None
) -> tuple[Any, Any, Any]:
    return (
        _request_id.set(request_id),
        _session_id.set(session_id),
        _run_id.set(run_id),
    )


def reset_log_context(tokens: tuple[Any, Any, Any]) -> None:
    request_id_token, session_id_token, run_id_token = tokens
    _run_id.reset(run_id_token)
    _session_id.reset(session_id_token)
    _request_id.reset(request_id_token)


def _get_or_create_handler(stream: TextIO) -> logging.Handler:
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if getattr(handler, "_cartcart_structured", False):
            return handler

    handler = logging.StreamHandler(stream)
    handler._cartcart_structured = True  # type: ignore[attr-defined]
    root_logger.addHandler(handler)
    return handler


def _record_value(record: logging.LogRecord, field: str) -> Any | None:
    if field in _LOG_RECORD_BUILTINS:
        return None
    return getattr(record, field, None)


def _exception_payload(
    exc_info: tuple[type[BaseException], BaseException, TracebackType | None]
    | tuple[None, None, None],
) -> dict[str, Any]:
    exc_type, exc_value, exc_tb = exc_info
    if exc_type is None or exc_value is None:
        return {}

    return {
        "type": exc_type.__name__,
        "message": str(exc_value),
        "traceback": traceback.format_exception(exc_type, exc_value, exc_tb),
    }
