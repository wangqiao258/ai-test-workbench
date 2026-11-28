from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_membership
from app.db.models.identity import ProjectMember
from app.db.session import get_db
from app.schemas.agent import AiTicketOut
from app.schemas.review import (
    DefectDetailOut,
    DefectListOut,
    DefectOut,
    DefectPatchIn,
    DefectStatus,
)
from app.services.review import defect_ai_ticket, load_defect, update_defect_status
from app.services.review_views import defect_detail, defect_out, defects_page

router = APIRouter(prefix="/projects/{project_id}/defects", tags=["review"])


@router.get("", response_model=DefectListOut)
def list_defects(
    project_id: UUID,
    status: DefectStatus | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> DefectListOut:
    return defects_page(
        db,
        project_id,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.get("/{defect_id}", response_model=DefectDetailOut)
def get_defect(
    project_id: UUID,
    defect_id: str,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> DefectDetailOut:
    return defect_detail(db, load_defect(db, project_id, defect_id))


@router.post("/{defect_id}/ai-ticket", response_model=AiTicketOut)
def create_defect_ai_ticket(
    project_id: UUID,
    defect_id: str,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> AiTicketOut:
    return defect_ai_ticket(db, load_defect(db, project_id, defect_id))


@router.patch("/{defect_id}", response_model=DefectOut)
def patch_defect(
    project_id: UUID,
    defect_id: str,
    payload: DefectPatchIn,
    member: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> DefectOut:
    defect = update_defect_status(
        db,
        project_id,
        defect_id,
        payload.status,
        payload.version,
        member.user_id,
    )
    result = defect_out(db, defect)
    db.commit()
    return result
