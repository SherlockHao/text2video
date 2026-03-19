import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Shot(Base, TimestampMixin):
    __tablename__ = "shots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    storyboard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("storyboards.id"), index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    scene_number: Mapped[int] = mapped_column(Integer, default=1)
    image_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    narration_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    scene_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    character_ids: Mapped[dict] = mapped_column(JSONB, default=list)
    selected_image_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", use_alter=True), nullable=True
    )
    generated_video_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", use_alter=True), nullable=True
    )
    tts_audio_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", use_alter=True), nullable=True
    )
    image_status: Mapped[str] = mapped_column(String(50), default="pending")
    video_status: Mapped[str] = mapped_column(String(50), default="pending")
    tts_status: Mapped[str] = mapped_column(String(50), default="pending")
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    # Relationships
    storyboard = relationship("Storyboard", back_populates="shots")
