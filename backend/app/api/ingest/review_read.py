"""供外部 AI 按编号读取发现、缺陷与运行证据的只读接口。

项目由 X-Project-Token 绑定，因此 FND-003 / DEF-1001 这类编号即可定位，
不需要再传项目 UUID。所有接口仅使用 GET，要求 runs:read；
令牌具备 assets:read 时额外附带需求与契约。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import (
    SCOPE_ASSETS_READ,
    SCOPE_RUNS_READ,
    ReadContext,
    require_read_context,
)
from app.core.errors import ApiError
from app.db.models.analysis import Finding
from app.db.models.asset import Operation
from app.db.models.review import Defect
from app.db.models.run import Exchange, Run
from app.db.session import get_db
from app.schemas.agent import DefectBundleOut, FindingBundleOut
from app.schemas.query import ExchangeDetailOut, RunCaseDetailOut
from app.schemas.review import (
    DefectListOut,
    DefectStatus,
    FindingListOut,
    FindingStatus,
)
from app.services.agent_views import (
    defect_bundle,
    exchange_detail,
    finding_bundle,
    resolve_run_case,
    run_case_detail,
)
from app.services.review import (
    build_defect_out,
    build_finding_out,
    resolve_finding_operation_id,
)
from app.services.runs import resolve_run

router = APIRouter(tags=["ingest"])


def _load_finding(db: Session, project_id, finding_id: str) -> Finding:
    finding = db.scalar(
        select(Finding).where(
            Finding.project_id == project_id, Finding.external_id == finding_id
        )
    )
    if finding is None:
        raise ApiError(404, "finding_not_found", "AI finding 不存在")
    return finding


def _ensure_ticket(context: ReadContext, resource: str) -> None:
    if context.ticket_resource is not None and context.ticket_resource != resource:
        raise ApiError(403, "ticket_scope_limited", "票据只能读取指定的发现或缺陷")


def _ensure_list_allowed(context: ReadContext) -> None:
    if context.ticket_resource is not None:
        raise ApiError(403, "ticket_scope_limited", "票据不能用于列表查询")


def _ensure_case_ticket(context: ReadContext, run: Run, nodeid: str) -> None:
    if context.ticket_resource is None:
        return
    if context.ticket_run != run.external_id or context.ticket_nodeid != nodeid:
        raise ApiError(403, "ticket_scope_limited", "票据只能读取该发现关联的用例")


def _load_defect(db: Session, project_id, defect_id: str) -> Defect:
    defect = db.scalar(
        select(Defect).where(
            Defect.project_id == project_id, Defect.number == defect_id
        )
    )
    if defect is None:
        raise ApiError(404, "defect_not_found", "缺陷不存在")
    return defect


@router.get("/findings", response_model=FindingListOut)
def list_findings(
    status: FindingStatus | None = None,
    run_filter: str | None = Query(default=None, alias="run"),
    limit: int = Query(default=20, ge=1, le=100),
    context: ReadContext = Depends(require_read_context(SCOPE_RUNS_READ)),
    db: Session = Depends(get_db),
) -> FindingListOut:
    _ensure_list_allowed(context)
    project_id = context.project.id
    conditions = [Finding.project_id == project_id]
    if status is not None:
        conditions.append(Finding.status == status)
    if run_filter:
        run = resolve_run(db, project_id, run_filter)
        conditions.append(Finding.run_id == run.id)

    findings = list(
        db.scalars(
            select(Finding)
            .where(*conditions)
            .order_by(Finding.created_at.desc(), Finding.external_id)
            .limit(limit)
        )
    )
    run_ids = {item.run_id for item in findings}
    run_map = (
        {
            item.id: item.external_id
            for item in db.scalars(select(Run).where(Run.id.in_(run_ids)))
        }
        if run_ids
        else {}
    )
    finding_ids = [item.id for item in findings]
    defect_map = (
        dict(
            db.execute(
                select(Defect.finding_id, Defect.number).where(
                    Defect.finding_id.in_(finding_ids)
                )
            ).all()
        )
        if finding_ids
        else {}
    )
    operations = list(
        db.scalars(select(Operation).where(Operation.project_id == project_id))
    )
    total = db.scalar(select(func.count(Finding.id)).where(*conditions)) or 0
    return FindingListOut(
        items=[
            build_finding_out(
                item,
                run_external_id=run_map.get(item.run_id, ""),
                operation_id=resolve_finding_operation_id(db, item, operations),
                defect_number=defect_map.get(item.id),
            )
            for item in findings
        ],
        page=1,
        page_size=limit,
        total=total,
    )


@router.get("/findings/{finding_id}", response_model=FindingBundleOut)
def get_finding(
    finding_id: str,
    body_limit: int = Query(
        default=4000,
        ge=0,
        le=200000,
        description="请求/响应 body 的最大字符数；0 表示不截断",
    ),
    context: ReadContext = Depends(require_read_context(SCOPE_RUNS_READ)),
    db: Session = Depends(get_db),
) -> FindingBundleOut:
    _ensure_ticket(context, f"finding:{finding_id}")
    finding = _load_finding(db, context.project.id, finding_id)
    return finding_bundle(
        db,
        context.project.id,
        finding,
        body_limit=body_limit,
        include_assets=SCOPE_ASSETS_READ in context.scopes,
    )


@router.get("/defects", response_model=DefectListOut)
def list_defects(
    status: DefectStatus | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    context: ReadContext = Depends(require_read_context(SCOPE_RUNS_READ)),
    db: Session = Depends(get_db),
) -> DefectListOut:
    _ensure_list_allowed(context)
    project_id = context.project.id
    conditions = [Defect.project_id == project_id]
    if status is not None:
        conditions.append(Defect.status == status)

    defects = list(
        db.scalars(
            select(Defect)
            .where(*conditions)
            .order_by(Defect.created_at.desc(), Defect.number)
            .limit(limit)
        )
    )
    finding_ids = {item.finding_id for item in defects if item.finding_id is not None}
    finding_map = (
        dict(
            db.execute(
                select(Finding.id, Finding.external_id).where(Finding.id.in_(finding_ids))
            ).all()
        )
        if finding_ids
        else {}
    )
    run_ids = {item.run_id for item in defects if item.run_id is not None}
    run_map = (
        dict(
            db.execute(select(Run.id, Run.external_id).where(Run.id.in_(run_ids))).all()
        )
        if run_ids
        else {}
    )
    total = db.scalar(select(func.count(Defect.id)).where(*conditions)) or 0
    return DefectListOut(
        items=[
            build_defect_out(
                item,
                finding_external_id=finding_map.get(item.finding_id),
                run_external_id=run_map.get(item.run_id),
            )
            for item in defects
        ],
        page=1,
        page_size=limit,
        total=total,
    )


@router.get("/defects/{defect_id}", response_model=DefectBundleOut)
def get_defect(
    defect_id: str,
    body_limit: int = Query(
        default=4000,
        ge=0,
        le=200000,
        description="请求/响应 body 的最大字符数；0 表示不截断",
    ),
    context: ReadContext = Depends(require_read_context(SCOPE_RUNS_READ)),
    db: Session = Depends(get_db),
) -> DefectBundleOut:
    _ensure_ticket(context, f"defect:{defect_id}")
    defect = _load_defect(db, context.project.id, defect_id)
    return defect_bundle(
        db,
        context.project.id,
        defect,
        body_limit=body_limit,
        include_assets=SCOPE_ASSETS_READ in context.scopes,
    )


@router.get(
    "/runs/{run_ref}/cases/{nodeid:path}/exchanges/{index}",
    response_model=ExchangeDetailOut,
)
def get_exchange(
    run_ref: str,
    nodeid: str,
    index: int,
    body_limit: int = Query(
        default=4000,
        ge=0,
        le=200000,
        description="请求/响应 body 的最大字符数；0 表示不截断",
    ),
    context: ReadContext = Depends(require_read_context(SCOPE_RUNS_READ)),
    db: Session = Depends(get_db),
) -> ExchangeDetailOut:
    run = resolve_run(db, context.project.id, run_ref)
    _ensure_case_ticket(context, run, nodeid)
    run_case = resolve_run_case(db, run, nodeid)
    exchange = db.scalar(
        select(Exchange).where(
            Exchange.run_case_id == run_case.id,
            Exchange.exchange_index == index,
        )
    )
    if exchange is None:
        raise ApiError(404, "exchange_not_found", "此次交换记录不存在")
    return exchange_detail(db, exchange, body_limit)


@router.get("/runs/{run_ref}/cases/{nodeid:path}", response_model=RunCaseDetailOut)
def get_run_case(
    run_ref: str,
    nodeid: str,
    body_limit: int = Query(
        default=4000,
        ge=0,
        le=200000,
        description="日志与错误的最大字符数；0 表示不截断",
    ),
    context: ReadContext = Depends(require_read_context(SCOPE_RUNS_READ)),
    db: Session = Depends(get_db),
) -> RunCaseDetailOut:
    run = resolve_run(db, context.project.id, run_ref)
    _ensure_case_ticket(context, run, nodeid)
    run_case = resolve_run_case(db, run, nodeid)
    return run_case_detail(db, run_case, body_limit)
