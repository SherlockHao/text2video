from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.character import (
    CharacterCreate,
    CharacterImageResponse,
    CharacterResponse,
    CharacterUpdate,
)
from app.dependencies import get_arq_pool, get_db
from app.services.character_service import CharacterService

router = APIRouter(prefix="/characters", tags=["characters"])

# Placeholder user_id until auth is implemented
_DEFAULT_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


@router.get("", response_model=list[CharacterResponse])
async def list_characters(
    tags: str | None = Query(None, description="Comma-separated tags to filter by"),
    db: AsyncSession = Depends(get_db),
) -> list[CharacterResponse]:
    """List user's characters, optionally filtered by tags."""
    service = CharacterService(db)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    characters = await service.list_characters(
        user_id=_DEFAULT_USER_ID, tags=tag_list
    )
    return [CharacterResponse.model_validate(c) for c in characters]


@router.post("", status_code=201, response_model=CharacterResponse)
async def create_character(
    body: CharacterCreate,
    db: AsyncSession = Depends(get_db),
) -> CharacterResponse:
    """Create a new character."""
    service = CharacterService(db)
    character = await service.create_character(
        user_id=_DEFAULT_USER_ID,
        data=body.model_dump(),
    )
    return CharacterResponse.model_validate(character)


@router.get("/{character_id}", response_model=CharacterResponse)
async def get_character(
    character_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> CharacterResponse:
    """Get a single character by ID."""
    service = CharacterService(db)
    character = await service.get_character(character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    return CharacterResponse.model_validate(character)


@router.put("/{character_id}", response_model=CharacterResponse)
async def update_character(
    character_id: UUID,
    body: CharacterUpdate,
    db: AsyncSession = Depends(get_db),
) -> CharacterResponse:
    """Update a character."""
    service = CharacterService(db)
    character = await service.update_character(
        character_id, body.model_dump(exclude_unset=True)
    )
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    return CharacterResponse.model_validate(character)


@router.delete("/{character_id}", status_code=204)
async def delete_character(
    character_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a character."""
    service = CharacterService(db)
    deleted = await service.delete_character(character_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Character not found")


@router.post("/{character_id}/generate-image", status_code=201)
async def generate_character_image(
    character_id: UUID,
    db: AsyncSession = Depends(get_db),
    arq_pool=Depends(get_arq_pool),
) -> dict:
    """Trigger gacha image generation for a character."""
    service = CharacterService(db)
    try:
        task = await service.generate_image(
            character_id=character_id,
            params={},
            arq_pool=arq_pool,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"task_id": str(task.id), "status": task.status}


@router.get(
    "/{character_id}/images",
    response_model=list[CharacterImageResponse],
)
async def list_character_images(
    character_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[CharacterImageResponse]:
    """List gacha image candidates for a character."""
    service = CharacterService(db)
    images = await service.list_images(character_id)
    return [CharacterImageResponse.model_validate(img) for img in images]


@router.post("/{character_id}/images/{image_id}/select", response_model=CharacterResponse)
async def select_character_image(
    character_id: UUID,
    image_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> CharacterResponse:
    """Pick canonical image for a character."""
    service = CharacterService(db)
    try:
        character = await service.select_image(character_id, image_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return CharacterResponse.model_validate(character)
