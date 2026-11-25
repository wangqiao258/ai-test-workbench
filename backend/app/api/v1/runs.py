from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_membership
from app.core.errors import ApiError
from app.core.pagination import paginate
from app.db.models.analysis import Analysis, Finding
from app.db.models.case import TestCase
from app.db.models.identity import ProjectMember
from app.db.models.run import Artifact, Exchange, Run, RunCase
from app.db.session import get_db
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

router = APIRouter(prefix="/projects/{project_id}/runs", tags=["query"])


def resolve_run(db: Session, project_id: UUID, run_ref: str) -> Run:
    run: Run | None = None
    try:
        run = db.get(Run, UUID(run_ref))
    except ValueError:
        pass
    if run is None:
        run = db.scalar(
            select(Run).where(Run.project_id == project_id, Run.external_id == run_ref)
        )
    if run is None or run.project_id != project_id:
        raise ApiError(404, "run_not_found", "运行不存在")
    return run


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


def _resolve_run_case(db: Session, run: Run, nodeid: str) -> RunCase:
    run_case = db.scalar(
        select(RunCase).where(RunCase.run_id == run.id, RunCase.nodeid == nodeid)
    )
    if run_case is None:
        raise ApiError(404, "run_case_not_found", "本次运行中不存在该用例")
    return run_case


def _artifact_body(db: Session, artifact_id: UUID | None) -> str | None:
    if artifact_id is None:
        return None
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        return None
    try:
        return get_storage().read(artifact.storage_key).decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def _case_meta(db: Session, run_case: RunCase) -> tuple[str | None, str | None]:
    if run_case.case_id is None:
        return None, None
    test_case = db.get(TestCase, run_case.case_id)
    if test_case is None:
        return None, None
    return test_case.name, test_case.file


@router.get("", response_model=RunListOut)
def list_runs(
    project_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
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


@router.get("/{run_ref}", response_model=RunOut)
def get_run(
    project_id: UUID,
    run_ref: str,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> RunOut:
    return run_out(resolve_run(db, project_id, run_ref))


@router.get("/{run_ref}/cases", response_model=list[RunCaseOut])
def list_run_cases(
    project_id: UUID,
    run_ref: str,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[RunCaseOut]:
    run = resolve_run(db, project_id, run_ref)
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
        name, file = _case_meta(db, run_case)
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


@router.get(
    "/{run_ref}/cases/{nodeid:path}/exchanges/{index}", response_model=ExchangeDetailOut
)
def get_exchange(
    project_id: UUID,
    run_ref: str,
    nodeid: str,
    index: int,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> ExchangeDetailOut:
    run = resolve_run(db, project_id, run_ref)
    run_case = _resolve_run_case(db, run, nodeid)
    exchange = db.scalar(
        select(Exchange).where(
            Exchange.run_case_id == run_case.id, Exchange.exchange_index == index
        )
    )
    if exchange is None:
        raise ApiError(404, "exchange_not_found", "此次交换记录不存在")

    request_body = exchange.request_body
    if request_body is None:
        request_body = _artifact_body(db, exchange.request_body_artifact_id)
    response_body = exchange.response_body
    if response_body is None:
        response_body = _artifact_body(db, exchange.response_body_artifact_id)

    return ExchangeDetailOut(
        index=exchange.exchange_index,
        method=exchange.method,
        url=exchange.url,
        status=exchange.status_code,
        elapsed_ms=exchange.elapsed_ms,
        request=ExchangeRequestOut(
            headers=exchange.request_headers,
            body=request_body,
            body_artifact_id=exchange.request_body_artifact_id,
        ),
        response=ExchangeResponseOut(
            status=exchange.status_code,
            headers=exchange.response_headers,
            body=response_body,
            body_artifact_id=exchange.response_body_artifact_id,
        ),
        error=exchange.error_text,
    )


@router.get("/{run_ref}/cases/{nodeid:path}", response_model=RunCaseDetailOut)
def get_run_case(
    project_id: UUID,
    run_ref: str,
    nodeid: str,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> RunCaseDetailOut:
    run = resolve_run(db, project_id, run_ref)
    run_case = _resolve_run_case(db, run, nodeid)
    name, file = _case_meta(db, run_case)
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
        error=run_case.error_text,
        logs=run_case.logs,
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


@router.get("/{run_ref}/analysis", response_model=AnalysisQueryOut)
def get_analysis(
    project_id: UUID,
    run_ref: str,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> AnalysisQueryOut:
    run = resolve_run(db, project_id, run_ref)
    analysis = db.scalar(
        select(Analysis).where(
            Analysis.run_id == run.id, Analysis.project_id == project_id
        )
    )
    if analysis is None:
        raise ApiError(404, "analysis_not_found", "该运行还没有 AI 分析摘要")
    finding_count = (
        db.scalar(select(func.count(Finding.id)).where(Finding.run_id == run.id)) or 0
    )
    return AnalysisQueryOut(
        run_id=run.id,
        analyzer=analysis.analyzer,
        model=analysis.model,
        generated_at=analysis.generated_at,
        summary=analysis.summary,
        finding_count=finding_count,
    )
