"""供外部 AI 按编号读取发现、缺陷与运行证据的只读接口。

项目由 X-Project-Token 绑定，因此 FND-003 / DEF-1001 这类编号即可定位，
不需要再传项目 UUID。所有接口仅使用 GET，要求 runs:read；
令牌具备 assets:read 时额外附带需求与契约。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import (
    SCOPE_ASSETS_READ,
    SCOPE_RUNS_READ,
    ReadContext,
    require_read_context,
)
from app.core.errors import ApiError
from app.db.models.run import Run
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
    finding_bundle,
)
from app.services.review import load_defect, load_finding
from app.services.review_views import defects_page, findings_page
from app.services.runs import (
    exchange_detail,
    load_exchange,
    resolve_run,
    resolve_run_case,
    run_case_detail,
)

router = APIRouter(tags=["ingest"])


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


@router.get("/findings", response_model=FindingListOut)
def list_findings(
    status: FindingStatus | None = None,
    run_filter: str | None = Query(default=None, alias="run"),
    limit: int = Query(default=20, ge=1, le=100),
    context: ReadContext = Depends(require_read_context(SCOPE_RUNS_READ)),
    db: Session = Depends(get_db),
) -> FindingListOut:
    _ensure_list_allowed(context)
    return findings_page(
        db,
        context.project.id,
        run_id=run_filter,
        status=status,
        page=1,
        page_size=limit,
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
    finding = load_finding(db, context.project.id, finding_id)
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
    return defects_page(
        db,
        context.project.id,
        status=status,
        page=1,
        page_size=limit,
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
    defect = load_defect(db, context.project.id, defect_id)
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
    exchange = load_exchange(db, run_case, index)
    return exchange_detail(db, exchange, body_limit, redact_sensitive=True)


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
