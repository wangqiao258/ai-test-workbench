from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_membership
from app.db.models.identity import AppUser, ProjectMember
from app.db.models.review import AuditLog
from app.db.session import get_db
from app.schemas.review import AuditListOut, AuditOut
from app.services.review import actor_name

router = APIRouter(prefix="/projects/{project_id}/audit", tags=["review"])


@router.get("", response_model=AuditListOut)
def list_audit_logs(
    project_id: UUID,
    entity_type: str | None = Query(default=None, alias="entityType"),
    entity_id: str | None = Query(default=None, alias="entityId"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> AuditListOut:
    conditions = [AuditLog.project_id == project_id]
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type)
    if entity_id:
        conditions.append(AuditLog.entity_id == entity_id)

    total = db.scalar(select(func.count(AuditLog.id)).where(*conditions)) or 0
    rows = db.execute(
        select(AuditLog, AppUser.display_name, AppUser.email)
        .outerjoin(AppUser, AppUser.id == AuditLog.actor_user_id)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return AuditListOut(
        items=[
            AuditOut(
                id=log.id,
                entity_type=log.entity_type,
                entity_id=log.entity_id,
                action=log.action,
                actor=actor_name(display_name, email),
                before=log.before,
                after=log.after,
                created_at=log.created_at,
            )
            for log, display_name, email in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )
