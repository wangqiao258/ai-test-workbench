import re
from datetime import datetime

from pydantic import Field, field_validator

from app.schemas.common import ApiModel

SECRET_KEY_PATTERN = r"^[A-Z][A-Z0-9_]{0,63}$"


def normalize_secret_key(value: str) -> str:
    key = value.strip().upper()
    if not key:
        raise ValueError("凭据名称不能为空")
    if re.fullmatch(SECRET_KEY_PATTERN, key) is None:
        raise ValueError("凭据名称只能包含大写字母、数字和下划线，且以字母开头")
    return key


class SecretUpsertIn(ApiModel):
    value: str = Field(min_length=1, max_length=4096)
    description: str = Field(default="", max_length=255)
    expires_at: datetime | None = None

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return value.strip()


class SecretOut(ApiModel):
    key: str
    description: str
    expires_at: datetime | None
    last_used_at: datetime | None
    updated_at: datetime
    expired: bool = False
    value: str | None = None


class SecretResolveIn(ApiModel):
    keys: list[str] = Field(min_length=1, max_length=50)

    @field_validator("keys")
    @classmethod
    def _validate_keys(cls, values: list[str]) -> list[str]:
        normalized = [normalize_secret_key(item) for item in values]
        return list(dict.fromkeys(normalized))


class SecretResolveOut(ApiModel):
    values: dict[str, str]
    missing: list[str] = Field(default_factory=list)
