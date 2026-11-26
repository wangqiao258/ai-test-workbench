import uuid

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models.project import Project


def get_project_or_404(db: Session, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise ApiError(404, "project_not_found", "项目不存在")
    return project
