from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_membership
from app.core.pagination import paginate
from app.db.models.identity import ProjectMember
from app.db.models.run_request import RunRequest
from app.db.session import get_db
from app.schemas.run_request import (
    RunRequestCreateIn,
    RunRequestListOut,
    RunRequestOut,
)
from app.services.run_requests import enqueue_run_request
from app.services.run_requests import get_run_request as load_run_request

router = APIRouter(prefix="/projects/{project_id}/run-requests", tags=["runner"])


@router.post("", response_model=RunRequestOut, status_code=201)
def create_run_request(
    project_id: UUID,
    payload: RunRequestCreateIn,
    member: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> RunRequestOut:
    request = enqueue_run_request(
        db,
        project_id,
        reason=payload.reason,
        spec_paths=payload.spec_paths,
        case_nodeids=payload.case_nodeids,
        yaml_hash=payload.yaml_hash,
        requested_by=member.user_id,
    )
    return RunRequestOut.model_validate(request)


@router.get("", response_model=RunRequestListOut)
def list_run_requests(
    project_id: UUID,
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> RunRequestListOut:
    conditions = [RunRequest.project_id == project_id]
    if status:
        conditions.append(RunRequest.status == status)

    rows, total = paginate(
        db,
        RunRequest,
        conditions,
        (RunRequest.created_at.desc(), RunRequest.id),
        page,
        page_size,
    )
    return RunRequestListOut(
        items=[RunRequestOut.model_validate(item) for item in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{request_id}", response_model=RunRequestOut)
def get_run_request(
    project_id: UUID,
    request_id: UUID,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> RunRequestOut:
    return RunRequestOut.model_validate(load_run_request(db, project_id, request_id))
