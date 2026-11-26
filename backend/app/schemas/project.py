from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

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


def _normalize_repo_url(value: str) -> str:
    value = value.strip()
    if len(value) > 512:
        raise ValueError("测试仓库地址不能超过 512 个字符")
    return value


def _normalize_repo_ref(value: str) -> str:
    value = value.strip()
    if len(value) > 128:
        raise ValueError("测试仓库分支不能超过 128 个字符")
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
    test_repo_url: str
    test_repo_ref: str
    updated_at: datetime
    role: str


class ProjectUpdateIn(ApiModel):
    """项目资料局部更新。"""

    name: str | None = None
    base_url: str | None = None
    test_repo_url: str | None = None
    test_repo_ref: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_name(value)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_base_url(value)

    @field_validator("test_repo_url")
    @classmethod
    def _validate_repo_url(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_repo_url(value)

    @field_validator("test_repo_ref")
    @classmethod
    def _validate_repo_ref(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_repo_ref(value)


class AgentRulesIn(ApiModel):
    rules: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("rules")
    @classmethod
    def _normalize_rules(cls, values: list[str]) -> list[str]:
        rules: list[str] = []
        for value in values:
            text = value.strip()
            if not text:
                continue
            if len(text) > 500:
                raise ValueError("单条规则不能超过 500 个字符")
            rules.append(text)
        return rules


class AgentRulesOut(ApiModel):
    rules: list[str]
    defaults: list[str]
    is_custom: bool
