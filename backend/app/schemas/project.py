from datetime import datetime
from uuid import UUID

from pydantic import field_validator

from app.schemas.common import ApiModel


def _normalize_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("项目名称不能为空")
    if len(value) > 120:
        raise ValueError("项目名称不能超过 120 个字符")
    return value


def _normalize_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        return ""
    if len(value) > 255:
        raise ValueError("被测服务地址不能超过 255 个字符")
    if not value.startswith(("http://", "https://")):
        raise ValueError("被测服务地址需以 http:// 或 https:// 开头")
    return value


class ProjectCreateIn(ApiModel):
    name: str
    base_url: str = ""

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _normalize_name(value)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        return _normalize_base_url(value)


class ProjectOut(ApiModel):
    id: UUID
    name: str
    base_url: str
    updated_at: datetime
    role: str


class ProjectUpdateIn(ApiModel):
    """项目资料局部更新。"""

    name: str | None = None
    base_url: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_name(value)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_base_url(value)
