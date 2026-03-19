import uuid

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class TTSConfig(Base, TimestampMixin):
    __tablename__ = "tts_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), unique=True, index=True
    )
    voice_id: Mapped[str] = mapped_column(String(255), default="")
    speed: Mapped[float] = mapped_column(Float, default=1.0)
    stability: Mapped[float] = mapped_column(Float, default=0.5)
    similarity_boost: Mapped[float] = mapped_column(Float, default=0.75)
    language: Mapped[str] = mapped_column(String(10), default="zh")

    # Relationships
    project = relationship("Project", back_populates="tts_config")
