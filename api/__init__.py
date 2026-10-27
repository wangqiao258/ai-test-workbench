"""API 蓝图：/api/* 全部端点，统一以 X-API-Token 鉴权。"""
from flask import Blueprint

api_bp = Blueprint("api", __name__, url_prefix="/api")

from . import (  # noqa: E402,F401  （导入即注册路由）
    bugs,
    cases,
    coverage,
    docs,
    executions,
    generation,
    interfaces,
    meta,
    packets,
    projects,
    runs,
    settings,
    upload,
)
