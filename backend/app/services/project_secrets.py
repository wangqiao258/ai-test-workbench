import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.project import ProjectSecret


def list_project_secrets(db: Session, project_id: uuid.UUID) -> list[ProjectSecret]:
    return list(
        db.scalars(
            select(ProjectSecret)
            .where(ProjectSecret.project_id == project_id)
            .order_by(ProjectSecret.key)
        )
    )
