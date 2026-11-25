"""AI 机 / 执行器专用接口文档：只暴露 /ingest/v1/*，避免与后台 JWT 接口混在一起。"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["ingest-docs"])


@router.get("/ingest/openapi.json", include_in_schema=False)
def ingest_openapi(request: Request) -> dict[str, Any]:
    spec = request.app.openapi()
    paths = {
        path: item
        for path, item in spec.get("paths", {}).items()
        if path.startswith("/ingest/")
    }
    return {
        "openapi": spec.get("openapi", "3.1.0"),
        "info": {
            "title": "AI 协同测试工作台 · Ingest API",
            "version": spec.get("info", {}).get("version", "0.1.0"),
            "description": (
                "AI 机与 pytest 执行器使用的项目 Token 接口。"
                "所有请求需带 X-Project-Token 请求头，写接口需要 Idempotency-Key；"
                "权限按 scope 划分，写权限自动包含对应读权限；"
                "先调用 GET /ingest/v1/whoami 获取当前 Token 的 scopes 与 actions。"
            ),
        },
        "paths": paths,
        "components": spec.get("components", {}),
        "tags": [{"name": "ingest", "description": "项目 Token 读写通道"}],
    }


@router.get("/ingest/docs", include_in_schema=False)
def ingest_docs() -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url="/ingest/openapi.json",
        title="AI Ingest API · AI 协同测试工作台",
        swagger_ui_parameters={"docExpansion": "list", "defaultModelsExpandDepth": -1},
    )
