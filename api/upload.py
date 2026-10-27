"""证据附件上传。"""

import os

import secrets

from flask import g, jsonify, request

from . import api_bp

from .deps import token_required

from db import UPLOAD_DIR, get_db, log_audit, now

# 证据文件白名单：截图 / HAR / 文本日志 / PDF / 录屏。可执行文件与脚本一律拒收。
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp", "har", "txt", "json", "log", "pdf", "mp4"}

@api_bp.route("/upload", methods=["POST"])
@token_required
def api_upload():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    ext = os.path.splitext(f.filename or "")[1].lstrip(".").lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"error": f"不允许的文件类型 .{ext or '(无扩展名)'}，"
                                 f"白名单：{'/'.join(sorted(ALLOWED_EXT))}"}), 400
    stored = f"{secrets.token_hex(8)}_{os.path.basename(f.filename)}"
    f.save(os.path.join(UPLOAD_DIR, stored))
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO attachments (filename, stored_name, linked_type, linked_id, created_at) "
        "VALUES (?,?,?,?,?)",
        (f.filename, stored, request.form.get("linked_type", ""),
         request.form.get("linked_id", type=int), now()),
    )
    conn.commit()
    conn.close()
    log_audit(g.actor, "api_upload", f"attachment:{cur.lastrowid}", f.filename)
    return jsonify({"id": cur.lastrowid, "stored_name": stored,
                    "url": f"/files/{stored}"}), 201

