from uuid import uuid4

import jwt
import pytest

from app.core.deps import (
    ISSUABLE_TOKEN_SCOPES,
    SCOPE_ANALYSIS_WRITE,
    SCOPE_ASSETS_READ,
    SCOPE_ASSETS_WRITE,
    SCOPE_LEGACY,
    SCOPE_RUNS_EXECUTE,
    SCOPE_RUNS_READ,
    SCOPE_RUNS_WRITE,
    TOKEN_PRESETS,
    expand_token_scopes,
)
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


def test_write_scope_implies_corresponding_read() -> None:
    assert expand_token_scopes({SCOPE_ASSETS_WRITE}) == frozenset(
        {SCOPE_ASSETS_WRITE, SCOPE_ASSETS_READ}
    )
    assert expand_token_scopes({SCOPE_RUNS_WRITE}) == frozenset(
        {SCOPE_RUNS_WRITE, SCOPE_RUNS_READ}
    )
    assert expand_token_scopes({SCOPE_RUNS_EXECUTE}) == frozenset(
        {SCOPE_RUNS_EXECUTE, SCOPE_RUNS_READ}
    )
    assert expand_token_scopes({SCOPE_ANALYSIS_WRITE}) == frozenset(
        {SCOPE_ANALYSIS_WRITE, SCOPE_RUNS_READ}
    )


def test_read_scope_does_not_imply_write() -> None:
    assert expand_token_scopes({SCOPE_ASSETS_READ}) == frozenset({SCOPE_ASSETS_READ})
    assert expand_token_scopes({SCOPE_RUNS_READ}) == frozenset({SCOPE_RUNS_READ})
    assert SCOPE_RUNS_WRITE not in expand_token_scopes({SCOPE_RUNS_EXECUTE})


def test_legacy_scope_expands_to_all_issuable_scopes() -> None:
    scopes = expand_token_scopes({SCOPE_LEGACY})
    assert SCOPE_ASSETS_READ in scopes
    assert SCOPE_ANALYSIS_WRITE in scopes
    assert SCOPE_LEGACY not in scopes


def test_token_presets_use_issuable_scopes() -> None:
    allowed = set(ISSUABLE_TOKEN_SCOPES)
    assert TOKEN_PRESETS
    for preset in TOKEN_PRESETS:
        assert set(preset["scopes"]) <= allowed
