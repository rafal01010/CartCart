from collections.abc import Awaitable, Callable
from typing import cast
from time import perf_counter
from uuid import uuid4

import logging
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ExceptionHandler

from app.api.errors import (
    REQUEST_ID_HEADER,
    application_exception_handler,
    validation_exception_handler,
)
from app.api.routes.agent_workbench import router as agent_workbench_router
from app.api.router import api_router
from app.core.errors import ApplicationError
from app.core.logging import bind_log_context, configure_logging, reset_log_context
from app.core.settings import (
    EnvironmentMode,
    Settings,
    get_settings,
)
from app.core.telemetry import configure_telemetry


request_logger = logging.getLogger("cartcart.request")


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)
    app = FastAPI(title="CartCart Backend")
    app.state.settings = app_settings
    configure_telemetry(app, app_settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.frontend_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(
        RequestValidationError,
        cast(ExceptionHandler, validation_exception_handler),
    )
    app.add_exception_handler(
        ApplicationError,
        cast(ExceptionHandler, application_exception_handler),
    )
    app.include_router(api_router)
    if _agent_workbench_route_enabled(app_settings):
        app.include_router(agent_workbench_router)

    @app.middleware("http")
    async def add_request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
        request.state.request_id = request_id
        started_at = perf_counter()
        tokens = bind_log_context(request_id=request_id)

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((perf_counter() - started_at) * 1000, 3)
            session_id = _request_context_value(request, "session_id")
            run_id = _request_context_value(request, "run_id")
            request_logger.exception(
                "request_failed",
                extra={
                    "event": "request_failed",
                    "request_id": request_id,
                    "session_id": session_id,
                    "run_id": run_id,
                    "http": {
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": 500,
                        "duration_ms": duration_ms,
                    },
                },
            )
            raise
        finally:
            reset_log_context(tokens)

        response.headers[REQUEST_ID_HEADER] = request_id
        duration_ms = round((perf_counter() - started_at) * 1000, 3)
        session_id = _request_context_value(request, "session_id")
        run_id = _request_context_value(request, "run_id")
        request_logger.info(
            "request_completed",
            extra={
                "event": "request_completed",
                "request_id": request_id,
                "session_id": session_id,
                "run_id": run_id,
                "http": {
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            },
        )
        return response

    return app


def _agent_workbench_route_enabled(settings: Settings) -> bool:
    return settings.agent_workbench_enabled and settings.environment in {
        EnvironmentMode.LOCAL,
        EnvironmentMode.TEST,
        EnvironmentMode.FIXTURE,
    }


def _request_context_value(request: Request, key: str) -> str | None:
    state_value = getattr(request.state, key, None)
    if isinstance(state_value, str) and state_value:
        return state_value

    path_value = request.path_params.get(key)
    if isinstance(path_value, str) and path_value:
        return path_value

    return None


app = create_app()
