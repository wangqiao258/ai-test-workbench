from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_membership, require_role
from app.db.models.identity import AppUser, ProjectMember
from app.db.session import get_db
from app.schemas.project import ProjectCreateIn, ProjectOut, ProjectUpdateIn
from app.schemas.query import SummaryOut
from app.services.projects import (
    create_project as create_project_service,
)
from app.services.projects import (
    delete_project as delete_project_service,
)
from app.services.projects import (
    get_project_or_404,
    list_project_outs,
    project_out,
)
from app.services.projects import (
    project_summary as project_summary_service,
)
from app.services.projects import (
    update_project as update_project_service,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProjectOut]:
    return list_project_outs(db, user.id)


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    payload: ProjectCreateIn,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectOut:
    project = create_project_service(db, user.id, payload)
    db.commit()
    db.refresh(project)
    return project_out(project, "admin")


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: UUID,
    payload: ProjectUpdateIn,
    member: ProjectMember = Depends(
        require_role("admin", message="仅项目管理员可以修改项目")
    ),
    db: Session = Depends(get_db),
) -> ProjectOut:
    project = get_project_or_404(db, project_id)
    update_project_service(db, project, payload, member.user_id)
    db.commit()
    db.refresh(project)
    return project_out(project, member.role)


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: UUID,
    member: ProjectMember = Depends(
        require_role("admin", message="仅项目管理员可以删除项目")
    ),
    db: Session = Depends(get_db),
) -> None:
    project = get_project_or_404(db, project_id)
    delete_project_service(db, project, member.user_id)
    db.commit()


@router.get("/{project_id}/summary", response_model=SummaryOut)
def project_summary(
    project_id: UUID,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> SummaryOut:
    return project_summary_service(db, project_id)
