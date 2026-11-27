"""结构化访问日志：一行一个 JSON，按天切分，便于后续用 jq / DuckDB 分析。"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Iterable
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import get_settings
from app.core.time import utcnow

_SENSITIVE_KEYS = (
    "token",
    "ticket",
    "secret",
    "password",
    "authorization",
    "api_key",
    "apikey",
    "access_key",
)
_SKIP_PATHS = {"/healthz", "/favicon.ico"}


def redact_query(items: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    query: dict[str, list[str]] = {}
    for key, value in items:
        lowered = key.lower()
        safe_value = "***" if any(word in lowered for word in _SENSITIVE_KEYS) else value
        query.setdefault(key, []).append(safe_value)
    return query


def _access_logger() -> logging.Logger:
    logger = logging.getLogger("workbench.access")
    if logger.handlers:
        return logger

    settings = get_settings()
    path = Path(settings.access_log_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(
        path,
        when="midnight",
        backupCount=settings.access_log_retention_days,
        encoding="utf-8",
        utc=True,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def _auth_label(request: Request) -> str | None:
    token = request.headers.get("x-project-token")
    if token:
        return f"project:{token[:12]}"
    if request.query_params.get("ticket"):
        return "ticket"
    if request.headers.get("authorization"):
        return "user"
    return None


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path in _SKIP_PATHS:
            return await call_next(request)

        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        started = time.perf_counter()
        response = None
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            route = request.scope.get("route")
            record = {
                "ts": utcnow().isoformat(timespec="milliseconds"),
                "requestId": request_id,
                "method": request.method,
                "path": request.url.path,
                "route": getattr(route, "path", None),
                "projectId": getattr(request.state, "project_id", None),
                "query": redact_query(request.query_params.multi_items()),
                "status": status,
                "durationMs": elapsed_ms,
                "client": request.client.host if request.client else None,
                "auth": _auth_label(request),
                "contentType": request.headers.get("content-type"),
                "requestBytes": request.headers.get("content-length"),
                "responseBytes": (
                    response.headers.get("content-length") if response else None
                ),
                "userAgent": (request.headers.get("user-agent") or "")[:200],
            }
            try:
                _access_logger().info(
                    json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                )
            except Exception:
                # 日志失败不能影响请求本身。
                pass
