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
    return {
        "status": "ready",
        "checks": {
            "configuration": "ok",
            "data_dir": str(settings.resolved_data_dir),
        },
    }
