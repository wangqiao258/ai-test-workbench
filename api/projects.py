"""项目 / 环境 / 账号（只读）+ OpenAPI 下载。"""

from flask import g, jsonify

from . import api_bp

from .common import api_list

from .deps import token_required

from core.openapi_doc import project_openapi

from db import log_audit

@api_bp.route("/projects")
@token_required
def api_projects():
    return api_list("projects", order_by="id ASC")

@api_bp.route("/projects/<int:pid>/environments")
@token_required
def api_envs(pid):
    return api_list("environments", [("project_id", pid)], order_by="id ASC")

@api_bp.route("/projects/<int:pid>/accounts")
@token_required
def api_accounts(pid):
    return api_list("accounts", [("project_id", pid)], order_by="id ASC")

@api_bp.route("/projects/<int:pid>/openapi.json")
@token_required
def apiproject_openapi(pid):
    """API 端下载 OpenAPI 文档（接口免审，全量导出）。

    旧调用带的 ?status=approved 静默忽略：审核状态轴已删除，
    哪条契约可信看 operation 上的 x-verify-status。
    """
    doc = project_openapi(pid)
    if doc is None:
        return jsonify({"error": "project not found"}), 404
    log_audit(g.actor, "api_export_openapi", f"project:{pid}")
    return jsonify(doc)

