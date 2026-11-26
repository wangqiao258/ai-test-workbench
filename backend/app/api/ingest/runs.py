from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.deps import SCOPE_ANALYSIS_WRITE, SCOPE_RUNS_WRITE, require_token_scope
from app.db.models.project import Project
from app.db.session import get_db
from app.schemas.ingest import AnalysisIn, AnalysisOut, RunIngestIn, RunIngestOut
from app.services.idempotency import begin_idempotent, digest_model, finish_idempotent
from app.services.ingestion import ingest_analysis, ingest_run
from app.services.runs import resolve_run
from app.services.storage import get_storage

router = APIRouter(prefix="/runs", tags=["ingest"])


@router.post("", response_model=RunIngestOut)
def upload_run(
    payload: RunIngestIn,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    project: Project = Depends(require_token_scope(SCOPE_RUNS_WRITE)),
    db: Session = Depends(get_db),
) -> RunIngestOut:
    record, replay = begin_idempotent(
        db, project.id, "runs", idempotency_key, digest_model(payload)
    )
    if replay is not None:
        return replay

    result = ingest_run(db, project.id, payload, get_storage())
    finish_idempotent(record, result.model_dump(mode="json"))
    db.commit()
    return result


@router.post("/{run_id}/analysis", response_model=AnalysisOut)
def upload_analysis(
    run_id: UUID,
    payload: AnalysisIn,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    project: Project = Depends(require_token_scope(SCOPE_ANALYSIS_WRITE)),
    db: Session = Depends(get_db),
) -> AnalysisOut:
    run = resolve_run(db, project.id, str(run_id))

    record, replay = begin_idempotent(
        db, project.id, "analysis", idempotency_key, digest_model(payload)
    )
    if replay is not None:
        return replay

    result = ingest_analysis(db, project.id, run, payload)
    finish_idempotent(record, result.model_dump(mode="json"))
    db.commit()
    return result
