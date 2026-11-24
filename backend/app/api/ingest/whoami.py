from fastapi import APIRouter, Depends

from app.core.deps import get_project_by_token
from app.db.models.project import Project

router = APIRouter(tags=["ingest"])


@router.get("/whoami")
def whoami(project: Project = Depends(get_project_by_token)) -> dict[str, dict[str, str]]:
    """供 pytest 插件校验 Token 是否可用。"""
    return {"project": {"id": str(project.id), "key": project.key, "name": project.name}}
