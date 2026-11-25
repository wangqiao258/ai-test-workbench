"""动作详情：从平台 OpenAPI 自动生成，不手写接口说明。"""

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.agent_actions import ACTIONS, SCOPE_ANY
from app.core.deps import TokenContext, get_token_context
from app.core.errors import ApiError

router = APIRouter(prefix="/actions", tags=["ingest"])


def _resolve(node: Any, components: dict, seen: frozenset[str] = frozenset()) -> Any:
    if isinstance(node, list):
        return [_resolve(item, components, seen) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/"):
        if ref in seen:
            return {"$ref": ref}
        target: Any = components
        for part in ref.removeprefix("#/components/").split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            target = target.get(key, {}) if isinstance(target, dict) else {}
        return _resolve(target, components, seen | {ref})
    return {key: _resolve(value, components, seen) for key, value in node.items()}


def _request_example(operation: dict) -> Any:
    content = (operation.get("requestBody") or {}).get("content") or {}
    for media in content.values():
        if "example" in media:
            return media["example"]
        schema = media.get("schema") or {}
        examples = schema.get("examples")
        if isinstance(examples, list) and examples:
            return examples[0]
        if "example" in schema:
            return schema["example"]
    return None


@router.get("/{step}")
def action_detail(
    step: str,
    request: Request,
    context: TokenContext = Depends(get_token_context),
) -> dict[str, Any]:
    action = next((item for item in ACTIONS if item["step"] == step), None)
    if action is None:
        raise ApiError(404, "action_not_found", "动作不存在")
    if action["scope"] != SCOPE_ANY and action["scope"] not in context.scopes:
        raise ApiError(403, "insufficient_scope", "项目 Token 缺少该动作权限")

    spec = request.app.openapi()
    operation = (
        spec.get("paths", {})
        .get(action["path"], {})
        .get(action["method"].lower())
    )
    if operation is None:
        raise ApiError(404, "action_not_documented", "动作缺少 OpenAPI 定义")

    resolved = _resolve(operation, spec.get("components", {}))
    return {
        "step": action["step"],
        "method": action["method"],
        "path": action["path"],
        "scope": action["scope"],
        "description": action["description"],
        "query": action.get("query"),
        "requestExample": _request_example(resolved),
        "operation": resolved,
    }
