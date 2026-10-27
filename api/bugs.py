"""Bug：待审核，必须带证据。"""

from flask import g, jsonify, request

from . import api_bp

from .common import api_list, as_id, check_project, table_cols

from .deps import token_required

from core.anchors import find_similar_bug
from core.validation import BUG_REPRO_LABELS, BUG_REPRO_VOCAB

from db import get_db, log_audit, now

@api_bp.route("/bugs", methods=["GET", "POST"])
@token_required
def api_bugs():
    if request.method == "GET":
        cols = table_cols("bugs")
        filters = [
            ("project_id", request.args.get("project_id", type=int)),
            # status 轴已废弃（2026-10-22）：开发在在线表格跟进，平台只分诊。
            # 需要按进度取，用 review_status（pending / approved / rejected）。
            ("review_status", request.args.get("review_status", "")),
            ("severity", request.args.get("severity", "")),
            ("module", request.args.get("module", "")),
            ("interface_id", request.args.get("interface_id", type=int)),
        ]
        return api_list("bugs", [(c, v) for c, v in filters if c in cols],
                        order_by="id DESC", limit=request.args.get("limit", type=int),
                        offset=request.args.get("offset", type=int))
    data = request.get_json(force=True)
    if not data.get("project_id") or not data.get("title"):
        return jsonify({"error": "project_id and title required"}), 400
    repro = (data.get("repro_rate") or "").strip()
    if repro and repro not in BUG_REPRO_VOCAB:
        return jsonify({"error": f"repro_rate 只能是 {list(BUG_REPRO_VOCAB)} 之一"
                                 f"（{'/'.join(BUG_REPRO_LABELS[v] for v in BUG_REPRO_VOCAB)}）"}), 400
    conn = get_db()
    pid, err = check_project(conn, data.get("project_id"))
    if err:
        conn.close()
        return jsonify({"error": err}), 404 if "不存在" in err else 400
    # 提交前查重（2026-10-26）：标题相似度 ≥0.85 视为同一条，409 带出既有那条，
    # 让提交方在入口处就能看见"投过了"——线上 57 投 55 驳，重复提交是常见原因。
    dup = (find_similar_bug(conn, pid, data["title"])
           if not data.get("force") else None)
    if dup:
        conn.close()
        return jsonify({
            "error": "项目里已存在标题高度相似的 Bug（相似度 ≥0.85），未新增",
            "duplicate_of": dup["id"], "existing_title": dup["title"],
            "existing_status": dup["review_status"],
            "hint": "若是同一问题补充材料，PUT /api/bugs/<duplicate_of> 用 evidence_append；"
                    "确认是另一件事再重发并带 force=true",
        }), 409
    for fkey, table in (("case_id", "cases"), ("interface_id", "interfaces")):
        v = data.get(fkey)
        if v is None:
            continue
        vid = as_id(v)
        if vid is None:
            conn.close()
            return jsonify({"error": f"{fkey} 必须是数字（可省略该字段）"}), 400
        if not conn.execute(
                f"SELECT 1 FROM {table} WHERE id=?", (vid,)).fetchone():
            conn.close()
            return jsonify({"error": f"{fkey} {v} 不存在（可省略该字段）"}), 400
    cur = conn.execute(
        "INSERT INTO bugs (project_id, case_id, interface_id, title, module, severity, steps, "
        "review_status, repro_rate, impact, created_by, evidence, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?, 'pending',?,?,?,?,?,?)",
        (pid, as_id(data.get("case_id")), as_id(data.get("interface_id")),
         data["title"], data.get("module", ""),
         data.get("severity", "normal"), data.get("steps", ""),
         data.get("repro_rate", ""), (data.get("impact") or "")[:200], g.actor,
         data.get("evidence", ""), now(), now()),
    )
    conn.commit()
    conn.close()
    log_audit(g.actor, "api_create_bug", f"bug:{cur.lastrowid}", data["title"])
    return jsonify({"id": cur.lastrowid, "review_status": "pending"}), 201

@api_bp.route("/bugs/<int:bid>", methods=["PUT"])
@token_required
def api_bug_update(bid):
    """更新 Bug（补充复现材料/修正结论等）。更新后重新进入待审核。
    evidence_append：把内容追加到现有 evidence 末尾（推荐，保留历史证据）。"""
    data = request.get_json(force=True)
    conn = get_db()
    row = conn.execute("SELECT id, evidence FROM bugs WHERE id=?", (bid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "not found"}), 404
    fields, args = [], []
    for f in ("title", "module", "severity", "steps", "evidence", "repro_rate", "impact"):
        if f in data:
            if f == "repro_rate" and (data[f] or "").strip() \
                    and data[f].strip() not in BUG_REPRO_VOCAB:
                conn.close()
                return jsonify({"error": f"repro_rate 只能是 {list(BUG_REPRO_VOCAB)} 之一"}), 400
            if f == "impact":
                args.append((data[f] or "")[:200])
            else:
                args.append(data[f])
            fields.append(f"{f}=?")
    if data.get("evidence_append"):
        fields.append("evidence=?")
        args.append((row["evidence"] or "") + "\n\n" + data["evidence_append"])
    if not fields:
        conn.close()
        return jsonify({"error": "nothing to update"}), 400
    fields += ["review_status='pending'", "updated_at=?"]
    args += [now(), bid]
    conn.execute(f"UPDATE bugs SET {', '.join(fields)} WHERE id=?", args)
    conn.commit()
    conn.close()
    log_audit(g.actor, "api_update_bug", f"bug:{bid}")
    return jsonify({"id": bid, "review_status": "pending"})

