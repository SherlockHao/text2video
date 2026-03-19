import uuid

from sqlalchemy import ForeignKey, Integer, Float, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Storyboard(Base, TimestampMixin):
    __tablename__ = "storyboards"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    scene_count: Mapped[int] = mapped_column(Integer, default=0)
    shots_per_minute: Mapped[float] = mapped_column(Float, default=10.0)
    raw_llm_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")

    # Relationships
    project = relationship("Project", back_populates="storyboards")
    shots = relationship(
        "Shot", back_populates="storyboard", order_by="Shot.sequence_number"
    )
