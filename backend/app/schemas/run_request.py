from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.common import ApiModel


class RunRequestCreateIn(ApiModel):
    reason: str = Field(default="", max_length=255)
    spec_paths: list[str] = Field(default_factory=list)
    yaml_hash: str = Field(default="", max_length=64)


class RunRequestOut(ApiModel):
    id: UUID
    status: str
    reason: str
    spec_paths: list[str]
    yaml_hash: str
    requested_by: UUID | None = None
    run_external_id: str | None = None
    log_path: str | None = None
    exit_code: int | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunRequestListOut(ApiModel):
    items: list[RunRequestOut]
    page: int
    page_size: int
    total: int
