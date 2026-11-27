from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.common import ApiModel

MAX_PROJECT_ENTRIES = 20


def _normalize_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("项目名称不能为空")
    if len(value) > 120:
        raise ValueError("项目名称不能超过 120 个字符")
    return value


def _normalize_entry_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("入口名称不能为空")
    if len(value) > 120:
        raise ValueError("入口名称不能超过 120 个字符")
    return value


def _normalize_entry_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        raise ValueError("入口地址不能为空")
    if len(value) > 512:
        raise ValueError("入口地址不能超过 512 个字符")
    if not value.startswith(("http://", "https://")):
        raise ValueError("入口地址需以 http:// 或 https:// 开头")
    return value


def _normalize_entry_note(value: str) -> str:
    value = value.strip()
    if len(value) > 255:
        raise ValueError("入口备注不能超过 255 个字符")
    return value


class ProjectEntry(ApiModel):
    name: str
    url: str
    note: str = ""

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _normalize_entry_name(value)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        return _normalize_entry_url(value)

    @field_validator("note")
    @classmethod
    def _validate_note(cls, value: str) -> str:
        return _normalize_entry_note(value)


def _ensure_unique_entry_urls(entries: list[ProjectEntry]) -> list[ProjectEntry]:
    seen: set[str] = set()
    for entry in entries:
        if entry.url in seen:
            raise ValueError(f"入口地址重复：{entry.url}")
        seen.add(entry.url)
    return entries


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
    entries: list[ProjectEntry] = Field(
        default_factory=list, max_length=MAX_PROJECT_ENTRIES
    )

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _normalize_name(value)

    @field_validator("entries")
    @classmethod
    def _validate_entries(cls, values: list[ProjectEntry]) -> list[ProjectEntry]:
        return _ensure_unique_entry_urls(values)


class ProjectOut(ApiModel):
    id: UUID
    name: str
    entries: list[ProjectEntry]
    test_repo_url: str
    test_repo_ref: str
    updated_at: datetime
    role: str


class ProjectUpdateIn(ApiModel):
    """项目资料局部更新。"""

    name: str | None = None
    entries: list[ProjectEntry] | None = Field(
        default=None, max_length=MAX_PROJECT_ENTRIES
    )
    test_repo_url: str | None = None
    test_repo_ref: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_name(value)

    @field_validator("entries")
    @classmethod
    def _validate_entries(
        cls, values: list[ProjectEntry] | None
    ) -> list[ProjectEntry] | None:
        return None if values is None else _ensure_unique_entry_urls(values)

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
