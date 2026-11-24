from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import ApiModel

Verdict = Literal["confirm", "reject", "false-positive"]
FindingStatus = Literal["pending", "confirmed", "rejected", "false-positive"]
DefectStatus = Literal["new", "confirmed", "fixing", "fixed", "closed"]


class JudgmentOut(ApiModel):
    verdict: str
    note: str
    actor: str
    defect_id: str | None = None
    created_at: datetime


class FindingOut(ApiModel):
    id: str
    run_id: UUID
    run_external_id: str
    nodeid: str
    type: str
    title: str
    summary: str
    root_cause: str
    impact: str
    confidence: float
    suggested_severity: str
    exchange_index: int | None = None
    requirement_id: str | None = None
    operation_id: str | None = None
    status: str
    note: str | None = None
    judged_at: datetime | None = None
    defect_id: str | None = None
    created_at: datetime


class FindingDetailOut(FindingOut):
    judgments: list[JudgmentOut] = Field(default_factory=list)


class FindingListOut(ApiModel):
    items: list[FindingOut]
    page: int
    page_size: int
    total: int


class DefectDecisionOut(ApiModel):
    verdict: str
    note: str
    at: datetime


class DefectOut(ApiModel):
    id: str
    title: str
    severity: str
    status: str
    finding_id: str | None = None
    run_id: UUID | None = None
    run_external_id: str | None = None
    nodeid: str
    requirement_id: str | None = None
    operation_id: str | None = None
    exchange_index: int | None = None
    evidence_summary: str
    source: str
    decision: DefectDecisionOut
    version: int
    created_at: datetime
    updated_at: datetime


class DefectEventOut(ApiModel):
    from_status: str | None = None
    to_status: str
    note: str
    actor: str
    created_at: datetime


class DefectDetailOut(DefectOut):
    events: list[DefectEventOut] = Field(default_factory=list)


class DefectListOut(ApiModel):
    items: list[DefectOut]
    page: int
    page_size: int
    total: int


class JudgeIn(ApiModel):
    verdict: Verdict
    note: str = ""


class JudgeOut(ApiModel):
    finding: FindingOut
    defect: DefectOut | None = None


class DefectPatchIn(ApiModel):
    status: DefectStatus
    version: int | None = None


class AuditOut(ApiModel):
    id: UUID
    entity_type: str
    entity_id: str
    action: str
    actor: str
    before: dict | None = None
    after: dict | None = None
    created_at: datetime


class AuditListOut(ApiModel):
    items: list[AuditOut]
    page: int
    page_size: int
    total: int
