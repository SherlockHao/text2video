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
async def readiness_check(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Check DB connectivity."""
    try:
        await db.execute(text("SELECT 1"))
        return JSONResponse(content={"status": "ready", "database": "ok"})
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "database": str(exc)},
        )
