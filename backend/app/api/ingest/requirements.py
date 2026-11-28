"""AI 机需求工作队列：先领小队列，再按需取详情。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.defaults import REQUIREMENT_QUEUE_LIMIT
from app.core.deps import SCOPE_ASSETS_READ, require_token_scope
from app.db.models.project import Project
from app.db.session import get_db
from app.schemas.query import (
    RequirementAssociationsOut,
    RequirementOut,
    RequirementQueueOut,
)
from app.services.asset_views import requirement_out_one
from app.services.assets import load_requirement
from app.services.associations import requirement_associations
from app.services.requirement_queue import build_requirement_queue

router = APIRouter(prefix="/requirements", tags=["ingest"])


@router.get("/next", response_model=RequirementQueueOut)
def next_requirements(
    limit: int = Query(default=REQUIREMENT_QUEUE_LIMIT, ge=1, le=20),
    offset: int = Query(default=0, ge=0),
    tag: str | None = Query(default=None),
    project: Project = Depends(require_token_scope(SCOPE_ASSETS_READ)),
    db: Session = Depends(get_db),
) -> RequirementQueueOut:
    return build_requirement_queue(
        db, project.id, limit=limit, offset=offset, tag=tag
    )


@router.get("/{requirement_id}/associations", response_model=RequirementAssociationsOut)
def get_requirement_associations(
    requirement_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    project: Project = Depends(require_token_scope(SCOPE_ASSETS_READ)),
    db: Session = Depends(get_db),
) -> RequirementAssociationsOut:
    load_requirement(db, project.id, requirement_id)
    return requirement_associations(
        db, project.id, requirement_id, limit=limit
    )


@router.get("/{requirement_id}", response_model=RequirementOut)
def get_requirement(
    requirement_id: str,
    project: Project = Depends(require_token_scope(SCOPE_ASSETS_READ)),
    db: Session = Depends(get_db),
) -> RequirementOut:
    requirement = load_requirement(db, project.id, requirement_id)
    return requirement_out_one(db, project.id, requirement)
