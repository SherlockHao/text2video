import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.models.character_image import CharacterImage
from app.models.task import AITask
from app.repositories.character_image_repo import CharacterImageRepository
from app.repositories.character_repo import CharacterRepository
from app.repositories.task_repo import TaskRepository

logger = logging.getLogger(__name__)


class CharacterService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.character_repo = CharacterRepository(session)
        self.char_image_repo = CharacterImageRepository(session)
        self.task_repo = TaskRepository(session)

    async def create_character(self, user_id: UUID, data: dict) -> Character:
        """Create a new character for the given user."""
        data["user_id"] = user_id
        character = await self.character_repo.create(data)
        await self.session.commit()
        return character

    async def list_characters(
        self, user_id: UUID, tags: list[str] | None = None
    ) -> list[Character]:
        """List characters for a user, optionally filtered by tags."""
        filters = None
        if tags:
            filters = {"tags": tags}
        return await self.character_repo.get_by_user_id(user_id, filters=filters)

    async def get_character(self, character_id: UUID) -> Character | None:
        """Get a single character by ID."""
        return await self.character_repo.get_by_id(character_id)

    async def update_character(self, character_id: UUID, data: dict) -> Character | None:
        """Update a character's fields."""
        character = await self.character_repo.update(character_id, data)
        if character:
            await self.session.commit()
        return character

    async def delete_character(self, character_id: UUID) -> bool:
        """Soft-delete a character."""
        deleted = await self.character_repo.soft_delete(character_id)
        if deleted:
            await self.session.commit()
        return deleted

    async def generate_image(
        self, character_id: UUID, params: dict, arq_pool=None
    ) -> AITask:
        """Trigger gacha image generation for a character.

        Creates AITask with type=image_generation, stores character_id in input_params.
        """
        character = await self.character_repo.get_by_id(character_id)
        if character is None:
            raise ValueError(f"Character {character_id} not found")

        # Create AITask for image generation
        task = await self.task_repo.create(
            {
                "project_id": params.get("project_id", "00000000-0000-0000-0000-000000000000"),
                "task_type": "image_generation",
                "status": "pending",
                "provider_name": "jimeng",
                "input_params": {
                    "character_id": str(character_id),
                    "character_name": character.name,
                    "visual_style": character.visual_style,
                    "seed": params.get("seed", -1),
                },
            }
        )

        # Enqueue to arq
        if arq_pool is not None:
            await arq_pool.enqueue_job("process_ai_task", str(task.id))

        await self.session.commit()
        return task

    async def list_images(self, character_id: UUID) -> list[CharacterImage]:
        """List all gacha image candidates for a character."""
        return await self.char_image_repo.get_by_character_id(character_id)

    async def select_image(self, character_id: UUID, image_id: UUID) -> Character:
        """Select an image as the canonical reference for a character.

        Updates character.reference_image_id and sets is_selected on the CharacterImage.
        """
        character = await self.character_repo.get_by_id(character_id)
        if character is None:
            raise ValueError(f"Character {character_id} not found")

        image = await self.char_image_repo.get_by_id(image_id)
        if image is None:
            raise ValueError(f"CharacterImage {image_id} not found")

        # Deselect all existing images for this character
        images = await self.char_image_repo.get_by_character_id(character_id)
        for img in images:
            if img.is_selected:
                img.is_selected = False
        await self.session.flush()

        # Select the new image
        image.is_selected = True
        character.reference_image_id = image.asset_id
        character.seed_value = image.generation_seed

        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(character)
        return character
