from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.agent_rules import DEFAULT_RULES
from app.core.deps import get_membership, require_role
from app.db.models.identity import ProjectMember
from app.db.models.project import Project
from app.db.session import get_db
from app.schemas.project import AgentRulesIn, AgentRulesOut
from app.services.audit import record_audit
from app.services.projects import get_project_or_404

router = APIRouter(prefix="/projects/{project_id}/agent-rules", tags=["projects"])

ADMIN_ONLY = require_role("admin", message="仅项目管理员可以修改 AI 规则")


def _out(project: Project) -> AgentRulesOut:
    custom = project.agent_rules
    return AgentRulesOut(
        rules=list(custom) if custom is not None else list(DEFAULT_RULES),
        defaults=list(DEFAULT_RULES),
        is_custom=custom is not None,
    )


@router.get("", response_model=AgentRulesOut)
def get_agent_rules(
    project_id: UUID,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> AgentRulesOut:
    return _out(get_project_or_404(db, project_id))


@router.put("", response_model=AgentRulesOut)
def save_agent_rules(
    project_id: UUID,
    payload: AgentRulesIn,
    member: ProjectMember = Depends(ADMIN_ONLY),
    db: Session = Depends(get_db),
) -> AgentRulesOut:
    project = get_project_or_404(db, project_id)
    before = project.agent_rules
    project.agent_rules = payload.rules
    record_audit(
        db,
        project_id,
        member.user_id,
        "project_agent_rules",
        str(project_id),
        "update",
        before={"rules": before},
        after={"rules": payload.rules},
    )
    db.commit()
    return _out(project)


@router.delete("", response_model=AgentRulesOut)
def reset_agent_rules(
    project_id: UUID,
    member: ProjectMember = Depends(ADMIN_ONLY),
    db: Session = Depends(get_db),
) -> AgentRulesOut:
    project = get_project_or_404(db, project_id)
    before = project.agent_rules
    project.agent_rules = None
    record_audit(
        db,
        project_id,
        member.user_id,
        "project_agent_rules",
        str(project_id),
        "reset",
        before={"rules": before},
        after={"rules": None},
    )
    db.commit()
    return _out(project)
