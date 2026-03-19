import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.script import (
    SensitiveCheckRequest,
    SensitiveCheckResponse,
    SensitiveWordHitItem,
    ScriptValidationRequest,
    ScriptValidationResponse,
)
from app.dependencies import get_db
from app.models.sensitive_word import SensitiveWordHit
from app.services.script_service import check_sensitive_words, validate_script_input

logger = logging.getLogger(__name__)
router = APIRouter(tags=["scripts"])

# Threshold: if hit_count >= this value, the text is considered blocked
_BLOCK_THRESHOLD = 1


@router.post(
    "/projects/{project_id}/script/check",
    response_model=SensitiveCheckResponse,
)
async def check_project_script(
    project_id: UUID,
    body: SensitiveCheckRequest,
    db: AsyncSession = Depends(get_db),
) -> SensitiveCheckResponse:
    """Run sensitive word check on the provided text for a project."""
    raw_hits = check_sensitive_words(body.text)

    hit_items = [
        SensitiveWordHitItem(
            keyword=h["keyword"],
            count=h["count"],
            positions=h["positions"],
            context=h["context"],
        )
        for h in raw_hits
    ]

    # Persist hits to DB (best-effort, don't fail the check if DB write fails)
    if raw_hits:
        try:
            record = SensitiveWordHit(
                project_id=project_id,
                text_segment=body.text[:500],
                matched_keywords=[h["keyword"] for h in raw_hits],
                action_taken="blocked" if len(raw_hits) >= _BLOCK_THRESHOLD else "warned",
            )
            db.add(record)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.warning("Failed to persist sensitive word hit for project %s", project_id)

    hit_count = len(raw_hits)
    return SensitiveCheckResponse(
        has_hits=hit_count > 0,
        hit_count=hit_count,
        hits=hit_items,
        is_blocked=hit_count >= _BLOCK_THRESHOLD,
    )


@router.post(
    "/scripts/validate",
    response_model=ScriptValidationResponse,
)
async def validate_script(
    body: ScriptValidationRequest,
) -> ScriptValidationResponse:
    """Validate script text input (length, emptiness)."""
    result = validate_script_input(body.text)
    return ScriptValidationResponse(**result)
