from fastapi import APIRouter

from app.api.v1 import health, projects, tasks
from app.core.config import settings

router = APIRouter()

router.include_router(health.router, prefix=settings.API_V1_PREFIX)
router.include_router(projects.router, prefix=settings.API_V1_PREFIX)
router.include_router(tasks.router, prefix=settings.API_V1_PREFIX)
