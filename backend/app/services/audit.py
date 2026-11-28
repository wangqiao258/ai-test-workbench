from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.identity import AppUser
from app.db.models.review import AuditLog
from app.schemas.review import AuditListOut, AuditOut


def record_audit(
    db: Session,
    project_id: UUID,
    actor_user_id: UUID | None,
    entity_type: str,
    entity_id: str,
    action: str,
    *,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_user_id=actor_user_id,
            before=before,
            after=after,
        )
    )


def audit_logs_page(
    db: Session,
    project_id: UUID,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
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
                actor=display_name or email or "系统",
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
