from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.review import AuditLog


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
