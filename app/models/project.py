import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class Project(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(50), default="draft")
    timeline_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)

    # New columns
    content_type: Mapped[str] = mapped_column(String(50), default="narration")
    visual_style: Mapped[str] = mapped_column(String(50), default="manga")
    aspect_ratio: Mapped[str] = mapped_column(String(10), default="16:9")
    duration_target: Mapped[int] = mapped_column(Integer, default=60)
    quality_tier: Mapped[str] = mapped_column(String(50), default="normal")
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_step: Mapped[str] = mapped_column(String(50), default="draft")
    reference_image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    user = relationship("User", back_populates="projects", lazy="selectin")
    assets = relationship("Asset", back_populates="project", lazy="selectin")
    tasks = relationship("AITask", back_populates="project", lazy="selectin")
    storyboards = relationship("Storyboard", back_populates="project")
    tts_config = relationship("TTSConfig", back_populates="project", uselist=False)
