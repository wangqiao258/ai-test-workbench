from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import decode_access_token, hash_api_token
from app.core.time import utcnow
from app.db.models.identity import AppUser, ProjectMember
from app.db.models.project import ApiToken, Project
from app.db.session import get_db

_bearer = HTTPBearer(auto_error=False)
_project_token = APIKeyHeader(
    name="X-Project-Token",
    scheme_name="ProjectToken",
    description="项目级 Token，权限由 scope 决定；可用 GET /ingest/v1/whoami 查询当前能力",
    auto_error=False,
)

SCOPE_LEGACY = "ingest"
SCOPE_ASSETS_READ = "assets:read"
SCOPE_ASSETS_WRITE = "assets:write"
SCOPE_RUNS_READ = "runs:read"
SCOPE_RUNS_WRITE = "runs:write"
SCOPE_ANALYSIS_WRITE = "analysis:write"
SCOPE_SPECS_WRITE = "specs:write"
SCOPE_SECRETS_READ = "secrets:read"

KNOWN_TOKEN_SCOPES = (
    SCOPE_LEGACY,
    SCOPE_ASSETS_READ,
    SCOPE_ASSETS_WRITE,
    SCOPE_RUNS_READ,
    SCOPE_RUNS_WRITE,
    SCOPE_ANALYSIS_WRITE,
    SCOPE_SPECS_WRITE,
    SCOPE_SECRETS_READ,
)

# 新建令牌只发放细分 scope；历史 ingest 仅用于兼容既有 Token。
ISSUABLE_TOKEN_SCOPES = tuple(
    scope for scope in KNOWN_TOKEN_SCOPES if scope != SCOPE_LEGACY
)

# 写/执行权限隐含对应读权限，避免出现“能写但无法回查”的令牌。
SCOPE_IMPLICATIONS: dict[str, frozenset[str]] = {
    SCOPE_ASSETS_WRITE: frozenset({SCOPE_ASSETS_READ}),
    SCOPE_RUNS_WRITE: frozenset({SCOPE_RUNS_READ}),
    SCOPE_ANALYSIS_WRITE: frozenset({SCOPE_RUNS_READ}),
}

SCOPE_CATALOG: tuple[dict[str, str], ...] = (
    {"id": SCOPE_ASSETS_READ, "label": "读资产", "description": "读取需求与 OpenAPI"},
    {
        "id": SCOPE_ASSETS_WRITE,
        "label": "资产读写",
        "description": "写入需求、契约、用例目录，含读取",
    },
    {"id": SCOPE_RUNS_READ, "label": "读运行", "description": "读取运行批次与任务"},
    {
        "id": SCOPE_RUNS_WRITE,
        "label": "运行读写",
        "description": "上传运行结果与证据，含读取",
    },
    {
        "id": SCOPE_ANALYSIS_WRITE,
        "label": "分析回写",
        "description": "写入分析结果，含读取运行",
    },
    {"id": SCOPE_SPECS_WRITE, "label": "传规格", "description": "上传 YAML 规格"},
    {
        "id": SCOPE_SECRETS_READ,
        "label": "读测试凭据",
        "description": "读取项目测试账号与 Token",
    },
    {"id": SCOPE_LEGACY, "label": "历史全量", "description": "兼容旧令牌"},
)

TOKEN_PRESETS: tuple[dict, ...] = (
    {
        "id": "read",
        "label": "只读发现",
        "hint": "读需求、契约与运行",
        "scopes": [SCOPE_ASSETS_READ, SCOPE_RUNS_READ],
    },
    {
        "id": "assets",
        "label": "资产入库",
        "hint": "写资产与规格",
        "scopes": [SCOPE_ASSETS_WRITE, SCOPE_SPECS_WRITE],
    },
    {
        "id": "run",
        "label": "运行分析",
        "hint": "上传运行与分析",
        "scopes": [SCOPE_RUNS_WRITE, SCOPE_ANALYSIS_WRITE],
    },
    {
        "id": "auto",
        "label": "全自动测试",
        "hint": "读资产、传规格、读凭据、写分析",
        "scopes": [
            SCOPE_ASSETS_READ,
            SCOPE_SPECS_WRITE,
            SCOPE_SECRETS_READ,
            SCOPE_ANALYSIS_WRITE,
        ],
    },
    {
        "id": "all",
        "label": "全量接入",
        "hint": "全部权限",
        "scopes": list(ISSUABLE_TOKEN_SCOPES),
    },
)


def expand_token_scopes(scopes: Iterable[str]) -> frozenset[str]:
    """把存储的 scope 展开为实际生效的权限。"""
    granted = set(scopes)
    if SCOPE_LEGACY in granted:
        return frozenset(ISSUABLE_TOKEN_SCOPES)
    for scope, implied in SCOPE_IMPLICATIONS.items():
        if scope in granted:
            granted.update(implied)
    return frozenset(granted)


@dataclass(frozen=True)
class TokenContext:
    project: Project
    # 展开后的生效权限；写/执行权限会带上对应读权限。
    scopes: frozenset[str]
    token_id: UUID


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AppUser:
    if credentials is None:
        raise ApiError(401, "unauthorized", "缺少登录凭证")
    try:
        user_id = decode_access_token(credentials.credentials)
    except (jwt.PyJWTError, ValueError):
        raise ApiError(401, "invalid_token", "登录已过期，请重新登录") from None
    user = db.get(AppUser, user_id)
    if user is None or user.status != "active":
        raise ApiError(401, "invalid_token", "登录已失效，请重新登录")
    return user


def get_membership(
    request: Request,
    project_id: UUID,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectMember:
    member = db.get(ProjectMember, (project_id, user.id))
    if member is None:
        raise ApiError(404, "project_not_found", "项目不存在或无权访问")
    request.state.project_id = str(project_id)
    return member


def require_role(*roles: str, message: str = "当前角色无权执行该操作"):
    """要求当前用户在项目中的角色属于指定集合。"""

    def dependency(member: ProjectMember = Depends(get_membership)) -> ProjectMember:
        if member.role not in roles:
            raise ApiError(403, "forbidden", message)
        return member

    return dependency


def get_token_context(
    request: Request,
    x_project_token: str | None = Depends(_project_token),
    db: Session = Depends(get_db),
) -> TokenContext:
    if not x_project_token:
        raise ApiError(401, "missing_project_token", "缺少 X-Project-Token")
    token = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_api_token(x_project_token)))
    now = utcnow()
    if token is None or token.revoked_at is not None:
        raise ApiError(401, "invalid_project_token", "项目 Token 无效")
    if token.expires_at is not None and token.expires_at <= now:
        raise ApiError(401, "invalid_project_token", "项目 Token 已过期")
    project = db.get(Project, token.project_id)
    if project is None:
        raise ApiError(401, "invalid_project_token", "项目 Token 对应的项目不存在")
    token.last_used_at = now
    db.commit()
    request.state.project_id = str(project.id)
    return TokenContext(
        project=project,
        scopes=expand_token_scopes(token.scopes or []),
        token_id=token.id,
    )


def get_project_by_token(context: TokenContext = Depends(get_token_context)) -> Project:
    return context.project


def require_token_scope(*required: str):
    """要求 Token 具备任一指定 scope；写权限已展开为对应的读权限。"""

    def dependency(context: TokenContext = Depends(get_token_context)) -> Project:
        scopes = context.scopes
        if scopes.intersection(required):
            return context.project
        raise ApiError(
            403,
            "insufficient_scope",
            "项目 Token 缺少所需权限",
            details={"required": sorted(required), "granted": sorted(scopes)},
        )

    return dependency
