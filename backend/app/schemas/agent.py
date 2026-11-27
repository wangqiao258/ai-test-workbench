"""供外部 AI 按编号读取分析上下文的只读视图。"""

from datetime import datetime

from app.schemas.common import ApiModel
from app.schemas.query import (
    AnalysisQueryOut,
    ExchangeDetailOut,
    OperationOut,
    RequirementOut,
    RunCaseDetailOut,
    RunOut,
)
from app.schemas.review import DefectDetailOut, DefectOut, FindingDetailOut


class FindingBundleOut(ApiModel):
    finding: FindingDetailOut
    run: RunOut | None = None
    case: RunCaseDetailOut | None = None
    exchange: ExchangeDetailOut | None = None
    requirement: RequirementOut | None = None
    operation: OperationOut | None = None
    defect: DefectOut | None = None
    analysis: AnalysisQueryOut | None = None


class DefectBundleOut(ApiModel):
    defect: DefectDetailOut
    finding: FindingDetailOut | None = None
    run: RunOut | None = None
    case: RunCaseDetailOut | None = None
    exchange: ExchangeDetailOut | None = None
    requirement: RequirementOut | None = None
    operation: OperationOut | None = None
    analysis: AnalysisQueryOut | None = None


class AiTicketOut(ApiModel):
    url: str
    expires_at: datetime
    ttl_seconds: int
