"""发现 / 缺陷的查询视图组装，供 v1 路由与 ingest 路由共用。"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pagination import paginate
from app.db.models.analysis import Finding
from app.db.models.asset import Operation
from app.db.models.identity import AppUser
from app.db.models.review import Defect, DefectEvent, Judgment
from app.db.models.run import Run
from app.schemas.review import (
    DefectDetailOut,
    DefectEventOut,
    DefectListOut,
    DefectOut,
    DefectStatus,
    FindingDetailOut,
    FindingListOut,
    FindingStatus,
    JudgmentOut,
)
from app.services.review import (
    actor_name,
    build_defect_out,
    build_finding_out,
    resolve_finding_operation_id,
)
from app.services.runs import resolve_run


def finding_detail(
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
    defect = db.scalar(select(Defect).where(Defect.finding_id == finding.id))
    base = build_finding_out(
        finding,
        run_external_id=run.external_id if run is not None else "",
        operation_id=resolve_finding_operation_id(db, finding, operations),
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


def defect_out(db: Session, defect: Defect) -> DefectOut:
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
    return build_defect_out(
        defect,
        finding_external_id=finding_external_id,
        run_external_id=run_external_id,
    )


def defect_detail(db: Session, defect: Defect) -> DefectDetailOut:
    base = defect_out(db, defect)
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


def findings_page(
    db: Session,
    project_id: UUID,
    *,
    run_id: str | None = None,
    status: FindingStatus | None = None,
    page: int = 1,
    page_size: int = 20,
) -> FindingListOut:
    conditions = [Finding.project_id == project_id]
    if run_id:
        run = resolve_run(db, project_id, run_id)
        conditions.append(Finding.run_id == run.id)
    if status is not None:
        conditions.append(Finding.status == status)

    findings, total = paginate(
        db,
        Finding,
        conditions,
        (Finding.created_at.desc(), Finding.external_id),
        page,
        page_size,
    )

    run_ids = {item.run_id for item in findings}
    run_map = (
        {run.id: run for run in db.scalars(select(Run).where(Run.id.in_(run_ids)))}
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
    return FindingListOut(
        items=[
            build_finding_out(
                item,
                run_external_id=(
                    run_map[item.run_id].external_id if item.run_id in run_map else ""
                ),
                operation_id=resolve_finding_operation_id(db, item, operations),
                defect_number=defect_map.get(item.id),
            )
            for item in findings
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


def defects_page(
    db: Session,
    project_id: UUID,
    *,
    status: DefectStatus | None = None,
    page: int = 1,
    page_size: int = 20,
) -> DefectListOut:
    conditions = [Defect.project_id == project_id]
    if status is not None:
        conditions.append(Defect.status == status)

    defects, total = paginate(
        db,
        Defect,
        conditions,
        (Defect.created_at.desc(), Defect.number),
        page,
        page_size,
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
    return DefectListOut(
        items=[
            build_defect_out(
                item,
                finding_external_id=finding_map.get(item.finding_id),
                run_external_id=run_map.get(item.run_id),
            )
            for item in defects
        ],
        page=page,
        page_size=page_size,
        total=total,
    )
