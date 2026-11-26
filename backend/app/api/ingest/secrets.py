from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import SCOPE_SECRETS_READ, require_token_scope
from app.core.secrets import decrypt_secret
from app.core.time import utcnow
from app.db.models.project import Project, ProjectSecret
from app.db.session import get_db
from app.schemas.secret import SecretOut, SecretResolveIn, SecretResolveOut
from app.services.audit import record_audit

router = APIRouter(prefix="/secrets", tags=["ingest"])


@router.get("", response_model=list[SecretOut])
def list_secrets(
    project: Project = Depends(require_token_scope(SCOPE_SECRETS_READ)),
    db: Session = Depends(get_db),
) -> list[SecretOut]:
    items = db.scalars(
        select(ProjectSecret)
        .where(ProjectSecret.project_id == project.id)
        .order_by(ProjectSecret.key)
    ).all()
    now = utcnow()
    return [
        SecretOut(
            key=item.key,
            description=item.description,
            expires_at=item.expires_at,
            last_used_at=item.last_used_at,
            updated_at=item.updated_at,
            expired=item.expires_at is not None and item.expires_at <= now,
        )
        for item in items
    ]


@router.post("/resolve", response_model=SecretResolveOut)
def resolve_secrets(
    payload: SecretResolveIn,
    project: Project = Depends(require_token_scope(SCOPE_SECRETS_READ)),
    db: Session = Depends(get_db),
) -> SecretResolveOut:
    items = db.scalars(
        select(ProjectSecret).where(
            ProjectSecret.project_id == project.id,
            ProjectSecret.key.in_(payload.keys),
        )
    ).all()
    now = utcnow()
    values: dict[str, str] = {}
    missing: list[str] = []
    for item in items:
        if item.expires_at is not None and item.expires_at <= now:
            missing.append(item.key)
            continue
        values[item.key] = decrypt_secret(item.value_ciphertext)
        item.last_used_at = now
    if values:
        record_audit(
            db,
            project.id,
            None,
            "project_secret",
            ",".join(sorted(values)),
            "resolve",
            after={"keys": sorted(values)},
        )
    missing.extend(key for key in payload.keys if key not in values and key not in missing)
    db.commit()
    return SecretResolveOut(values=values, missing=sorted(set(missing)))
