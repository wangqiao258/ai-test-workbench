from datetime import datetime
from uuid import UUID

from app.schemas.common import ApiModel


class RunOut(ApiModel):
    id: UUID
    external_id: str
    started_at: datetime
    duration_ms: int
    branch: str
    commit: str
    environment: str
    stats: dict


class RunListOut(ApiModel):
    items: list[RunOut]
    page: int
    page_size: int
    total: int


class RunCaseOut(ApiModel):
    nodeid: str
    name: str | None = None
    file: str | None = None
    status: str
    duration_ms: int
    error: str | None = None
    exchange_count: int = 0


class ExchangeSummaryOut(ApiModel):
    index: int
    method: str
    url: str
    status: int | None = None
    elapsed_ms: int
    error: str | None = None
    has_request_body: bool = False
    has_response_body: bool = False


class RunCaseDetailOut(ApiModel):
    nodeid: str
    name: str | None = None
    file: str | None = None
    status: str
    duration_ms: int
    error: str | None = None
    logs: list[str]
    exchanges: list[ExchangeSummaryOut]


class ExchangeRequestOut(ApiModel):
    headers: list[dict]
    body: str | None = None
    body_artifact_id: UUID | None = None


class ExchangeResponseOut(ApiModel):
    status: int | None = None
    headers: list[dict]
    body: str | None = None
    body_artifact_id: UUID | None = None


class ExchangeDetailOut(ApiModel):
    index: int
    method: str
    url: str
    status: int | None = None
    elapsed_ms: int
    request: ExchangeRequestOut
    response: ExchangeResponseOut
    error: str | None = None


class AnalysisQueryOut(ApiModel):
    run_id: UUID
    analyzer: str
    model: str
    generated_at: datetime
    summary: str
    finding_count: int


class SummaryOut(ApiModel):
    pending_findings: int
    open_defects: int
    case_count: int
    run_count: int
    recent_runs: list[RunOut]


class CaseOut(ApiModel):
    nodeid: str
    name: str
    file: str
    spec_path: str | None = None
    tags: list[str]
    requirement_ids: list[str]
    operation_ids: list[str]
    last_run_id: UUID | None = None
    last_status: str | None = None
    last_duration_ms: int | None = None
    last_run_at: datetime | None = None
    archived_at: datetime | None = None


class CaseListOut(ApiModel):
    items: list[CaseOut]
    page: int
    page_size: int
    total: int


class CaseArchiveIn(ApiModel):
    nodeid: str
    archived: bool = True


class CaseArchiveOut(ApiModel):
    nodeid: str
    archived: bool


class RequirementOut(ApiModel):
    id: str
    title: str
    version: str
    tags: list[str]
    owner: str
    updated_at: datetime
    content_md: str
    operation_ids: list[str]
    case_nodeids: list[str]


class RequirementQueueItem(ApiModel):
    id: str
    title: str
    category: str
    tags: list[str]
    priority: str
    reason: str
    updated_at: datetime
    case_count: int
    last_status: str | None = None
    last_run_at: datetime | None = None
    operation_count: int = 0
    preview: str = ""


class RequirementQueueOut(ApiModel):
    items: list[RequirementQueueItem]
    total: int
    next_offset: int | None = None


class RequirementOperationOut(ApiModel):
    id: str
    method: str
    path: str
    summary: str
    tag: str
    case_count: int
    last_status: str | None = None
    last_run_at: datetime | None = None
    confidence: str


class RequirementAssociationsOut(ApiModel):
    requirement_id: str
    operations: list[RequirementOperationOut]
    total: int


class OperationOut(ApiModel):
    id: str
    doc_id: str
    method: str
    path: str
    summary: str
    tag: str
    description: str
    params: list[dict]
    request_body: list[dict] | None = None
    responses: list[dict]
    requirement_ids: list[str]
    case_nodeids: list[str]


class OperationSummaryOut(ApiModel):
    id: str
    doc_id: str
    method: str
    path: str
    summary: str
    tag: str
    description_preview: str = ""
    required_params: list[dict] = []
    optional_param_count: int = 0
    request_body_fields: list[dict] = []
    request_body_field_count: int = 0
    response_statuses: list[int] = []


class OperationSummaryListOut(ApiModel):
    items: list[OperationSummaryOut]
    total: int
    next_offset: int | None = None


class OpenApiDocOut(ApiModel):
    id: str
    title: str
    version: str
    base_url: str
    updated_at: datetime
    description: str
    operations: list[OperationOut]
