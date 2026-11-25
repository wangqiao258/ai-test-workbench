import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.db.base import Base


class TestCase(Base):
    __tablename__ = "test_case"
    __table_args__ = (
        UniqueConstraint("project_id", "nodeid", name="uq_test_case_project_nodeid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nodeid: Mapped[str] = mapped_column(String(512), nullable=False)
    file: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    last_status: Mapped[str | None] = mapped_column(String(20))
    last_duration_ms: Mapped[int | None] = mapped_column(Integer)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CaseRequirementMarker(Base):
    __tablename__ = "case_requirement_marker"
    __table_args__ = (
        UniqueConstraint(
            "case_id", "requirement_external_id", name="uq_case_requirement_marker_case_req"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("test_case.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requirement_external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="marker")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
