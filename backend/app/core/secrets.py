from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.errors import ApiError


def _fernet() -> Fernet:
    raw = get_settings().secrets_key.strip()
    if raw:
        key = raw.encode()
    else:
        # 本地开发兜底：从 JWT_SECRET 派生；生产环境应显式配置 SECRETS_KEY。
        key = base64.urlsafe_b64encode(
            hashlib.sha256(get_settings().jwt_secret.encode("utf-8")).digest()
        )
    try:
        return Fernet(key)
    except ValueError as exc:
        raise RuntimeError(
            "SECRETS_KEY 必须是 Fernet key；可用 "
            "python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\" 生成"
        ) from exc


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ApiError(
            500,
            "secret_decrypt_failed",
            "测试凭据解密失败，请检查 SECRETS_KEY 是否变更",
        ) from exc
