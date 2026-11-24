from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

RunStatus = Literal["passed", "failed", "skipped", "error"]
Severity = Literal["blocker", "critical", "major", "minor"]
FindingType = Literal["regression", "spec-mismatch", "contract", "duplicate", "flaky"]


class HeaderItem(BaseModel):
    name: str
    value: str


class HttpPayload(BaseModel):
    headers: list[HeaderItem] = Field(default_factory=list)
    body: str | None = None


class ExchangeIn(BaseModel):
    index: int = Field(ge=0)
    method: str
    url: str
    status: int | None = None
    elapsed_ms: int = 0
    request: HttpPayload = Field(default_factory=HttpPayload)
    response: HttpPayload = Field(default_factory=HttpPayload)
    error: str | None = None


class CaseIn(BaseModel):
    nodeid: str = Field(min_length=1)
    status: RunStatus
    duration_ms: int = 0
    error: str | None = None
    logs: list[str] = Field(default_factory=list)
    name: str | None = None
    file: str | None = None
    tags: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    exchanges: list[ExchangeIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_exchange_index(self) -> "CaseIn":
        seen: set[int] = set()
        for exchange in self.exchanges:
            if exchange.index in seen:
                raise ValueError(f"exchanges 中 index {exchange.index} 重复")
            seen.add(exchange.index)
        return self


class RunMeta(BaseModel):
    external_id: str = Field(min_length=1)
    started_at: datetime
    duration_ms: int = 0
    branch: str = ""
    commit: str = ""
    environment: str = ""

    @field_validator("started_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("started_at 必须带时区，例如 2026-11-24T09:12:33+08:00")
        return value


class FindingIn(BaseModel):
    external_id: str = Field(min_length=1)
    nodeid: str = Field(min_length=1)
    exchange_index: int | None = None
    type: FindingType
    title: str
    severity: Severity = "major"
    confidence: float = Field(default=0, ge=0, le=1)
    summary: str = ""
    root_cause: str = ""
    impact: str = ""
    requirement_id: str | None = None


class AnalysisIn(BaseModel):
    analyzer: str = ""
    model: str = ""
    generated_at: datetime
    summary: str = ""
    findings: list[FindingIn] = Field(default_factory=list)

    @field_validator("generated_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("generated_at 必须带时区")
        return value


class RunIngestIn(BaseModel):
    run: RunMeta
    cases: list[CaseIn] = Field(default_factory=list)
    analysis: AnalysisIn | None = None


class CatalogCaseIn(BaseModel):
    nodeid: str = Field(min_length=1)
    name: str | None = None
    file: str | None = None
    tags: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)


class CatalogIn(BaseModel):
    cases: list[CatalogCaseIn] = Field(default_factory=list)


class RunIngestOut(BaseModel):
    run_id: UUID
    external_id: str
    case_count: int
    exchange_count: int
    finding_count: int


class CatalogOut(BaseModel):
    case_count: int
    marker_count: int


class AnalysisOut(BaseModel):
    run_id: UUID
    finding_count: int


class ArtifactOut(BaseModel):
    id: UUID
    kind: str
    filename: str
    size_bytes: int
    sha256: str
    job_id: UUID | None = None


class JobOut(BaseModel):
    id: UUID
    status: str
    error: dict | None = None
    created_at: datetime
    updated_at: datetime
