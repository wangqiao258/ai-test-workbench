from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_project_by_token
from app.core.errors import ApiError
from app.db.models.ingest import IngestionJob
from app.db.models.project import Project
from app.db.models.run import Run, RunCase
from app.db.session import get_db
from app.schemas.ingest import ArtifactOut
from app.services.artifacts import process_har_job, store_artifact
from app.services.idempotency import begin_idempotent, digest_bytes, finish_idempotent
from app.services.storage import get_storage

router = APIRouter(prefix="/runs", tags=["ingest"])

ALLOWED_KINDS = {"har", "screenshot", "attachment"}


@router.post("/{run_id}/artifacts", response_model=ArtifactOut, status_code=202)
async def upload_artifact(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    kind: str = Form(default="har"),
    nodeid: str | None = Form(default=None),
    file: UploadFile = File(...),
    project: Project = Depends(get_project_by_token),
    db: Session = Depends(get_db),
) -> ArtifactOut:
    if kind not in ALLOWED_KINDS:
        raise ApiError(
            422,
            "invalid_artifact_kind",
            "kind 不合法",
            details={"allowed": sorted(ALLOWED_KINDS), "received": kind},
        )

    data = await file.read()
    request_digest = digest_bytes(kind.encode(), (nodeid or "").encode(), data)
    record, replay = begin_idempotent(db, project.id, "artifacts", idempotency_key, request_digest)
    if replay is not None:
        return replay

    run = db.get(Run, run_id)
    if run is None or run.project_id != project.id:
        raise ApiError(404, "run_not_found", "运行不存在")

    run_case: RunCase | None = None
    if nodeid:
        run_case = db.scalar(
            select(RunCase).where(RunCase.run_id == run.id, RunCase.nodeid == nodeid)
        )
        if run_case is None:
            raise ApiError(
                422,
                "unknown_nodeid",
                "该 nodeid 不属于当前运行",
                details={"nodeid": nodeid},
            )
    if kind == "har" and run_case is None:
        raise ApiError(
            422,
            "missing_nodeid",
            "上传 HAR 必须提供 nodeid，用于把交换记录挂到具体用例",
        )

    filename = file.filename or f"{kind}-upload"
    artifact = store_artifact(
        db,
        get_storage(),
        project.id,
        run,
        run_case,
        kind,
        filename,
        file.content_type or "application/octet-stream",
        data,
    )

    job: IngestionJob | None = None
    if kind == "har":
        job = IngestionJob(
            project_id=project.id,
            artifact_id=artifact.id,
            endpoint="artifacts",
            status="queued",
        )
        db.add(job)
        db.flush()

    response = ArtifactOut(
        id=artifact.id,
        kind=artifact.kind,
        filename=artifact.filename,
        size_bytes=artifact.size_bytes,
        sha256=artifact.sha256,
        job_id=job.id if job is not None else None,
    )
    finish_idempotent(record, response.model_dump(mode="json"))
    db.commit()

    if job is not None:
        background_tasks.add_task(process_har_job, job.id)
    return response
