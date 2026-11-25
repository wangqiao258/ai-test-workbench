import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.db.base import Base


class Analysis(Base):
    __tablename__ = "analysis"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("run.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    analyzer: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Finding(Base):
    __tablename__ = "finding"
    __table_args__ = (
        UniqueConstraint("project_id", "external_id", name="uq_finding_project_external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run_case.id", ondelete="SET NULL")
    )
    nodeid: Mapped[str] = mapped_column(String(512), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    exchange_index: Mapped[int | None] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    root_cause: Mapped[str] = mapped_column(Text, nullable=False, default="")
    impact: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    suggested_severity: Mapped[str] = mapped_column(String(16), nullable=False, default="major")
    requirement_external_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    note: Mapped[str | None] = mapped_column(Text)
    judged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
