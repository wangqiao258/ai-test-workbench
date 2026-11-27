from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.runs import run_out
from app.core.deps import get_current_user, get_membership, require_role
from app.core.errors import ApiError
from app.db.models.analysis import Finding
from app.db.models.case import TestCase
from app.db.models.identity import AppUser, ProjectMember
from app.db.models.project import Project
from app.db.models.review import Defect
from app.db.models.run import Run
from app.db.session import get_db
from app.schemas.project import ProjectCreateIn, ProjectOut, ProjectUpdateIn
from app.schemas.query import SummaryOut
from app.services.audit import record_audit
from app.services.projects import get_project_or_404

router = APIRouter(prefix="/projects", tags=["projects"])


def _project_out(project: Project, role: str) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        entries=project.entries or [],
        test_repo_url=project.test_repo_url,
        test_repo_ref=project.test_repo_ref,
        updated_at=project.updated_at,
        role=role,
    )


def list_project_outs(db: Session, user_id: UUID) -> list[ProjectOut]:
    rows = db.execute(
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user_id)
        .order_by(Project.name)
    ).all()
    return [_project_out(project, role) for project, role in rows]


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
    is_admin = db.scalar(
        select(ProjectMember)
        .where(ProjectMember.user_id == user.id, ProjectMember.role == "admin")
        .limit(1)
    )
    if is_admin is None:
        raise ApiError(403, "forbidden", "仅项目管理员可以创建项目")

    project = Project(
        name=payload.name,
        entries=[entry.model_dump() for entry in payload.entries],
    )
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="admin"))
    record_audit(
        db,
        project.id,
        user.id,
        "project",
        str(project.id),
        "create",
        after={"name": project.name, "entries": project.entries},
    )
    db.commit()
    db.refresh(project)
    return _project_out(project, "admin")


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

    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    before = {key: getattr(project, key) for key in updates}
    for key, value in updates.items():
        setattr(project, key, value)
    record_audit(
        db,
        project.id,
        member.user_id,
        "project",
        str(project.id),
        "update",
        before=before,
        after=updates,
    )
    db.commit()
    db.refresh(project)
    return _project_out(project, member.role)


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: UUID,
    member: ProjectMember = Depends(
        require_role("admin", message="仅项目管理员可以删除项目")
    ),
    db: Session = Depends(get_db),
) -> None:
    project = get_project_or_404(db, project_id)

    membership_count = (
        db.scalar(
            select(func.count(ProjectMember.project_id)).where(
                ProjectMember.user_id == member.user_id
            )
        )
        or 0
    )
    if membership_count <= 1:
        raise ApiError(
            409,
            "last_project",
            "这是你唯一参与的项目，删除后将无法进入工作台；请先创建或加入其他项目",
        )

    db.delete(project)
    db.commit()


@router.get("/{project_id}/summary", response_model=SummaryOut)
def project_summary(
    project_id: UUID,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> SummaryOut:
    pending_findings = (
        db.scalar(
            select(func.count(Finding.id)).where(
                Finding.project_id == project_id, Finding.status == "pending"
            )
        )
        or 0
    )
    case_count = (
        db.scalar(select(func.count(TestCase.id)).where(TestCase.project_id == project_id))
        or 0
    )
    open_defects = (
        db.scalar(
            select(func.count(Defect.id)).where(
                Defect.project_id == project_id, Defect.status != "closed"
            )
        )
        or 0
    )
    run_count = (
        db.scalar(select(func.count(Run.id)).where(Run.project_id == project_id)) or 0
    )
    recent_runs = db.scalars(
        select(Run)
        .where(Run.project_id == project_id)
        .order_by(Run.started_at.desc(), Run.created_at.desc())
        .limit(5)
    ).all()
    return SummaryOut(
        pending_findings=pending_findings,
        open_defects=open_defects,
        case_count=case_count,
        run_count=run_count,
        recent_runs=[run_out(run) for run in recent_runs],
    )

