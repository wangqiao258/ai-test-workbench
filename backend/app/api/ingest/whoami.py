"""AI 机发现项目、目标地址与动作清单。"""

from typing import Any

from fastapi import APIRouter, Depends

from app.core.agent_actions import ACTIONS, SCOPE_ANY, WORKFLOW_STEPS
from app.core.deps import TokenContext, get_token_context

router = APIRouter(tags=["ingest"])

RULES: tuple[str, ...] = (
    "被测请求 URL = project.baseUrl + operation.path；为空先填项目设置，actions.path 用平台地址",
    "动作需要参数或请求体时先读 action.detail，不要猜",
    "按 actions 顺序执行；需求与接口关联由测试请求自动建立",
    "已测接口优先复用，未覆盖的再按 tag / q 检索",
    "摘要只用于选接口，生成用例前必须读 /operations/{id} 详情",
    "Tavern marks 写 workbench:requirement:<需求ID>",
    "运行串行：上一次运行结束后再触发下一次；AI 只上传规格并触发运行，不执行 pytest",
)


@router.get("/whoami")
def whoami(context: TokenContext = Depends(get_token_context)) -> dict[str, Any]:
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
        "docs": {
            "swagger": "/ingest/docs",
            "openapi": "/ingest/openapi.json",
        },
    }
