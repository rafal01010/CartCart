from fastapi import APIRouter, Request

from app.agents.workbench import (
    AgentWorkbenchCatalogResponse,
    AgentWorkbenchError,
    AgentWorkbenchRunRequest,
    AgentWorkbenchRunResult,
    AgentWorkbenchRunner,
)
from app.core.errors import ApplicationError
from app.core.settings import Settings


router = APIRouter(
    prefix="/internal/agent-workbench",
    tags=["internal-agent-workbench"],
    include_in_schema=False,
)

_LOCAL_CLIENT_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


@router.get("")
async def list_agent_workbench(request: Request) -> AgentWorkbenchCatalogResponse:
    _require_local_client(request)
    runner = _runner_for_request(request)
    try:
        return runner.catalog_response()
    except AgentWorkbenchError as exc:
        raise _application_error(exc) from exc


@router.post("/runs")
async def run_agent_workbench(
    run_request: AgentWorkbenchRunRequest,
    request: Request,
) -> AgentWorkbenchRunResult:
    _require_local_client(request)
    runner = _runner_for_request(request)
    try:
        return await runner.run(run_request)
    except AgentWorkbenchError as exc:
        raise _application_error(exc) from exc


def _runner_for_request(request: Request) -> AgentWorkbenchRunner:
    settings: Settings = request.app.state.settings
    return AgentWorkbenchRunner(settings)


def _require_local_client(request: Request) -> None:
    client_host = request.client.host if request.client is not None else None
    if client_host not in _LOCAL_CLIENT_HOSTS:
        raise ApplicationError(
            "agent_workbench_local_only",
            "The isolated agent workbench is available only from a local development client.",
            status_code=404,
        )


def _application_error(exc: AgentWorkbenchError) -> ApplicationError:
    return ApplicationError(
        exc.code,
        exc.message,
        status_code=exc.status_code,
        details=exc.details,
    )
