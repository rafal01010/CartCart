from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.guided_intake import router as guided_intake_router
from app.api.routes.products import router as products_router
from app.api.routes.refinements import router as refinements_router
from app.api.routes.results import router as results_router
from app.api.routes.runs import router as runs_router
from app.api.routes.sessions import router as sessions_router


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(guided_intake_router)
api_router.include_router(sessions_router)
api_router.include_router(runs_router)
api_router.include_router(results_router)
api_router.include_router(products_router)
api_router.include_router(refinements_router)
