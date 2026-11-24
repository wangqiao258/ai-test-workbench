from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

HttpMethod = Literal["GET", "POST", "PUT", "DELETE", "PATCH"]


class RequirementIn(BaseModel):
    external_id: str = Field(min_length=1)
    title: str = ""
    version: str = ""
    tags: list[str] = Field(default_factory=list)
    owner: str = ""
    content_md: str = ""
    updated_at: datetime | None = None

    @field_validator("updated_at")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("时间必须带时区，例如 2026-11-24T09:12:33+08:00")
        return value


class RequirementBatchIn(BaseModel):
    requirements: list[RequirementIn] = Field(default_factory=list)


class OperationIn(BaseModel):
    external_id: str = Field(min_length=1)
    method: HttpMethod
    path: str = Field(min_length=1)
    summary: str = ""
    tag: str = ""
    description: str = ""
    params: list[dict] = Field(default_factory=list)
    request_body: list[dict] | None = None
    responses: list[dict] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)


class OpenApiDocIn(BaseModel):
    external_id: str = Field(min_length=1)
    title: str = ""
    version: str = ""
    base_url: str = ""
    description: str = ""
    updated_at: datetime | None = None
    operations: list[OperationIn] = Field(default_factory=list)

    @field_validator("updated_at")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("时间必须带时区，例如 2026-11-24T09:12:33+08:00")
        return value


class OpenApiBatchIn(BaseModel):
    docs: list[OpenApiDocIn] = Field(default_factory=list)


class RequirementIngestOut(BaseModel):
    requirement_count: int


class OpenApiIngestOut(BaseModel):
    doc_count: int
    operation_count: int
