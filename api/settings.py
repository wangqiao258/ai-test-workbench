"""项目级配置：P1 先用于 runner 的鉴权策略（auth），P2 再加 diff_mask。

为什么要走平台而不是 runner 本地文件：执行策略是"数据"不是"代码"（§3-8），
同一套 runner 换项目只换配置。AI 可以写，用户在设置页能看能改（网页端 P2）。
"""

from flask import g, jsonify, request

import json

from . import api_bp

from .common import json_dumps

from .deps import token_required

from core.notify import validate_notify

from db import get_db, log_audit, now

# 只认这几个键，避免 AI 往项目配置里塞任意东西
ALLOWED_KEYS = ("auth", "diff_mask", "vars", "notify")


def _validate_auth(value):
    """auth 必须是能被执行器理解的形状，返回 (规范化值, err)。"""
    if not isinstance(value, dict):
        return None, "auth 应为对象"
    typ = (value.get("type") or "").strip().lower()
    if typ not in ("login", "static"):
        return None, "auth.type 只能是 login（账号换 token）或 static（直接给 token）"
    out = {"type": typ}
    if typ == "static":
        headers = value.get("static_headers") or value.get("headers")
        if not isinstance(headers, dict) or not headers:
            return None, "static 类型必须给 static_headers（如 {Authorization, tenant-id}）"
        out["static_headers"] = headers
        return out, None
    path = (value.get("path") or "").strip()
    if not path.startswith("/") or "://" in path:
        return None, "login.path 只能是路径（如 /admin-api/system/auth/login），不能带域名"
    token_path = (value.get("token_path") or "").strip()
    if not token_path:
        return None, "login.token_path 必填（如 $.data.accessToken）"
    out.update({
        "method": (value.get("method") or "POST").upper(),
        "path": path,
        "token_path": token_path,
    })
    for k in ("headers", "body", "inject", "account_id"):
        if value.get(k):
            out[k] = value[k]
    if not out.get("inject"):
        out["inject"] = {"header": "Authorization", "prefix": "Bearer "}
    return out, None


@api_bp.route("/projects/<int:pid>/settings")
@token_required
def api_settings(pid):
    conn = get_db()
    rows = conn.execute(
        "SELECT key, value, updated_by, updated_at FROM project_settings "
        "WHERE project_id=? ORDER BY key", (pid,)).fetchall()
    conn.close()
    out = {}
    for r in rows:
        try:
            val = json.loads(r["value"])
        except (ValueError, TypeError):
            val = r["value"]
        out[r["key"]] = {"value": val, "updated_by": r["updated_by"],
                         "updated_at": r["updated_at"]}
    return jsonify(out)


@api_bp.route("/projects/<int:pid>/settings/<key>", methods=["PUT"])
@token_required
def api_setting_put(pid, key):
    if key not in ALLOWED_KEYS:
        return jsonify({"error": f"不支持的配置键 {key}（可选 {'/'.join(ALLOWED_KEYS)}）"}), 400
    data = request.get_json(force=True) or {}
    raw = data.get("value", data)
    if key == "auth":
        value, err = _validate_auth(raw)
        if err:
            return jsonify({"error": err}), 400
    elif key == "vars":
        # 项目级变量：token 这类会过期的东西只存一处，用例里写 {{vars.memberToken}}
        if not isinstance(raw, dict):
            return jsonify({"error": "vars 应为对象，如 {\"memberToken\": \"xxx\"}"}), 400
        value = {str(k): v for k, v in raw.items() if str(k).strip()}
    elif key == "notify":
        # 运行收尾通知（修复项 12）：校验收敛在 core/notify.py，网页端与 API 同一套规则
        value, err = validate_notify(raw)
        if err:
            return jsonify({"error": err}), 400
    else:
        if not isinstance(raw, dict):
            return jsonify({"error": f"{key} 应为对象"}), 400
        value = raw
    conn = get_db()
    if not conn.execute("SELECT id FROM projects WHERE id=?", (pid,)).fetchone():
        conn.close()
        return jsonify({"error": "project not found"}), 404
    conn.execute(
        "INSERT INTO project_settings (project_id, key, value, updated_by, updated_at) "
        "VALUES (?,?,?,?,?) ON CONFLICT(project_id, key) DO UPDATE SET "
        "value=excluded.value, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
        (pid, key, json_dumps(value), g.actor, now()))
    conn.commit()
    conn.close()
    log_audit(g.actor, "api_setting_put", f"project:{pid}", key)
    return jsonify({"project_id": pid, "key": key, "value": value})


@api_bp.route("/projects/<int:pid>/settings/<key>", methods=["DELETE"])
@token_required
def api_setting_delete(pid, key):
    conn = get_db()
    conn.execute("DELETE FROM project_settings WHERE project_id=? AND key=?", (pid, key))
    conn.commit()
    conn.close()
    log_audit(g.actor, "api_setting_delete", f"project:{pid}", key)
    return jsonify({"deleted": True})
