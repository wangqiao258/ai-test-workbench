import pytest
from pydantic import ValidationError

from app.core.secrets import decrypt_secret, encrypt_secret
from app.schemas.secret import SecretResolveIn, normalize_secret_key


def test_secret_encrypt_roundtrip() -> None:
    token = encrypt_secret("sut-token-123")
    assert token != "sut-token-123"
    assert decrypt_secret(token) == "sut-token-123"


def test_normalize_secret_key() -> None:
    assert normalize_secret_key(" sut_token ") == "SUT_TOKEN"
    for value in ("1TOKEN", "SUT-TOKEN", "SUT TOKEN", ""):
        with pytest.raises(ValueError):
            normalize_secret_key(value)


def test_resolve_keys_are_normalized_and_deduplicated() -> None:
    payload = SecretResolveIn(keys=["sut_token", "SUT_TOKEN", "SUT_PASSWORD"])
    assert payload.keys == ["SUT_TOKEN", "SUT_PASSWORD"]


def test_resolve_rejects_empty_keys() -> None:
    with pytest.raises(ValidationError):
        SecretResolveIn(keys=[])
