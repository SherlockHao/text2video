"""Tests for CharacterService."""

import uuid
from unittest.mock import AsyncMock

import pytest


async def test_create_character(db_session, sample_user):
    """create_character should create a character with correct fields."""
    from app.services.character_service import CharacterService

    service = CharacterService(db_session)
    character = await service.create_character(
        user_id=sample_user.id,
        data={
            "name": "Hero",
            "description": "The main protagonist",
            "tags": ["hero", "male"],
            "visual_style": "manga",
        },
    )

    assert character is not None
    assert character.name == "Hero"
    assert character.description == "The main protagonist"
    assert character.tags == ["hero", "male"]
    assert character.visual_style == "manga"
    assert character.user_id == sample_user.id


async def test_list_characters(db_session, sample_user):
    """list_characters should return all characters for a user."""
    from app.services.character_service import CharacterService

    service = CharacterService(db_session)
    await service.create_character(
        user_id=sample_user.id,
        data={"name": "Char A", "tags": ["a"]},
    )
    await service.create_character(
        user_id=sample_user.id,
        data={"name": "Char B", "tags": ["b"]},
    )

    characters = await service.list_characters(user_id=sample_user.id)
    assert len(characters) == 2
    names = {c.name for c in characters}
    assert "Char A" in names
    assert "Char B" in names


async def test_list_characters_with_tags(db_session, sample_user):
    """list_characters with tags filter should return only matching characters.

    Note: JSONB @> operator is PostgreSQL-specific. This test verifies the
    service path works; the actual filtering is skipped on SQLite.
    We mark it as xfail for SQLite environments.
    """
    import sqlalchemy

    from app.services.character_service import CharacterService

    service = CharacterService(db_session)
    await service.create_character(
        user_id=sample_user.id,
        data={"name": "Tagged", "tags": ["hero", "male"]},
    )
    await service.create_character(
        user_id=sample_user.id,
        data={"name": "Other", "tags": ["villain"]},
    )

    try:
        characters = await service.list_characters(
            user_id=sample_user.id, tags=["hero"]
        )
    except sqlalchemy.exc.OperationalError:
        pytest.skip("JSONB @> operator not supported on SQLite")

    assert len(characters) == 1
    assert characters[0].name == "Tagged"


async def test_update_character(db_session, sample_user):
    """update_character should update the specified fields."""
    from app.services.character_service import CharacterService

    service = CharacterService(db_session)
    character = await service.create_character(
        user_id=sample_user.id,
        data={"name": "Original Name"},
    )

    updated = await service.update_character(
        character.id, {"name": "Updated Name", "description": "New description"}
    )

    assert updated is not None
    assert updated.name == "Updated Name"
    assert updated.description == "New description"


async def test_delete_character(db_session, sample_user):
    """delete_character should soft-delete the character."""
    from app.services.character_service import CharacterService

    service = CharacterService(db_session)
    character = await service.create_character(
        user_id=sample_user.id,
        data={"name": "ToDelete"},
    )

    deleted = await service.delete_character(character.id)
    assert deleted is True

    # Should not be found after deletion
    result = await service.get_character(character.id)
    assert result is None


async def test_select_image(db_session, sample_user):
    """select_image should set reference_image_id on the character."""
    from app.models.asset import Asset
    from app.models.character_image import CharacterImage
    from app.services.character_service import CharacterService

    service = CharacterService(db_session)
    character = await service.create_character(
        user_id=sample_user.id,
        data={"name": "WithImage"},
    )

    # Create an asset to reference
    asset = Asset(
        id=uuid.uuid4(),
        file_name="test.png",
        file_type="image",
        storage_path="/tmp/test.png",
        file_size_bytes=1024,
        asset_category="character_ref",
    )
    db_session.add(asset)
    await db_session.flush()

    # Create a character image
    char_image = CharacterImage(
        id=uuid.uuid4(),
        character_id=character.id,
        asset_id=asset.id,
        generation_seed=42,
        is_selected=False,
        attempt_number=1,
    )
    db_session.add(char_image)
    await db_session.flush()
    await db_session.commit()

    # Select the image
    updated = await service.select_image(character.id, char_image.id)

    assert updated.reference_image_id == asset.id
    assert updated.seed_value == 42
