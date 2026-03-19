from fastapi import APIRouter

from app.api.v1 import characters, health, projects, scripts, shots, storyboards, tasks, tts
from app.core.config import settings

router = APIRouter()

router.include_router(health.router, prefix=settings.API_V1_PREFIX)
router.include_router(projects.router, prefix=settings.API_V1_PREFIX)
router.include_router(scripts.router, prefix=settings.API_V1_PREFIX)
router.include_router(storyboards.router, prefix=settings.API_V1_PREFIX)
router.include_router(tasks.router, prefix=settings.API_V1_PREFIX)
router.include_router(characters.router, prefix=settings.API_V1_PREFIX)
router.include_router(shots.router, prefix=settings.API_V1_PREFIX)
router.include_router(tts.router, prefix=settings.API_V1_PREFIX)
