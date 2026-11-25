from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import ISSUABLE_TOKEN_SCOPES, require_role
from app.core.errors import ApiError
from app.core.security import generate_api_token
from app.core.time import utcnow
from app.db.models.identity import ProjectMember
from app.db.models.project import ApiToken
from app.db.session import get_db
from app.schemas.token import TokenCreatedOut, TokenCreateIn, TokenOut
from app.services.audit import record_audit

router = APIRouter(prefix="/projects/{project_id}/tokens", tags=["tokens"])

ADMIN_ONLY = require_role("admin", message="仅项目管理员可以管理接入令牌")


def _status(token: ApiToken, now: datetime) -> str:
    if token.revoked_at is not None:
        return "revoked"
    if token.expires_at is not None and token.expires_at <= now:
        return "expired"
    return "active"


def _token_out(token: ApiToken, now: datetime) -> TokenOut:
    return TokenOut(
        id=token.id,
        name=token.name,
        prefix=token.token_prefix,
        scopes=list(token.scopes or []),
        status=_status(token, now),
        last_used_at=token.last_used_at,
        expires_at=token.expires_at,
        created_at=token.created_at,
    )


@router.get("", response_model=list[TokenOut])
def list_tokens(
    project_id: UUID,
    _: ProjectMember = Depends(ADMIN_ONLY),
    db: Session = Depends(get_db),
) -> list[TokenOut]:
    tokens = db.scalars(
        select(ApiToken)
        .where(ApiToken.project_id == project_id)
        .order_by(ApiToken.created_at.desc())
    ).all()
    now = utcnow()
    return [_token_out(token, now) for token in tokens]


@router.post("", response_model=TokenCreatedOut, status_code=201)
def create_token(
    project_id: UUID,
    payload: TokenCreateIn,
    member: ProjectMember = Depends(ADMIN_ONLY),
    db: Session = Depends(get_db),
) -> TokenCreatedOut:
    invalid = sorted(set(payload.scopes) - set(ISSUABLE_TOKEN_SCOPES))
    if invalid:
        raise ApiError(
            422,
            "invalid_scope",
            "包含未知权限",
            details={"invalid": invalid, "allowed": list(ISSUABLE_TOKEN_SCOPES)},
        )

    raw, prefix, digest = generate_api_token()
    now = utcnow()
    token = ApiToken(
        project_id=project_id,
        name=payload.name,
        token_prefix=prefix,
        token_hash=digest,
        scopes=payload.scopes,
        created_at=now,
    )
    db.add(token)
    db.flush()
    record_audit(
        db,
        project_id,
        member.user_id,
        "api_token",
        str(token.id),
        "create",
        after={"name": token.name, "prefix": prefix, "scopes": token.scopes},
    )
    db.commit()
    db.refresh(token)
    return TokenCreatedOut(**_token_out(token, now).model_dump(), token=raw)


@router.delete("/{token_id}", status_code=204)
def revoke_token(
    project_id: UUID,
    token_id: UUID,
    member: ProjectMember = Depends(ADMIN_ONLY),
    db: Session = Depends(get_db),
) -> None:
    token = db.scalar(
        select(ApiToken).where(
            ApiToken.id == token_id, ApiToken.project_id == project_id
        )
    )
    if token is None:
        raise ApiError(404, "token_not_found", "令牌不存在")
    if token.revoked_at is not None:
        return

    token.revoked_at = utcnow()
    record_audit(
        db,
        project_id,
        member.user_id,
        "api_token",
        str(token.id),
        "revoke",
        before={"name": token.name, "prefix": token.token_prefix},
    )
    db.commit()
