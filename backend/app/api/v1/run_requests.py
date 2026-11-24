from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_membership
from app.core.errors import ApiError
from app.db.models.identity import ProjectMember
from app.db.models.run_request import RunRequest
from app.db.session import get_db
from app.schemas.run_request import (
    RunRequestCreateIn,
    RunRequestListOut,
    RunRequestOut,
)

router = APIRouter(prefix="/projects/{project_id}/run-requests", tags=["runner"])


def _out(request: RunRequest) -> RunRequestOut:
    return RunRequestOut(
        id=request.id,
        status=request.status,
        reason=request.reason,
        spec_paths=request.spec_paths or [],
        yaml_hash=request.yaml_hash,
        requested_by=request.requested_by,
        run_external_id=request.run_external_id,
        log_path=request.log_path,
        exit_code=request.exit_code,
        error=request.error,
        created_at=request.created_at,
        started_at=request.started_at,
        finished_at=request.finished_at,
    )


@router.post("", response_model=RunRequestOut, status_code=201)
def create_run_request(
    project_id: UUID,
    payload: RunRequestCreateIn,
    member: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> RunRequestOut:
    active = db.scalar(
        select(RunRequest).where(
            RunRequest.project_id == project_id,
            RunRequest.status.in_(("queued", "running")),
        )
    )
    if active is not None:
        raise ApiError(
            409,
            "run_request_active",
            "该项目已有待执行或执行中的任务",
            details={"id": str(active.id), "status": active.status},
        )

    request = RunRequest(
        project_id=project_id,
        reason=payload.reason.strip(),
        spec_paths=[item.strip() for item in payload.spec_paths if item.strip()],
        yaml_hash=payload.yaml_hash.strip(),
        requested_by=member.user_id,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return _out(request)


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

    total = db.scalar(select(func.count(RunRequest.id)).where(*conditions)) or 0
    rows = db.scalars(
        select(RunRequest)
        .where(*conditions)
        .order_by(RunRequest.created_at.desc(), RunRequest.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return RunRequestListOut(
        items=[_out(item) for item in rows],
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
    request = db.get(RunRequest, request_id)
    if request is None or request.project_id != project_id:
        raise ApiError(404, "run_request_not_found", "运行任务不存在")
    return _out(request)
