"""文档：叙述性内容，AI 写入即生效（免审）。

文档的实际角色是"给下一次会话读的交接笔记 + 结论存档"：AI 写、AI 读，
人几乎不逐条看。2026-10-22 起取消审核状态轴（实测 13 份文档零意见），
质量控制落在服务端规则（dtype / 字数 / 归类）与 evidence 上。
"""

from flask import g, jsonify, request

from . import api_bp

from .common import api_list, check_project

from .deps import token_required

from core.validation import validate_doc

from db import get_db, log_audit, now

@api_bp.route("/docs", methods=["GET", "POST"])
@token_required
def api_docs():
    if request.method == "GET":
        # 旧调用习惯带的 &status= 参数静默忽略（该列已删除，不再有审核状态）
        return api_list("docs", [
            ("project_id", request.args.get("project_id", type=int)),
            ("dtype", request.args.get("dtype", "")),
        ], order_by="updated_at DESC")
    data = request.get_json(force=True)
    if not data.get("project_id") or not data.get("title"):
        return jsonify({"error": "project_id and title required"}), 400
    err = validate_doc(data.get("dtype", "general"), data["title"], data.get("content", ""))
    if err:
        log_audit(g.actor, "api_create_doc_rejected", f"title:{data['title']}", err)
        return jsonify({"error": err}), 400
    conn = get_db()
    pid, err = check_project(conn, data.get("project_id"))
    if err:
        conn.close()
        return jsonify({"error": err}), 404 if "不存在" in err else 400
    cur = conn.execute(
        "INSERT INTO docs (project_id, dtype, title, content, created_by, evidence, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (pid, data.get("dtype", "general"), data["title"],
         data.get("content", ""), g.actor, data.get("evidence", ""), now(), now()),
    )
    conn.commit()
    conn.close()
    log_audit(g.actor, "api_create_doc", f"doc:{cur.lastrowid}", data["title"])
    return jsonify({"id": cur.lastrowid, "dtype": data.get("dtype", "general")}), 201

