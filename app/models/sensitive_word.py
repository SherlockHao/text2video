import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SensitiveWordHit(Base, TimestampMixin):
    __tablename__ = "sensitive_word_hits"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), index=True
    )
    text_segment: Mapped[str] = mapped_column(Text, nullable=False)
    matched_keywords: Mapped[dict] = mapped_column(JSONB, default=list)
    action_taken: Mapped[str] = mapped_column(String(50), default="warned")
