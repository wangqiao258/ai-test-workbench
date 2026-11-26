from datetime import datetime
from uuid import UUID

from pydantic import field_validator

from app.schemas.common import ApiModel


class TokenCreateIn(ApiModel):
    name: str
    scopes: list[str]

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("令牌名称不能为空")
        if len(value) > 120:
            raise ValueError("令牌名称不能超过 120 个字符")
        return value

    @field_validator("scopes")
    @classmethod
    def _validate_scopes(cls, value: list[str]) -> list[str]:
        scopes = list(dict.fromkeys(scope.strip() for scope in value if scope.strip()))
        if not scopes:
            raise ValueError("至少选择一项权限")
        return scopes


class TokenOut(ApiModel):
    id: UUID
    name: str
    prefix: str
    scopes: list[str]
    status: str
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    token: str | None = None


class TokenCreatedOut(TokenOut):
    """创建响应额外返回明文 Token 与创建时一致，之后可在列表查看。"""

    token: str


class TokenPurgeOut(ApiModel):
    deleted: int
