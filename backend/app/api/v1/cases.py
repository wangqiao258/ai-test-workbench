from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_membership, require_role
from app.db.models.identity import ProjectMember
from app.db.session import get_db
from app.schemas.query import CaseArchiveIn, CaseArchiveOut, CaseListOut
from app.services.cases import RunStatus, cases_page
from app.services.cases import set_case_archived as archive_case

router = APIRouter(prefix="/projects/{project_id}/cases", tags=["query"])

EDITOR = require_role("admin", "tester", message="当前角色无权修改用例")


@router.get("", response_model=CaseListOut)
def list_cases(
    project_id: UUID,
    q: str | None = None,
    status: RunStatus | None = None,
    requirement: str | None = None,
    operation: str | None = None,
    include_archived: bool = Query(default=False, alias="includeArchived"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> CaseListOut:
    return cases_page(
        db,
        project_id,
        q=q,
        status=status,
        requirement=requirement,
        operation=operation,
        include_archived=include_archived,
        page=page,
        page_size=page_size,
    )


@router.patch("", response_model=CaseArchiveOut)
def set_case_archived(
    project_id: UUID,
    payload: CaseArchiveIn,
    member: ProjectMember = Depends(EDITOR),
    db: Session = Depends(get_db),
) -> CaseArchiveOut:
    result = archive_case(
        db, project_id, payload.nodeid, payload.archived, member.user_id
    )
    db.commit()
    return result
