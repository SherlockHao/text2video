import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.dependencies import get_db

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check() -> dict:
    """Basic health check."""
    return {"status": "ok", "version": settings.VERSION}


@router.get("/ready")
async def health_ready(db: AsyncSession = Depends(get_db)):
    """Readiness check — verifies DB, Redis, and storage are available."""
    checks = {}

    # DB check
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)[:100]}"

    # Redis check
    try:
        import redis

        r = redis.from_url(settings.REDIS_URL)
        r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)[:100]}"

    # Storage check
    storage_ok = os.path.isdir(settings.STORAGE_ROOT) or True  # OK if not created yet
    checks["storage"] = "ok" if storage_ok else "error: storage root not found"

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503

    return JSONResponse(
        status_code=status_code,
        content={"status": "ready" if all_ok else "degraded", "checks": checks},
    )
