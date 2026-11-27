"""按发现 / 缺陷编号组装外部 AI 可直接分析的最小上下文。"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models.analysis import Analysis, Finding
from app.db.models.asset import (
    CaseOperationMarker,
    OpenApiDoc,
    Operation,
    Requirement,
)
from app.db.models.case import TestCase
from app.db.models.identity import AppUser
from app.db.models.review import Defect, DefectEvent, Judgment
from app.db.models.run import Artifact, Exchange, Run, RunCase
from app.schemas.agent import (
    DefectBundleOut,
    FindingBundleOut,
    RelatedOperationOut,
)
from app.schemas.query import (
    AnalysisQueryOut,
    ExchangeDetailOut,
    ExchangeRequestOut,
    ExchangeResponseOut,
    ExchangeSummaryOut,
    RunCaseDetailOut,
)
from app.schemas.review import (
    DefectDetailOut,
    DefectEventOut,
    FindingDetailOut,
    JudgmentOut,
)
from app.services.asset_views import operation_out_one, requirement_out_one
from app.services.review import (
    actor_name,
    build_defect_out,
    build_finding_out,
    match_operation_id,
    resolve_finding_operation_id,
)
from app.services.runs import run_out
from app.services.storage import get_storage

SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-project-token",
}


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None or limit <= 0 or len(text) <= limit:
        return text
    return f"{text[:limit]}\n…（已截断，原文 {len(text)} 字符）"


def _safe_headers(headers: list[dict] | None) -> list[dict]:
    items: list[dict] = []
    for header in headers or []:
        name = str(header.get("name") or "")
        value = str(header.get("value") or "")
        if name.lower() in SENSITIVE_HEADERS:
            value = "***"
        items.append({"name": name, "value": value})
    return items


def _artifact_body(db: Session, artifact_id: UUID | None) -> str | None:
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


def _case_meta(db: Session, run_case: RunCase) -> tuple[str | None, str | None]:
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


def run_case_detail(db: Session, run_case: RunCase, body_limit: int) -> RunCaseDetailOut:
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
        error=_truncate(run_case.error_text, body_limit),
        logs=[
            _truncate(item, body_limit) or ""
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


def exchange_detail(
    db: Session, exchange: Exchange, body_limit: int
) -> ExchangeDetailOut:
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
            headers=_safe_headers(exchange.request_headers),
            body=_truncate(request_body, body_limit),
            body_artifact_id=exchange.request_body_artifact_id,
        ),
        response=ExchangeResponseOut(
            status=exchange.status_code,
            headers=_safe_headers(exchange.response_headers),
            body=_truncate(response_body, body_limit),
            body_artifact_id=exchange.response_body_artifact_id,
        ),
        error=exchange.error_text,
    )


def pick_exchange(
    db: Session, run_case: RunCase, exchange_index: int | None
) -> Exchange | None:
    if exchange_index is not None:
        return db.scalar(
            select(Exchange).where(
                Exchange.run_case_id == run_case.id,
                Exchange.exchange_index == exchange_index,
            )
        )
    failed = db.scalar(
        select(Exchange)
        .where(
            Exchange.run_case_id == run_case.id,
            Exchange.status_code >= 400,
        )
        .order_by(Exchange.exchange_index)
    )
    if failed is not None:
        return failed
    return db.scalar(
        select(Exchange)
        .where(Exchange.run_case_id == run_case.id)
        .order_by(Exchange.exchange_index)
    )


def _finding_detail(
    db: Session,
    project_id: UUID,
    finding: Finding,
    operations: list[Operation] | None = None,
) -> FindingDetailOut:
    run = db.get(Run, finding.run_id)
    if operations is None:
        operations = list(
            db.scalars(select(Operation).where(Operation.project_id == project_id))
        )
    operation_id = resolve_finding_operation_id(db, finding, operations)
    defect = db.scalar(select(Defect).where(Defect.finding_id == finding.id))
    base = build_finding_out(
        finding,
        run_external_id=run.external_id if run is not None else "",
        operation_id=operation_id,
        defect_number=defect.number if defect is not None else None,
    )
    rows = db.execute(
        select(Judgment, AppUser.display_name, AppUser.email)
        .outerjoin(AppUser, AppUser.id == Judgment.actor_user_id)
        .where(Judgment.finding_id == finding.id)
        .order_by(Judgment.created_at)
    ).all()
    return FindingDetailOut(
        **base.model_dump(),
        judgments=[
            JudgmentOut(
                verdict=judgment.verdict,
                note=judgment.note,
                actor=actor_name(display_name, email),
                defect_id=(
                    defect.number
                    if judgment.defect_id is not None and defect is not None
                    else None
                ),
                created_at=judgment.created_at,
            )
            for judgment, display_name, email in rows
        ],
    )


def _defect_detail(db: Session, defect: Defect) -> DefectDetailOut:
    finding_external_id: str | None = None
    if defect.finding_id is not None:
        finding_external_id = db.scalar(
            select(Finding.external_id).where(Finding.id == defect.finding_id)
        )
    run_external_id: str | None = None
    if defect.run_id is not None:
        run_external_id = db.scalar(
            select(Run.external_id).where(Run.id == defect.run_id)
        )
    base = build_defect_out(
        defect,
        finding_external_id=finding_external_id,
        run_external_id=run_external_id,
    )
    rows = db.execute(
        select(DefectEvent, AppUser.display_name, AppUser.email)
        .outerjoin(AppUser, AppUser.id == DefectEvent.actor_user_id)
        .where(DefectEvent.defect_id == defect.id)
        .order_by(DefectEvent.created_at)
    ).all()
    return DefectDetailOut(
        **base.model_dump(),
        events=[
            DefectEventOut(
                from_status=event.from_status,
                to_status=event.to_status,
                note=event.note,
                actor=actor_name(display_name, email),
                created_at=event.created_at,
            )
            for event, display_name, email in rows
        ],
    )


def _analysis(
    db: Session, project_id: UUID, run_id: UUID | None
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


def _assets(
    db: Session,
    project_id: UUID,
    requirement_id: str | None,
    operation_id: str | None,
    include_assets: bool,
):
    if not include_assets:
        return None, None
    requirement = None
    if requirement_id:
        requirement_row = db.scalar(
            select(Requirement).where(
                Requirement.project_id == project_id,
                Requirement.external_id == requirement_id,
            )
        )
        if requirement_row is not None:
            requirement = requirement_out_one(db, project_id, requirement_row)
    operation = None
    if operation_id:
        operation_row = db.scalar(
            select(Operation).where(
                Operation.project_id == project_id,
                Operation.external_id == operation_id,
            )
        )
        if operation_row is not None and db.get(OpenApiDoc, operation_row.doc_id):
            operation = operation_out_one(db, project_id, operation_row)
    return requirement, operation


def _case_har(
    db: Session, run_case: RunCase, body_limit: int
) -> list[ExchangeDetailOut]:
    exchanges = db.scalars(
        select(Exchange)
        .where(Exchange.run_case_id == run_case.id)
        .order_by(Exchange.exchange_index)
    ).all()
    return [exchange_detail(db, item, body_limit) for item in exchanges]


def _case_operations(
    db: Session,
    run_case: RunCase,
    operations: list[Operation],
    include_assets: bool,
) -> list[RelatedOperationOut]:
    if not include_assets or run_case.case_id is None:
        return []
    markers = db.scalars(
        select(CaseOperationMarker).where(
            CaseOperationMarker.case_id == run_case.case_id
        )
    ).all()
    by_id = {item.external_id: item for item in operations}
    seen: set[str] = set()
    items: list[RelatedOperationOut] = []
    for marker in markers:
        operation = by_id.get(marker.operation_external_id)
        if operation is None or operation.external_id in seen:
            continue
        seen.add(operation.external_id)
        items.append(
            RelatedOperationOut(
                id=operation.external_id,
                method=operation.method,
                path=operation.path,
                summary=operation.summary,
            )
        )
    return items


def finding_bundle(
    db: Session,
    project_id: UUID,
    finding: Finding,
    *,
    body_limit: int,
    include_assets: bool,
) -> FindingBundleOut:
    operations = list(
        db.scalars(select(Operation).where(Operation.project_id == project_id))
    )
    detail = _finding_detail(db, project_id, finding, operations)
    run = db.get(Run, finding.run_id)
    case_detail = None
    exchange = None
    har: list[ExchangeDetailOut] = []
    related: list[RelatedOperationOut] = []
    picked: Exchange | None = None
    if run is not None:
        run_case = db.scalar(
            select(RunCase).where(
                RunCase.run_id == run.id, RunCase.nodeid == finding.nodeid
            )
        )
        if run_case is not None:
            case_detail = run_case_detail(db, run_case, body_limit)
            har = _case_har(db, run_case, body_limit)
            picked = pick_exchange(db, run_case, finding.exchange_index)
            if picked is not None:
                exchange = exchange_detail(db, picked, body_limit)
            related = _case_operations(db, run_case, operations, include_assets)
    operation_id = detail.operation_id
    if operation_id is None and picked is not None:
        operation_id = match_operation_id(
            operations, picked.method, picked.path_norm
        )
        if operation_id is not None:
            detail.operation_id = operation_id
    requirement, operation = _assets(
        db,
        project_id,
        finding.requirement_external_id,
        operation_id,
        include_assets,
    )
    defect = db.scalar(select(Defect).where(Defect.finding_id == finding.id))
    defect_out = (
        build_defect_out(
            defect,
            finding_external_id=finding.external_id,
            run_external_id=run.external_id if run is not None else None,
        )
        if defect is not None
        else None
    )
    return FindingBundleOut(
        finding=detail,
        run=run_out(run) if run is not None else None,
        case=case_detail,
        exchange=exchange,
        har=har,
        related_operations=related,
        requirement=requirement,
        operation=operation,
        defect=defect_out,
        analysis=_analysis(db, project_id, finding.run_id),
    )


def defect_bundle(
    db: Session,
    project_id: UUID,
    defect: Defect,
    *,
    body_limit: int,
    include_assets: bool,
) -> DefectBundleOut:
    operations = list(
        db.scalars(select(Operation).where(Operation.project_id == project_id))
    )
    detail = _defect_detail(db, defect)
    run = db.get(Run, defect.run_id) if defect.run_id is not None else None
    case_detail = None
    exchange = None
    har: list[ExchangeDetailOut] = []
    related: list[RelatedOperationOut] = []
    picked: Exchange | None = None
    if run is not None and defect.nodeid:
        run_case = db.scalar(
            select(RunCase).where(
                RunCase.run_id == run.id, RunCase.nodeid == defect.nodeid
            )
        )
        if run_case is not None:
            case_detail = run_case_detail(db, run_case, body_limit)
            har = _case_har(db, run_case, body_limit)
            picked = pick_exchange(db, run_case, defect.exchange_index)
            if picked is not None:
                exchange = exchange_detail(db, picked, body_limit)
            related = _case_operations(db, run_case, operations, include_assets)
    operation_id = detail.operation_id
    if operation_id is None and picked is not None:
        operation_id = match_operation_id(
            operations, picked.method, picked.path_norm
        )
        if operation_id is not None:
            detail.operation_id = operation_id
    requirement, operation = _assets(
        db,
        project_id,
        defect.requirement_external_id,
        operation_id,
        include_assets,
    )
    finding_detail = None
    if defect.finding_id is not None:
        finding = db.get(Finding, defect.finding_id)
        if finding is not None:
            finding_detail = _finding_detail(
                db, project_id, finding, operations
            )
    return DefectBundleOut(
        defect=detail,
        finding=finding_detail,
        run=run_out(run) if run is not None else None,
        case=case_detail,
        exchange=exchange,
        har=har,
        related_operations=related,
        requirement=requirement,
        operation=operation,
        analysis=_analysis(db, project_id, defect.run_id),
    )
