import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunRequest(Base):
    __tablename__ = "run_request"
    __table_args__ = (
        CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'failed', 'canceled')",
            name="status_valid",
        ),
        Index("ix_run_request_project_status", "project_id", "status", "created_at"),
        Index("ix_run_request_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    spec_paths: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    yaml_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    run_external_id: Mapped[str | None] = mapped_column(String(128))
    log_path: Mapped[str | None] = mapped_column(String(512))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
