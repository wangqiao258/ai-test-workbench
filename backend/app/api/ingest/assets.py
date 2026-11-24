from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.deps import get_project_by_token
from app.db.models.project import Project
from app.db.session import get_db
from app.schemas.asset import (
    OpenApiBatchIn,
    OpenApiIngestOut,
    RequirementBatchIn,
    RequirementIngestOut,
)
from app.services.assets import upsert_openapi, upsert_requirements
from app.services.idempotency import begin_idempotent, digest_model, finish_idempotent

router = APIRouter(tags=["ingest"])


@router.post("/requirements", response_model=RequirementIngestOut)
def upload_requirements(
    payload: RequirementBatchIn,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    project: Project = Depends(get_project_by_token),
    db: Session = Depends(get_db),
) -> RequirementIngestOut:
    record, replay = begin_idempotent(
        db, project.id, "requirements", idempotency_key, digest_model(payload)
    )
    if replay is not None:
        return RequirementIngestOut(**replay)

    count = upsert_requirements(db, project.id, payload)
    result = RequirementIngestOut(requirement_count=count)
    finish_idempotent(record, result.model_dump(mode="json"))
    db.commit()
    return result


@router.post("/openapi", response_model=OpenApiIngestOut)
def upload_openapi(
    payload: OpenApiBatchIn,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    project: Project = Depends(get_project_by_token),
    db: Session = Depends(get_db),
) -> OpenApiIngestOut:
    record, replay = begin_idempotent(
        db, project.id, "openapi", idempotency_key, digest_model(payload)
    )
    if replay is not None:
        return OpenApiIngestOut(**replay)

    result = upsert_openapi(db, project.id, payload)
    finish_idempotent(record, result.model_dump(mode="json"))
    db.commit()
    return result
