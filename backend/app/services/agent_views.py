"""按发现 / 缺陷编号组装外部 AI 可直接分析的最小上下文。"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.analysis import Finding
from app.db.models.asset import (
    CaseOperationMarker,
    OpenApiDoc,
    Operation,
    Requirement,
)
from app.db.models.review import Defect
from app.db.models.run import Exchange, Run, RunCase
from app.schemas.agent import (
    DefectBundleOut,
    FindingBundleOut,
    RelatedOperationOut,
)
from app.schemas.query import (
    ExchangeDetailOut,
    RunCaseDetailOut,
)
from app.schemas.review import (
    DefectDetailOut,
    FindingDetailOut,
)
from app.services.asset_views import operation_out_one, requirement_out_one
from app.services.review import (
    build_defect_out,
    match_operation_id,
)
from app.services.review_views import defect_detail, finding_detail
from app.services.runs import (
    analysis_summary,
    exchange_detail,
    run_case_detail,
    run_out,
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
    return [
        exchange_detail(db, item, body_limit, redact_sensitive=True)
        for item in exchanges
    ]


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


def _case_context(
    db: Session,
    run: Run | None,
    nodeid: str,
    exchange_index: int | None,
    operations: list[Operation],
    *,
    body_limit: int,
    include_assets: bool,
) -> tuple[
    RunCaseDetailOut | None,
    ExchangeDetailOut | None,
    list[ExchangeDetailOut],
    list[RelatedOperationOut],
    Exchange | None,
]:
    if run is None or not nodeid:
        return None, None, [], [], None
    run_case = db.scalar(
        select(RunCase).where(RunCase.run_id == run.id, RunCase.nodeid == nodeid)
    )
    if run_case is None:
        return None, None, [], [], None
    case_detail = run_case_detail(db, run_case, body_limit)
    har = _case_har(db, run_case, body_limit)
    picked = pick_exchange(db, run_case, exchange_index)
    exchange = (
        exchange_detail(db, picked, body_limit, redact_sensitive=True)
        if picked is not None
        else None
    )
    related = _case_operations(db, run_case, operations, include_assets)
    return case_detail, exchange, har, related, picked


def _apply_picked_operation(
    detail: FindingDetailOut | DefectDetailOut,
    operations: list[Operation],
    picked: Exchange | None,
) -> None:
    if detail.operation_id is not None or picked is None:
        return
    matched = match_operation_id(operations, picked.method, picked.path_norm)
    if matched is not None:
        detail.operation_id = matched


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
    detail = finding_detail(db, project_id, finding, operations)
    run = db.get(Run, finding.run_id)
    case_detail, exchange, har, related, picked = _case_context(
        db,
        run,
        finding.nodeid,
        finding.exchange_index,
        operations,
        body_limit=body_limit,
        include_assets=include_assets,
    )
    _apply_picked_operation(detail, operations, picked)
    requirement, operation = _assets(
        db,
        project_id,
        finding.requirement_external_id,
        detail.operation_id,
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
        analysis=analysis_summary(db, project_id, finding.run_id),
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
    detail = defect_detail(db, defect)
    run = db.get(Run, defect.run_id) if defect.run_id is not None else None
    case_detail, exchange, har, related, picked = _case_context(
        db,
        run,
        defect.nodeid,
        defect.exchange_index,
        operations,
        body_limit=body_limit,
        include_assets=include_assets,
    )
    _apply_picked_operation(detail, operations, picked)
    requirement, operation = _assets(
        db,
        project_id,
        defect.requirement_external_id,
        detail.operation_id,
        include_assets,
    )
    finding_view = None
    if defect.finding_id is not None:
        finding = db.get(Finding, defect.finding_id)
        if finding is not None:
            finding_view = finding_detail(db, project_id, finding, operations)
    return DefectBundleOut(
        defect=detail,
        finding=finding_view,
        run=run_out(run) if run is not None else None,
        case=case_detail,
        exchange=exchange,
        har=har,
        related_operations=related,
        requirement=requirement,
        operation=operation,
        analysis=analysis_summary(db, project_id, defect.run_id),
    )
