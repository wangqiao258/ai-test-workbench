from uuid import uuid4

import jwt
import pytest

from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_api_token,
    hash_api_token,
    hash_password,
    verify_password,
)


def test_password_roundtrip() -> None:
    hashed = hash_password("secret-123")
    assert verify_password("secret-123", hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_jwt_roundtrip() -> None:
    user_id = uuid4()
    token = create_access_token(user_id)
    assert decode_access_token(token) == user_id


def test_jwt_rejects_tampered_token() -> None:
    token = create_access_token(uuid4())
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(token + "x")


def test_api_token_hash_is_stable() -> None:
    raw, prefix, digest = generate_api_token()
    assert raw.startswith("atw_")
    assert prefix == raw[:12]
    assert digest == hash_api_token(raw)
