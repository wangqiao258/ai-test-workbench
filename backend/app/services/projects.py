import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models.analysis import Finding
from app.db.models.case import TestCase
from app.db.models.identity import ProjectMember
from app.db.models.project import Project, ProjectSecret
from app.db.models.review import Defect
from app.db.models.run import Run
from app.schemas.project import ProjectCreateIn, ProjectOut, ProjectUpdateIn
from app.schemas.query import SummaryOut
from app.services.audit import record_audit
from app.services.runs import run_out


def get_project_or_404(db: Session, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise ApiError(404, "project_not_found", "项目不存在")
    return project


def project_out(project: Project, role: str) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        entries=project.entries or [],
        test_repo_url=project.test_repo_url,
        test_repo_ref=project.test_repo_ref,
        updated_at=project.updated_at,
        role=role,
    )


def list_project_outs(db: Session, user_id: uuid.UUID) -> list[ProjectOut]:
    rows = db.execute(
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user_id)
        .order_by(Project.name)
    ).all()
    return [project_out(project, role) for project, role in rows]


def create_project(db: Session, user_id: uuid.UUID, payload: ProjectCreateIn) -> Project:
    is_admin = db.scalar(
        select(ProjectMember)
        .where(ProjectMember.user_id == user_id, ProjectMember.role == "admin")
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
    db.add(ProjectMember(project_id=project.id, user_id=user_id, role="admin"))
    record_audit(
        db,
        project.id,
        user_id,
        "project",
        str(project.id),
        "create",
        after={"name": project.name, "entries": project.entries},
    )
    return project


def update_project(
    db: Session, project: Project, payload: ProjectUpdateIn, actor_user_id: uuid.UUID
) -> Project:
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    before = {key: getattr(project, key) for key in updates}
    for key, value in updates.items():
        setattr(project, key, value)
    record_audit(
        db,
        project.id,
        actor_user_id,
        "project",
        str(project.id),
        "update",
        before=before,
        after=updates,
    )
    return project


def delete_project(db: Session, project: Project, actor_user_id: uuid.UUID) -> None:
    membership_count = (
        db.scalar(
            select(func.count(ProjectMember.project_id)).where(
                ProjectMember.user_id == actor_user_id
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


def list_project_secrets(db: Session, project_id: uuid.UUID) -> list[ProjectSecret]:
    return list(
        db.scalars(
            select(ProjectSecret)
            .where(ProjectSecret.project_id == project_id)
            .order_by(ProjectSecret.key)
        )
    )


def project_summary(db: Session, project_id: uuid.UUID) -> SummaryOut:
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
