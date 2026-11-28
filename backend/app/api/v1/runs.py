from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_membership
from app.db.models.identity import ProjectMember
from app.db.session import get_db
from app.schemas.query import (
    AnalysisQueryOut,
    ExchangeDetailOut,
    RunCaseDetailOut,
    RunCaseOut,
    RunListOut,
    RunOut,
)
from app.services.runs import (
    analysis_out,
    exchange_detail,
    load_exchange,
    resolve_run,
    resolve_run_case,
    run_case_detail,
    run_out,
    runs_page,
)
from app.services.runs import (
    list_run_cases as list_run_cases_service,
)

router = APIRouter(prefix="/projects/{project_id}/runs", tags=["query"])


@router.get("", response_model=RunListOut)
def list_runs(
    project_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> RunListOut:
    return runs_page(db, project_id, page, page_size)


@router.get("/{run_ref}", response_model=RunOut, deprecated=True)
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
    return list_run_cases_service(db, resolve_run(db, project_id, run_ref))


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
    run_case = resolve_run_case(db, run, nodeid)
    return exchange_detail(db, load_exchange(db, run_case, index))


@router.get("/{run_ref}/cases/{nodeid:path}", response_model=RunCaseDetailOut)
def get_run_case(
    project_id: UUID,
    run_ref: str,
    nodeid: str,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> RunCaseDetailOut:
    run = resolve_run(db, project_id, run_ref)
    return run_case_detail(db, resolve_run_case(db, run, nodeid))


@router.get("/{run_ref}/analysis", response_model=AnalysisQueryOut)
def get_analysis(
    project_id: UUID,
    run_ref: str,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> AnalysisQueryOut:
    return analysis_out(db, project_id, resolve_run(db, project_id, run_ref))
