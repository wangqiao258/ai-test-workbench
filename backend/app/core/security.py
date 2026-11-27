import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from app.core.config import get_settings
from app.core.time import utcnow

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False


def create_access_token(user_id: UUID) -> str:
    settings = get_settings()
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> UUID:
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    return UUID(payload["sub"])


AI_TICKET_AUDIENCE = "workbench-ai-ticket"
AI_TICKET_TYPE = "ai-ticket"


def _ai_ticket_key() -> bytes:
    """从 JWT 密钥派生独立密钥，避免票据与用户登录令牌互相冒用。"""
    settings = get_settings()
    return hmac.new(
        settings.jwt_secret.encode("utf-8"), b"ai-read-ticket", hashlib.sha256
    ).digest()


def create_ai_ticket(
    *,
    project_id: UUID,
    resource: str,
    run_ref: str | None,
    nodeid: str | None,
    ttl_minutes: int,
) -> tuple[str, datetime]:
    now = utcnow()
    expires_at = now + timedelta(minutes=ttl_minutes)
    payload = {
        "aud": AI_TICKET_AUDIENCE,
        "typ": AI_TICKET_TYPE,
        "pid": str(project_id),
        "res": resource,
        "run": run_ref,
        "node": nodeid,
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(payload, _ai_ticket_key(), algorithm="HS256")
    return token, expires_at


def decode_ai_ticket(ticket: str) -> dict:
    payload = jwt.decode(
        ticket,
        _ai_ticket_key(),
        algorithms=["HS256"],
        audience=AI_TICKET_AUDIENCE,
    )
    if payload.get("typ") != AI_TICKET_TYPE:
        raise jwt.InvalidTokenError("invalid ai ticket type")
    return payload


def generate_api_token() -> tuple[str, str, str]:
    """返回 (明文 token, 展示用前缀, sha256 摘要)，明文另加密存库供设置页回看。"""
    raw = "atw_" + secrets.token_urlsafe(32)
    return raw, raw[:12], hash_api_token(raw)


def hash_api_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
