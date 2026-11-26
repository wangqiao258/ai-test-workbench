from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_membership, require_role
from app.core.errors import ApiError
from app.core.secrets import decrypt_secret, encrypt_secret
from app.core.time import utcnow
from app.db.models.identity import ProjectMember
from app.db.models.project import ProjectSecret
from app.db.session import get_db
from app.schemas.secret import SecretOut, SecretUpsertIn, normalize_secret_key
from app.services.audit import record_audit
from app.services.project_secrets import list_project_secrets

router = APIRouter(prefix="/projects/{project_id}/secrets", tags=["secrets"])

ADMIN_ONLY = require_role("admin", message="仅项目管理员可以管理测试凭据")


def _out(item: ProjectSecret, now: datetime, value: str | None = None) -> SecretOut:
    return SecretOut(
        key=item.key,
        description=item.description,
        expires_at=item.expires_at,
        last_used_at=item.last_used_at,
        updated_at=item.updated_at,
        expired=item.expires_at is not None and item.expires_at <= now,
        value=value,
    )


@router.get("", response_model=list[SecretOut])
def list_secrets(
    project_id: UUID,
    _: ProjectMember = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[SecretOut]:
    items = list_project_secrets(db, project_id)
    now = utcnow()
    return [_out(item, now, decrypt_secret(item.value_ciphertext)) for item in items]


@router.put("/{key}", response_model=SecretOut)
def upsert_secret(
    project_id: UUID,
    key: str,
    payload: SecretUpsertIn,
    member: ProjectMember = Depends(ADMIN_ONLY),
    db: Session = Depends(get_db),
) -> SecretOut:
    try:
        normalized = normalize_secret_key(key)
    except ValueError as exc:
        raise ApiError(422, "invalid_secret_key", str(exc)) from exc

    item = db.scalar(
        select(ProjectSecret).where(
            ProjectSecret.project_id == project_id, ProjectSecret.key == normalized
        )
    )
    before = None
    if item is None:
        item = ProjectSecret(
            project_id=project_id,
            key=normalized,
            value_ciphertext=encrypt_secret(payload.value),
            description=payload.description,
            expires_at=payload.expires_at,
        )
        db.add(item)
    else:
        before = {
            "description": item.description,
            "expiresAt": item.expires_at.isoformat() if item.expires_at else None,
        }
        item.value_ciphertext = encrypt_secret(payload.value)
        item.description = payload.description
        item.expires_at = payload.expires_at

    db.flush()
    record_audit(
        db,
        project_id,
        member.user_id,
        "project_secret",
        normalized,
        "upsert",
        before=before,
        after={
            "description": item.description,
            "expiresAt": item.expires_at.isoformat() if item.expires_at else None,
        },
    )
    db.commit()
    db.refresh(item)
    return _out(item, utcnow(), payload.value)


@router.delete("/{key}", status_code=204)
def delete_secret(
    project_id: UUID,
    key: str,
    member: ProjectMember = Depends(ADMIN_ONLY),
    db: Session = Depends(get_db),
) -> None:
    try:
        normalized = normalize_secret_key(key)
    except ValueError as exc:
        raise ApiError(422, "invalid_secret_key", str(exc)) from exc

    item = db.scalar(
        select(ProjectSecret).where(
            ProjectSecret.project_id == project_id, ProjectSecret.key == normalized
        )
    )
    if item is None:
        raise ApiError(404, "secret_not_found", "测试凭据不存在")

    db.delete(item)
    record_audit(
        db,
        project_id,
        member.user_id,
        "project_secret",
        normalized,
        "delete",
        before={"description": item.description},
    )
    db.commit()
