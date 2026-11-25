from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_membership
from app.core.errors import ApiError
from app.core.pagination import paginate
from app.db.models.analysis import Finding
from app.db.models.identity import AppUser, ProjectMember
from app.db.models.review import Defect, DefectEvent
from app.db.models.run import Run
from app.db.session import get_db
from app.schemas.review import (
    DefectDetailOut,
    DefectEventOut,
    DefectListOut,
    DefectOut,
    DefectPatchIn,
    DefectStatus,
)
from app.services.review import actor_name, build_defect_out, update_defect_status

router = APIRouter(prefix="/projects/{project_id}/defects", tags=["review"])


def _load_defect(db: Session, project_id: UUID, defect_id: str) -> Defect:
    defect = db.scalar(
        select(Defect).where(
            Defect.project_id == project_id, Defect.number == defect_id
        )
    )
    if defect is None:
        raise ApiError(404, "defect_not_found", "缺陷不存在")
    return defect


def _defect_out(db: Session, defect: Defect) -> DefectOut:
    finding_external_id: str | None = None
    if defect.finding_id is not None:
        finding_external_id = db.scalar(
            select(Finding.external_id).where(Finding.id == defect.finding_id)
        )
    run_external_id: str | None = None
    if defect.run_id is not None:
        run_external_id = db.scalar(select(Run.external_id).where(Run.id == defect.run_id))
    return build_defect_out(
        defect,
        finding_external_id=finding_external_id,
        run_external_id=run_external_id,
    )


@router.get("", response_model=DefectListOut)
def list_defects(
    project_id: UUID,
    status: DefectStatus | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
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
        {run.id: run.external_id for run in db.scalars(select(Run).where(Run.id.in_(run_ids)))}
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


@router.get("/{defect_id}", response_model=DefectDetailOut)
def get_defect(
    project_id: UUID,
    defect_id: str,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> DefectDetailOut:
    defect = _load_defect(db, project_id, defect_id)
    base = _defect_out(db, defect)
    rows = db.execute(
        select(DefectEvent, AppUser.display_name, AppUser.email)
        .outerjoin(AppUser, AppUser.id == DefectEvent.actor_user_id)
        .where(DefectEvent.defect_id == defect.id)
        .order_by(DefectEvent.created_at)
    ).all()
    events = [
        DefectEventOut(
            from_status=event.from_status,
            to_status=event.to_status,
            note=event.note,
            actor=actor_name(display_name, email),
            created_at=event.created_at,
        )
        for event, display_name, email in rows
    ]
    return DefectDetailOut(**base.model_dump(), events=events)


@router.patch("/{defect_id}", response_model=DefectOut)
def patch_defect(
    project_id: UUID,
    defect_id: str,
    payload: DefectPatchIn,
    member: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> DefectOut:
    defect = update_defect_status(
        db,
        project_id,
        defect_id,
        payload.status,
        payload.version,
        member.user_id,
    )
    result = _defect_out(db, defect)
    db.commit()
    return result
