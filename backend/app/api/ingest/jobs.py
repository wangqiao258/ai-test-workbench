from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_project_by_token
from app.core.errors import ApiError
from app.db.models.ingest import IngestionJob
from app.db.models.project import Project
from app.db.session import get_db
from app.schemas.ingest import JobOut

router = APIRouter(prefix="/jobs", tags=["ingest"])


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: UUID,
    project: Project = Depends(get_project_by_token),
    db: Session = Depends(get_db),
) -> JobOut:
    job = db.get(IngestionJob, job_id)
    if job is None or job.project_id != project.id:
        raise ApiError(404, "job_not_found", "任务不存在")
    return JobOut(
        id=job.id,
        status=job.status,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
