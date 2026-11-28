from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_membership
from app.db.models.identity import ProjectMember
from app.db.session import get_db
from app.schemas.review import AuditListOut
from app.services.audit import audit_logs_page

router = APIRouter(prefix="/projects/{project_id}/audit", tags=["review"])


@router.get("", response_model=AuditListOut)
def list_audit_logs(
    project_id: UUID,
    entity_type: str | None = Query(default=None, alias="entityType"),
    entity_id: str | None = Query(default=None, alias="entityId"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> AuditListOut:
    return audit_logs_page(
        db,
        project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        page=page,
        page_size=page_size,
    )
