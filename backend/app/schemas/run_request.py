from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.common import ApiModel


class RunRequestCreateIn(ApiModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=255)
    spec_paths: list[str] = Field(default_factory=list)
    case_nodeids: list[str] = Field(default_factory=list)
    yaml_hash: str = Field(default="", max_length=64)


class RunRequestBaseOut(ApiModel):
    id: UUID
    status: str
    reason: str
    spec_paths: list[str]
    case_nodeids: list[str]
    run_external_id: str | None = None
    exit_code: int | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunRequestOut(RunRequestBaseOut):
    yaml_hash: str
    requested_by: UUID | None = None
    log_path: str | None = None


class RunRequestListOut(ApiModel):
    items: list[RunRequestOut]
    page: int
    page_size: int
    total: int


class IngestRunRequestIn(ApiModel):
    """AI 机触发运行：spec_paths 相对项目 specs 目录，留空执行该项目全部规格。"""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=255)
    spec_paths: list[str] = Field(default_factory=list)
    case_nodeids: list[str] = Field(default_factory=list)


class IngestRunRequestOut(RunRequestBaseOut):
    """AI 机只看到任务状态与结果，不暴露平台内部路径。"""
