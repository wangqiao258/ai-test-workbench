"""AI 接入动作清单：唯一来源，whoami 与 action 详情共用。"""

from typing import Any

from app.core.defaults import OPERATIONS_PAGE_SIZE, REQUIREMENT_QUEUE_LIMIT
from app.core.deps import (
    SCOPE_ANALYSIS_WRITE,
    SCOPE_ASSETS_READ,
    SCOPE_ASSETS_WRITE,
    SCOPE_CATALOG_WRITE,
    SCOPE_RUNS_READ,
    SCOPE_RUNS_WRITE,
    SCOPE_SPECS_WRITE,
)

SCOPE_ANY = "any"

WORKFLOW_STEPS = (
    "next_requirements",
    "requirement_detail",
    "requirement_associations",
    "find_operations",
    "operation_detail",
    "upload_specs",
    "upload_run",
    "read_run_stats",
    "write_analysis",
)

ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "step": "next_requirements",
        "method": "GET",
        "path": "/ingest/v1/requirements/next",
        "query": {"limit": REQUIREMENT_QUEUE_LIMIT},
        "scope": SCOPE_ASSETS_READ,
        "description": "领取排序后的需求队列，不要全量读取",
    },
    {
        "step": "requirement_detail",
        "method": "GET",
        "path": "/ingest/v1/requirements/{requirement_id}",
        "scope": SCOPE_ASSETS_READ,
        "description": "读取需求正文、已测接口与用例",
    },
    {
        "step": "requirement_associations",
        "method": "GET",
        "path": "/ingest/v1/requirements/{requirement_id}/associations",
        "scope": SCOPE_ASSETS_READ,
        "description": "查看已测接口、用例数和置信度，优先复用",
    },
    {
        "step": "find_operations",
        "method": "GET",
        "path": "/ingest/v1/operations",
        "query": {"limit": OPERATIONS_PAGE_SIZE},
        "scope": SCOPE_ASSETS_READ,
        "description": "按 tag / 关键词检索接口摘要",
    },
    {
        "step": "operation_detail",
        "method": "GET",
        "path": "/ingest/v1/operations/{operation_id}",
        "scope": SCOPE_ASSETS_READ,
        "description": "生成用例前读取完整契约",
    },
    {
        "step": "upload_specs",
        "method": "POST",
        "path": "/ingest/v1/specs",
        "scope": SCOPE_SPECS_WRITE,
        "description": "上传 Tavern / pytest YAML，path 相对项目 specs 目录",
    },
    {
        "step": "read_run_stats",
        "method": "GET",
        "path": "/ingest/v1/assets/runs",
        "query": {"limit": 20},
        "scope": SCOPE_RUNS_READ,
        "description": "读取最近运行与统计",
    },
    {
        "step": "write_analysis",
        "method": "POST",
        "path": "/ingest/v1/runs/{run_id}/analysis",
        "scope": SCOPE_ANALYSIS_WRITE,
        "description": "回写分析结果，需 Idempotency-Key",
    },
    {
        "step": "list_pending_findings",
        "method": "GET",
        "path": "/ingest/v1/findings",
        "query": {"status": "pending", "limit": 20},
        "scope": SCOPE_RUNS_READ,
        "description": "列出待审判发现，可按 status / run 过滤",
    },
    {
        "step": "read_finding",
        "method": "GET",
        "path": "/ingest/v1/findings/{finding_id}",
        "scope": SCOPE_RUNS_READ,
        "description": "按 FND 编号读取发现、用例、日志、请求响应与关联契约",
    },
    {
        "step": "read_defect",
        "method": "GET",
        "path": "/ingest/v1/defects/{defect_id}",
        "scope": SCOPE_RUNS_READ,
        "description": "按 DEF 编号读取缺陷、来源发现与运行证据",
    },
    {
        "step": "read_requirements_full",
        "method": "GET",
        "path": "/ingest/v1/assets/requirements",
        "scope": SCOPE_ASSETS_READ,
        "description": "全量导出需求，仅用于导出",
    },
    {
        "step": "read_openapi",
        "method": "GET",
        "path": "/ingest/v1/assets/openapi",
        "scope": SCOPE_ASSETS_READ,
        "description": "全量导出 OpenAPI，仅用于导出",
    },
    {
        "step": "write_requirements",
        "method": "POST",
        "path": "/ingest/v1/requirements",
        "scope": SCOPE_ASSETS_WRITE,
        "description": "批量写入需求，需 Idempotency-Key",
    },
    {
        "step": "write_openapi",
        "method": "POST",
        "path": "/ingest/v1/openapi",
        "scope": SCOPE_ASSETS_WRITE,
        "description": "批量写入接口契约，需 Idempotency-Key",
    },
    {
        "step": "write_catalog",
        "method": "POST",
        "path": "/ingest/v1/catalog",
        "scope": SCOPE_CATALOG_WRITE,
        "description": "写入用例索引；正文先 commit 并 push 到项目测试仓库，再上报实际 "
        "source(repo/ref/commit) 与 framework",
    },
    {
        "step": "upload_run",
        "method": "POST",
        "path": "/ingest/v1/runs",
        "scope": SCOPE_RUNS_WRITE,
        "description": "平台不执行测试；AI 在本地或外部执行后上传结果与证据，需 "
        "Idempotency-Key；其它框架或临时脚本用 framework=script",
    },
    {
        "step": "upload_artifact",
        "method": "POST",
        "path": "/ingest/v1/runs/{run_id}/artifacts",
        "scope": SCOPE_RUNS_WRITE,
        "description": "上传 HAR / 截图等证据",
    },
    {
        "step": "job_status",
        "method": "GET",
        "path": "/ingest/v1/jobs/{job_id}",
        "scope": SCOPE_ANY,
        "description": "查询异步入库任务",
    },
)
