import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.pagination import paginate
from app.db.models.analysis import Analysis, Finding
from app.db.models.case import TestCase
from app.db.models.run import Artifact, Exchange, Run, RunCase
from app.schemas.query import (
    AnalysisQueryOut,
    ExchangeDetailOut,
    ExchangeRequestOut,
    ExchangeResponseOut,
    ExchangeSummaryOut,
    RunCaseDetailOut,
    RunCaseOut,
    RunListOut,
    RunOut,
)
from app.services.storage import get_storage

SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-project-token",
}


def run_out(run: Run) -> RunOut:
    return RunOut(
        id=run.id,
        external_id=run.external_id,
        started_at=run.started_at,
        duration_ms=run.duration_ms,
        branch=run.branch,
        commit=run.commit_sha,
        environment=run.environment,
        stats=run.stats,
    )


def resolve_run(db: Session, project_id: uuid.UUID, run_ref: str) -> Run:
    """按 UUID 或 external_id 定位运行，并校验归属项目。"""
    run: Run | None = None
    try:
        run = db.get(Run, uuid.UUID(run_ref))
    except ValueError:
        pass
    if run is None:
        run = db.scalar(
            select(Run).where(Run.project_id == project_id, Run.external_id == run_ref)
        )
    if run is None or run.project_id != project_id:
        raise ApiError(404, "run_not_found", "运行不存在")
    return run


def truncate_text(text: str | None, limit: int) -> str | None:
    if text is None or limit <= 0 or len(text) <= limit:
        return text
    return f"{text[:limit]}\n…（已截断，原文 {len(text)} 字符）"


def redact_sensitive_headers(headers: list[dict] | None) -> list[dict]:
    items: list[dict] = []
    for header in headers or []:
        name = str(header.get("name") or "")
        value = str(header.get("value") or "")
        if name.lower() in SENSITIVE_HEADERS:
            value = "***"
        items.append({"name": name, "value": value})
    return items


def artifact_body(db: Session, artifact_id: uuid.UUID | None) -> str | None:
    if artifact_id is None:
        return None
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        return None
    try:
        return get_storage().read(artifact.storage_key).decode(
            "utf-8", errors="replace"
        )
    except (OSError, ValueError):
        return None


def case_meta(db: Session, run_case: RunCase) -> tuple[str | None, str | None]:
    if run_case.case_id is None:
        return None, None
    test_case = db.get(TestCase, run_case.case_id)
    if test_case is None:
        return None, None
    return test_case.name, test_case.file


def resolve_run_case(db: Session, run: Run, nodeid: str) -> RunCase:
    run_case = db.scalar(
        select(RunCase).where(RunCase.run_id == run.id, RunCase.nodeid == nodeid)
    )
    if run_case is None:
        raise ApiError(404, "run_case_not_found", "本次运行中不存在该用例")
    return run_case


def runs_page(
    db: Session, project_id: uuid.UUID, page: int = 1, page_size: int = 20
) -> RunListOut:
    rows, total = paginate(
        db,
        Run,
        [Run.project_id == project_id],
        (Run.started_at.desc(), Run.created_at.desc()),
        page,
        page_size,
    )
    return RunListOut(
        items=[run_out(run) for run in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


def list_run_cases(db: Session, run: Run) -> list[RunCaseOut]:
    run_cases = list(
        db.scalars(select(RunCase).where(RunCase.run_id == run.id).order_by(RunCase.nodeid))
    )
    counts = dict(
        db.execute(
            select(Exchange.run_case_id, func.count(Exchange.id))
            .where(Exchange.run_id == run.id)
            .group_by(Exchange.run_case_id)
        ).all()
    )
    items: list[RunCaseOut] = []
    for run_case in run_cases:
        name, file = case_meta(db, run_case)
        items.append(
            RunCaseOut(
                nodeid=run_case.nodeid,
                name=name,
                file=file,
                status=run_case.status,
                duration_ms=run_case.duration_ms,
                error=run_case.error_text,
                exchange_count=counts.get(run_case.id, 0),
            )
        )
    return items


def run_case_detail(
    db: Session, run_case: RunCase, body_limit: int = 0
) -> RunCaseDetailOut:
    name, file = case_meta(db, run_case)
    exchanges = db.scalars(
        select(Exchange)
        .where(Exchange.run_case_id == run_case.id)
        .order_by(Exchange.exchange_index)
    ).all()
    return RunCaseDetailOut(
        nodeid=run_case.nodeid,
        name=name,
        file=file,
        status=run_case.status,
        duration_ms=run_case.duration_ms,
        error=truncate_text(run_case.error_text, body_limit),
        logs=[
            truncate_text(item, body_limit) or ""
            for item in (run_case.logs or [])
        ],
        exchanges=[
            ExchangeSummaryOut(
                index=exchange.exchange_index,
                method=exchange.method,
                url=exchange.url,
                status=exchange.status_code,
                elapsed_ms=exchange.elapsed_ms,
                error=exchange.error_text,
                has_request_body=(
                    exchange.request_body is not None
                    or exchange.request_body_artifact_id is not None
                ),
                has_response_body=(
                    exchange.response_body is not None
                    or exchange.response_body_artifact_id is not None
                ),
            )
            for exchange in exchanges
        ],
    )


def load_exchange(db: Session, run_case: RunCase, exchange_index: int) -> Exchange:
    exchange = db.scalar(
        select(Exchange).where(
            Exchange.run_case_id == run_case.id,
            Exchange.exchange_index == exchange_index,
        )
    )
    if exchange is None:
        raise ApiError(404, "exchange_not_found", "此次交换记录不存在")
    return exchange


def exchange_detail(
    db: Session,
    exchange: Exchange,
    body_limit: int = 0,
    *,
    redact_sensitive: bool = False,
) -> ExchangeDetailOut:
    request_body = exchange.request_body
    if request_body is None:
        request_body = artifact_body(db, exchange.request_body_artifact_id)
    response_body = exchange.response_body
    if response_body is None:
        response_body = artifact_body(db, exchange.response_body_artifact_id)
    return ExchangeDetailOut(
        index=exchange.exchange_index,
        method=exchange.method,
        url=exchange.url,
        status=exchange.status_code,
        elapsed_ms=exchange.elapsed_ms,
        request=ExchangeRequestOut(
            headers=(
                redact_sensitive_headers(exchange.request_headers)
                if redact_sensitive
                else exchange.request_headers
            ),
            body=truncate_text(request_body, body_limit),
            body_artifact_id=exchange.request_body_artifact_id,
        ),
        response=ExchangeResponseOut(
            status=exchange.status_code,
            headers=(
                redact_sensitive_headers(exchange.response_headers)
                if redact_sensitive
                else exchange.response_headers
            ),
            body=truncate_text(response_body, body_limit),
            body_artifact_id=exchange.response_body_artifact_id,
        ),
        error=exchange.error_text,
    )


def analysis_summary(
    db: Session, project_id: uuid.UUID, run_id: uuid.UUID | None
) -> AnalysisQueryOut | None:
    if run_id is None:
        return None
    analysis = db.scalar(
        select(Analysis).where(
            Analysis.run_id == run_id, Analysis.project_id == project_id
        )
    )
    if analysis is None:
        return None
    finding_count = (
        db.scalar(select(func.count(Finding.id)).where(Finding.run_id == run_id)) or 0
    )
    return AnalysisQueryOut(
        run_id=run_id,
        analyzer=analysis.analyzer,
        model=analysis.model,
        generated_at=analysis.generated_at,
        summary=analysis.summary,
        finding_count=finding_count,
    )


def analysis_out(db: Session, project_id: uuid.UUID, run: Run) -> AnalysisQueryOut:
    result = analysis_summary(db, project_id, run.id)
    if result is None:
        raise ApiError(404, "analysis_not_found", "该运行还没有 AI 分析摘要")
    return result
