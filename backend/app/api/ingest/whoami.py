"""AI 机发现项目、目标地址与动作清单。"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.agent_actions import ACTIONS, SCOPE_ANY, WORKFLOW_STEPS
from app.core.deps import SCOPE_SECRETS_READ, TokenContext, get_token_context
from app.core.frameworks import AD_HOC_FRAMEWORK, CATALOG_FRAMEWORKS
from app.core.time import utcnow
from app.db.models.project import ProjectSecret
from app.db.session import get_db

router = APIRouter(tags=["ingest"])

RULES: tuple[str, ...] = (
    "被测请求 URL = project.baseUrl + operation.path；为空先填项目设置，actions.path 用平台地址",
    "动作需要参数或请求体时先读 action.detail，不要猜",
    "按 actions 顺序执行；需求与接口关联由测试请求自动建立",
    "已测接口优先复用，未覆盖的再按 tag / q 检索",
    "摘要只用于选接口，生成用例前必须读 /operations/{id} 详情",
    "Tavern marks 写 workbench:requirement:<需求ID>",
    "用例正文在 Git：catalog 只写索引，需带 source(repo/ref/commit) 与 framework；"
    f"framework 只收 {'、'.join(CATALOG_FRAMEWORKS)}",
    f"临时脚本上报时 framework={AD_HOC_FRAMEWORK}，只留运行与证据，不进入用例库",
    "AI 在本机或外部环境执行 pytest，执行后通过 /ingest/v1/runs 上传运行结果与证据",
    "证据优先上传原始 HAR（浏览器、Playwright、代理工具导出的均可）；"
    "无法抓包时随 run 内联 cases[].exchanges",
    "HAR 需在运行上传后按 nodeid 上传，解析结果会替换该用例已有交换记录",
    "测试凭据只引用名称：pytest 用 os.environ['KEY']，"
    "Tavern 用 {tavern.env_vars.KEY}，值由插件注入，不要写死",
)


@router.get("/whoami")
def whoami(
    context: TokenContext = Depends(get_token_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scopes = sorted(context.scopes)
    permitted = [
        action
        for action in ACTIONS
        if action["scope"] == SCOPE_ANY or action["scope"] in context.scopes
    ]
    by_step = {action["step"]: action for action in permitted}
    workflow = [by_step[step] for step in WORKFLOW_STEPS if step in by_step]
    ordered = workflow + [
        action for action in permitted if action["step"] not in WORKFLOW_STEPS
    ]
    actions = [
        {**action, "detail": f"/ingest/v1/actions/{action['step']}"}
        for action in ordered
    ]
    secrets: list[dict[str, Any]] = []
    if SCOPE_SECRETS_READ in context.scopes:
        now = utcnow()
        items = db.scalars(
            select(ProjectSecret)
            .where(ProjectSecret.project_id == context.project.id)
            .order_by(ProjectSecret.key)
        ).all()
        secrets = [
            {
                "key": item.key,
                "description": item.description,
                "expiresAt": item.expires_at.isoformat() if item.expires_at else None,
                "expired": item.expires_at is not None and item.expires_at <= now,
            }
            for item in items
        ]
    return {
        "project": {
            "id": str(context.project.id),
            "name": context.project.name,
            "baseUrl": context.project.base_url or None,
        },
        "token": {"scopes": scopes},
        "start": workflow[0]["step"] if workflow else None,
        "actions": actions,
        "rules": list(RULES),
        "secrets": secrets,
        "docs": {
            "swagger": "/ingest/docs",
            "openapi": "/ingest/openapi.json",
        },
    }
