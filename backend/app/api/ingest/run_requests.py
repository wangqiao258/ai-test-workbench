from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import SCOPE_RUNS_EXECUTE, SCOPE_RUNS_READ, require_token_scope
from app.core.errors import ApiError
from app.db.models.project import Project
from app.db.session import get_db
from app.schemas.run_request import IngestRunRequestIn, IngestRunRequestOut
from app.services.run_requests import enqueue_run_request
from app.services.run_requests import get_run_request as load_run_request

router = APIRouter(prefix="/run-requests", tags=["ingest"])


def _spec_paths(raw_paths: list[str]) -> list[str]:
    paths: list[str] = []
    for raw in raw_paths:
        value = raw.strip()
        if not value:
            continue
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ApiError(
                422, "invalid_spec_path", "用例路径必须是相对路径且不能包含 .."
            )
        paths.append(path.as_posix())
    return paths


@router.post("", response_model=IngestRunRequestOut, status_code=201)
def trigger_run(
    payload: IngestRunRequestIn,
    project: Project = Depends(require_token_scope(SCOPE_RUNS_EXECUTE)),
    db: Session = Depends(get_db),
) -> IngestRunRequestOut:
    request = enqueue_run_request(
        db,
        project.id,
        reason=payload.reason,
        spec_paths=_spec_paths(payload.spec_paths),
        case_nodeids=payload.case_nodeids,
        yaml_hash="",
        requested_by=None,
    )
    return IngestRunRequestOut.model_validate(request)


@router.get("/{request_id}", response_model=IngestRunRequestOut)
def get_run_request(
    request_id: UUID,
    project: Project = Depends(require_token_scope(SCOPE_RUNS_READ)),
    db: Session = Depends(get_db),
) -> IngestRunRequestOut:
    return IngestRunRequestOut.model_validate(
        load_run_request(db, project.id, request_id)
    )
