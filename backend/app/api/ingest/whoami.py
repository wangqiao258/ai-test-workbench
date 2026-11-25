"""供 AI 机 / pytest 插件发现当前 Token 的能力边界。"""

from typing import Any

from fastapi import APIRouter, Depends

from app.core.deps import SCOPE_LEGACY, TokenContext, get_token_context

router = APIRouter(tags=["ingest"])

CAPABILITIES: tuple[dict[str, str], ...] = (
    {
        "method": "GET",
        "path": "/ingest/v1/assets/requirements",
        "scope": "assets:read",
        "description": "读取需求文档列表（含关联接口与用例 nodeid）",
    },
    {
        "method": "GET",
        "path": "/ingest/v1/assets/openapi",
        "scope": "assets:read",
        "description": "读取 OpenAPI 契约与全部接口明细",
    },
    {
        "method": "GET",
        "path": "/ingest/v1/assets/runs",
        "scope": "runs:read",
        "description": "读取最近运行批次及统计",
    },
    {
        "method": "POST",
        "path": "/ingest/v1/requirements",
        "scope": "assets:write",
        "description": "批量写入需求，需 Idempotency-Key 请求头",
    },
    {
        "method": "POST",
        "path": "/ingest/v1/openapi",
        "scope": "assets:write",
        "description": "批量写入结构化接口契约，需 Idempotency-Key 请求头",
    },
    {
        "method": "POST",
        "path": "/ingest/v1/catalog",
        "scope": "assets:write",
        "description": "写入 pytest 用例目录",
    },
    {
        "method": "POST",
        "path": "/ingest/v1/runs",
        "scope": "runs:write",
        "description": "上传运行结果、日志与抓包，需 Idempotency-Key 请求头",
    },
    {
        "method": "POST",
        "path": "/ingest/v1/runs/{run_id}/artifacts",
        "scope": "runs:write",
        "description": "上传 HAR / 截图等证据文件",
    },
    {
        "method": "POST",
        "path": "/ingest/v1/runs/{run_id}/analysis",
        "scope": "analysis:write",
        "description": "写入 AI 分析结果与 finding，需 Idempotency-Key 请求头",
    },
    {
        "method": "POST",
        "path": "/ingest/v1/specs",
        "scope": "specs:write",
        "description": "上传 pytest / Tavern YAML 规格，平台 runner 执行",
    },
    {
        "method": "GET",
        "path": "/ingest/v1/jobs/{job_id}",
        "scope": "any",
        "description": "查询异步入库任务状态",
    },
)


@router.get("/whoami")
def whoami(context: TokenContext = Depends(get_token_context)) -> dict[str, Any]:
    """返回当前 Token 所属项目、granted scopes 与可用能力清单。"""
    scopes = sorted(context.scopes)
    granted_all = SCOPE_LEGACY in context.scopes
    capabilities = [
        item
        for item in CAPABILITIES
        if granted_all or item["scope"] == "any" or item["scope"] in context.scopes
    ]
    return {
        "project": {
            "id": str(context.project.id),
            "key": context.project.key,
            "name": context.project.name,
        },
        "token": {"scopes": scopes},
        "capabilities": capabilities,
        "docs": {
            "swagger": "/ingest/docs",
            "openapi": "/ingest/openapi.json",
        },
    }
