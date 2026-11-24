import uuid

from sqlalchemy.orm import Session

from app.db.models.ingest import IngestionJob
from app.db.models.run import Artifact, Run, RunCase
from app.db.session import SessionLocal
from app.services.har import parse_har
from app.services.ingestion import replace_exchanges
from app.services.storage import LocalStorage, get_storage


def store_artifact(
    db: Session,
    storage: LocalStorage,
    project_id: uuid.UUID,
    run: Run,
    run_case: RunCase | None,
    kind: str,
    filename: str,
    content_type: str,
    data: bytes,
) -> Artifact:
    storage_key, size, sha256 = storage.save(project_id, run.id, filename, data, content_type)
    artifact = Artifact(
        project_id=project_id,
        run_id=run.id,
        run_case_id=run_case.id if run_case is not None else None,
        kind=kind,
        storage_key=storage_key,
        filename=filename,
        content_type=content_type,
        size_bytes=size,
        sha256=sha256,
    )
    db.add(artifact)
    db.flush()
    return artifact


def process_har_job(job_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        job = db.get(IngestionJob, job_id)
        if job is None:
            return
        job.status = "running"
        db.commit()

        try:
            artifact = db.get(Artifact, job.artifact_id) if job.artifact_id else None
            if artifact is None:
                raise ValueError("附件不存在")
            run_case = db.get(RunCase, artifact.run_case_id) if artifact.run_case_id else None
            if run_case is None:
                raise ValueError("HAR 未关联用例：上传时请提供 nodeid")
            exchanges = parse_har(get_storage().read(artifact.storage_key))
            replace_exchanges(db, get_storage(), job.project_id, artifact.run_id, run_case.id, exchanges)
            job.status = "succeeded"
            job.error = None
            db.commit()
        except Exception as exc:  # noqa: BLE001 - 后台任务需要把失败原因落到 job
            db.rollback()
            job = db.get(IngestionJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error = {"message": str(exc)}
                db.commit()
    finally:
        db.close()
