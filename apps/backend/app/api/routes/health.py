from typing import Any

from fastapi import APIRouter, Request

from app.core.settings import Settings


router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    provider_warnings = settings.provider_readiness_warnings()
    return {
        "status": "ready",
        "checks": {
            "configuration": "warning" if provider_warnings else "ok",
            "data_dir": str(settings.resolved_data_dir),
            "providers": "warning" if provider_warnings else "ok",
        },
        "warnings": [
            warning.model_dump(mode="json") for warning in provider_warnings
        ],
    }
