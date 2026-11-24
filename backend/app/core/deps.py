from datetime import datetime, timezone
from uuid import UUID

import jwt
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import decode_access_token, hash_api_token
from app.db.models.identity import AppUser, ProjectMember
from app.db.models.project import ApiToken, Project
from app.db.session import get_db

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AppUser:
    if credentials is None:
        raise ApiError(401, "unauthorized", "缺少登录凭证")
    try:
        user_id = decode_access_token(credentials.credentials)
    except (jwt.PyJWTError, ValueError):
        raise ApiError(401, "invalid_token", "登录已过期，请重新登录") from None
    user = db.get(AppUser, user_id)
    if user is None or user.status != "active":
        raise ApiError(401, "invalid_token", "登录已失效，请重新登录")
    return user


def get_membership(
    project_id: UUID,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectMember:
    member = db.get(ProjectMember, (project_id, user.id))
    if member is None:
        raise ApiError(404, "project_not_found", "项目不存在或无权访问")
    return member


def get_project_by_token(
    x_project_token: str | None = Header(default=None, alias="X-Project-Token"),
    db: Session = Depends(get_db),
) -> Project:
    if not x_project_token:
        raise ApiError(401, "missing_project_token", "缺少 X-Project-Token")
    token = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_api_token(x_project_token)))
    now = datetime.now(timezone.utc)
    if token is None or token.revoked_at is not None:
        raise ApiError(401, "invalid_project_token", "项目 Token 无效")
    if token.expires_at is not None and token.expires_at <= now:
        raise ApiError(401, "invalid_project_token", "项目 Token 已过期")
    project = db.get(Project, token.project_id)
    if project is None:
        raise ApiError(401, "invalid_project_token", "项目 Token 对应的项目不存在")
    token.last_used_at = now
    db.commit()
    return project
