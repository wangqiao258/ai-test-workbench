from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.deps import get_project_by_token
from app.db.models.project import Project
from app.db.session import get_db
from app.schemas.ingest import CatalogIn, CatalogOut
from app.services.idempotency import begin_idempotent, digest_model, finish_idempotent
from app.services.ingestion import upsert_catalog

router = APIRouter(prefix="/catalog", tags=["ingest"])


@router.post("", response_model=CatalogOut)
def upload_catalog(
    payload: CatalogIn,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    project: Project = Depends(get_project_by_token),
    db: Session = Depends(get_db),
) -> CatalogOut:
    record, replay = begin_idempotent(
        db, project.id, "catalog", idempotency_key, digest_model(payload)
    )
    if replay is not None:
        return replay

    result = upsert_catalog(db, project.id, payload)
    finish_idempotent(record, result.model_dump(mode="json"))
    db.commit()
    return result
