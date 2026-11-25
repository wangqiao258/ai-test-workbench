from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models.case import TestCase
from app.db.models.run_request import RunRequest


def get_run_request(db: Session, project_id: UUID, request_id: UUID) -> RunRequest:
    request = db.get(RunRequest, request_id)
    if request is None or request.project_id != project_id:
        raise ApiError(404, "run_request_not_found", "运行任务不存在")
    return request


def _validate_case_nodeids(
    db: Session, project_id: UUID, case_nodeids: list[str]
) -> list[str]:
    if not case_nodeids:
        return []
    rows = list(
        db.scalars(
            select(TestCase).where(
                TestCase.project_id == project_id,
                TestCase.nodeid.in_(case_nodeids),
            )
        )
    )
    by_nodeid = {case.nodeid: case for case in rows}
    missing = [nodeid for nodeid in case_nodeids if nodeid not in by_nodeid]
    archived = [
        nodeid
        for nodeid in case_nodeids
        if nodeid in by_nodeid and by_nodeid[nodeid].archived_at is not None
    ]
    if missing or archived:
        raise ApiError(
            422,
            "invalid_case_selection",
            "选择中包含不存在或已归档的用例",
            details={"missing": missing, "archived": archived},
        )
    return list(dict.fromkeys(case_nodeids))


def enqueue_run_request(
    db: Session,
    project_id: UUID,
    *,
    reason: str,
    spec_paths: list[str],
    case_nodeids: list[str],
    yaml_hash: str,
    requested_by: UUID | None,
) -> RunRequest:
    """创建排队中的运行任务；同一项目同时只允许一个待执行或执行中任务。"""
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

    selected = _validate_case_nodeids(
        db, project_id, [item.strip() for item in case_nodeids if item.strip()]
    )
    request = RunRequest(
        project_id=project_id,
        reason=reason.strip(),
        spec_paths=[item.strip() for item in spec_paths if item.strip()],
        case_nodeids=selected,
        yaml_hash=yaml_hash.strip(),
        requested_by=requested_by,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request
