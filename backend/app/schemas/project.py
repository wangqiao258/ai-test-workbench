import re
from datetime import datetime
from uuid import UUID

from pydantic import field_validator

from app.schemas.common import ApiModel

_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


class ProjectCreateIn(ApiModel):
    key: str
    name: str
    repo: str = ""
    environment: str = ""
    owner: str = ""

    @field_validator("key")
    @classmethod
    def _validate_key(cls, value: str) -> str:
        value = value.strip().lower()
        if not _KEY_PATTERN.fullmatch(value):
            raise ValueError("项目 KEY 需为 2-64 位小写字母、数字或连字符，且以字母或数字开头")
        return value

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("项目名称不能为空")
        if len(value) > 120:
            raise ValueError("项目名称不能超过 120 个字符")
        return value

    @field_validator("repo", "environment", "owner")
    @classmethod
    def _strip_optional(cls, value: str) -> str:
        return value.strip()


class ProjectOut(ApiModel):
    id: UUID
    key: str
    name: str
    repo: str
    environment: str
    owner: str
    updated_at: datetime
    role: str


class ProjectUpdateIn(ApiModel):
    """项目资料局部更新。项目 KEY 创建后不可修改。"""

    name: str | None = None
    repo: str | None = None
    environment: str | None = None
    owner: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("项目名称不能为空")
        if len(value) > 120:
            raise ValueError("项目名称不能超过 120 个字符")
        return value

    @field_validator("repo", "environment", "owner")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None
