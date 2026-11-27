import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models.run import Run
from app.schemas.query import RunOut


def run_out(run: Run) -> RunOut:
    return RunOut(
        id=run.id,
        external_id=run.external_id,
        started_at=run.started_at,
        duration_ms=run.duration_ms,
        branch=run.branch,
        commit=run.commit_sha,
        environment=run.environment,
        stats=run.stats,
    )


def resolve_run(db: Session, project_id: uuid.UUID, run_ref: str) -> Run:
    """按 UUID 或 external_id 定位运行，并校验归属项目。"""
    run: Run | None = None
    try:
        run = db.get(Run, uuid.UUID(run_ref))
    except ValueError:
        pass
    if run is None:
        run = db.scalar(
            select(Run).where(Run.project_id == project_id, Run.external_id == run_ref)
        )
    if run is None or run.project_id != project_id:
        raise ApiError(404, "run_not_found", "运行不存在")
    return run
