"""数据包证据 API。

一次实测 = 一条 packet：完整请求（method/url/query/headers/body）
+ 完整响应（status/headers/body/duration）。

三条硬规则：
1. 完整度由服务端算，不接受调用方自报；只有 full 才能把接口置为 verified。
2. 响应体超过 INLINE_CHARS 一律落盘，DB 存引用 —— 不截断、不丢尾巴。
3. 读取时分档：列表不带报文，详情默认给预览并**明说**这是预览，
   要原文加 ?body=full 或走 /download。
"""

import json
import os

from flask import Response, g, jsonify, request, send_file

from . import api_bp

from .common import api_list, rows_to_list

from .deps import token_required

from core.packets import (FULL, completeness, normalize, raw_text, render_text,
                          spill_figure, spill_name)

from db import UPLOAD_DIR, get_db, log_audit, now

PACKET_DIR = os.path.join(UPLOAD_DIR, "packets")

# 预览档给多少字符。这是**显示层**截断，与存储无关：
# 响应里同时回 preview_chars 和 resp_chars，调用方一眼能看出这是预览。
PREVIEW_CHARS = 2000

# 列表档：不带报文正文，避免 161 条 × 11 万字符那种体积
PACKET_META = ("id", "project_id", "linked_type", "linked_id", "label", "req_method",
               "req_url", "resp_status", "resp_chars", "resp_bytes", "duration_ms",
               "completeness", "missing", "resp_body_file", "sha256",
               "created_by", "captured_at", "created_at")


def _linked_project(conn, linked_type, linked_id):
    """数据包要挂的对象属于哪个项目。executions 没有 project_id，经 cases 反查。"""
    if linked_type == "interface":
        row = conn.execute("SELECT project_id FROM interfaces WHERE id=?",
                           (linked_id,)).fetchone()
        return row["project_id"] if row else None
    if linked_type == "bug":
        row = conn.execute("SELECT project_id FROM bugs WHERE id=?",
                           (linked_id,)).fetchone()
        return row["project_id"] if row else None
    row = conn.execute(
        "SELECT c.project_id FROM executions e JOIN cases c ON c.id=e.case_id "
        "WHERE e.id=?", (linked_id,)).fetchone()
    return row["project_id"] if row else None


def _store_body(sha, chars, body):
    """响应体落盘。返回相对 UPLOAD_DIR 的路径。

    文件名只由 sha 前 16 位与字符数拼成，不含用户输入。
    同一份响应重复提交会命中同一文件名（内容寻址），不产生冗余文件。
    """
    os.makedirs(PACKET_DIR, exist_ok=True)
    name = spill_name(sha, chars)
    path = os.path.join(PACKET_DIR, name)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(body)
    return f"packets/{name}"


def packet_rows(conn, linked_type, linked_id):
    """给页面用：取某对象下的全部数据包元信息（不含报文正文）。"""
    if linked_type not in ("interface", "bug", "execution") or not linked_id:
        return []
    return rows_to_list(conn.execute(
        f"SELECT {', '.join(PACKET_META)} FROM packets "
        "WHERE linked_type=? AND linked_id=? ORDER BY id DESC",
        (linked_type, linked_id)))


def packet_bodies(conn, packet_id, preview=True):
    """取一条数据包，带回正文。preview=True 时响应体只给前 N 字符并标 preview。"""
    row = conn.execute("SELECT * FROM packets WHERE id=?", (packet_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    body = data.pop("resp_body", "") or ""
    if not body and data.get("resp_body_file"):
        path = os.path.join(UPLOAD_DIR, data["resp_body_file"])
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                body = f.read()
        except OSError:
            body = ""
            data["body_file_missing"] = True
    total = len(body)
    if preview and total > PREVIEW_CHARS:
        data["resp_body"] = body[:PREVIEW_CHARS]
        data["preview_chars"] = PREVIEW_CHARS
        data["body_truncated_for_display"] = True   # 仅显示层，存储是完整的
    else:
        data["resp_body"] = body
        data["preview_chars"] = None
        data["body_truncated_for_display"] = False
    data["resp_chars_actual"] = total
    return data


VIEW_CHARS = 20000   # 页面上单条响应体最多渲染多少字符；超出显式提示 + 给下载


def packets_for_view(conn, linked_type, linked_id):
    """页面渲染用：带正文的完整数据包。

    大响应在这里会截到 VIEW_CHARS，但**只在渲染层**：
    返回值同时带 resp_chars_total 与 view_truncated，模板据此显示
    "预览已截断，完整 N 字符"并给下载入口，存储永远是全量。

    `raw` 是原生报文文本（core/packets.raw_text）：请求行 + 头 + 体 +
    状态行 + 头 + 体，头按入库顺序、body 不改一个字符。2026-10-26 起
    页面直接渲染它，不再拆双栏/表格——证据的呈现形式就是抓包那一刻的
    原文（截断时 raw 同步截，view_truncated 提示与下载入口不受影响）。
    """
    out = []
    for meta in packet_rows(conn, linked_type, linked_id):
        d = packet_bodies(conn, meta["id"], preview=False) or meta
        body = d.get("resp_body") or ""
        total = len(body)
        if total > VIEW_CHARS:
            d["resp_body"] = body[:VIEW_CHARS]
            d["view_truncated"] = True
        else:
            d["view_truncated"] = False
        d["resp_chars_total"] = total
        d["raw"] = raw_text(d)
        out.append(d)
    return out


def insert_packet(conn, norm, actor):
    """把规整好的报文写进 packets，必要时落盘。返回 (id, level, meta)。

    单独抽出来，是为了 POST /api/interfaces 带 packet 时能复用——
    建接口与建数据包要在同一个事务里，不能各写一份落盘逻辑。
    调用方负责 commit。
    """
    level, missing = completeness(norm)
    to_spill, chars, nbytes, sha = spill_figure(norm["resp_body"])
    body_file, body_inline = "", norm["resp_body"]
    if to_spill:
        body_file = _store_body(sha, chars, norm["resp_body"])
        body_inline = ""            # 大响应不双写，只留文件
    captured = norm["captured_at"] or now()
    cur = conn.execute(
        "INSERT INTO packets (project_id, linked_type, linked_id, label, req_method, "
        "req_url, req_query, req_headers, req_body, resp_status, resp_headers, resp_body, "
        "resp_body_file, resp_chars, resp_bytes, duration_ms, sha256, completeness, missing, "
        "created_by, captured_at, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (norm["project_id"], norm["linked_type"], norm["linked_id"], norm["label"],
         norm["req_method"], norm["req_url"], norm["req_query"], norm["req_headers"],
         norm["req_body"], norm["resp_status"], norm["resp_headers"], body_inline,
         body_file, chars, nbytes, norm["duration_ms"], sha, level, missing,
         actor, captured, now()),
    )
    meta = {"id": cur.lastrowid, "completeness": level, "missing": missing,
            "stored": "file" if body_file else "inline", "resp_body_file": body_file,
            "resp_chars": chars, "resp_bytes": nbytes, "sha256": sha}
    return cur.lastrowid, level, meta


@api_bp.route("/packets", methods=["GET", "POST"])
@token_required
def api_packets():
    if request.method == "GET":
        filters = [
            ("project_id", request.args.get("project_id", type=int)),
            ("linked_type", request.args.get("linked_type", "")),
            ("linked_id", request.args.get("linked_id", type=int)),
            ("completeness", request.args.get("completeness", "")),
        ]
        return api_list("packets", filters, fields=PACKET_META, order_by="id DESC",
                        limit=request.args.get("limit", type=int),
                        offset=request.args.get("offset", type=int))

    data = request.get_json(force=True)
    norm, err = normalize(data)
    if err:
        return jsonify({"error": err}), 400

    conn = get_db()
    pid = _linked_project(conn, norm["linked_type"], norm["linked_id"])
    if pid is None:
        conn.close()
        return jsonify({"error": f"{norm['linked_type']} {norm['linked_id']} 不存在"}), 400
    if pid != norm["project_id"]:
        conn.close()
        return jsonify({"error": f"linked_id 属于项目 {pid}，与 project_id "
                                 f"{norm['project_id']} 不一致"}), 400

    packet_id, level, meta = insert_packet(conn, norm, g.actor)

    # 只有完整数据包才配得上 verified（这就是本次改造的核心）
    if norm["linked_type"] == "interface" and level == FULL:
        conn.execute(
            "UPDATE interfaces SET verify_status='verified', verified_at=?, updated_at=? "
            "WHERE id=?", (now(), now(), norm["linked_id"]))
    conn.commit()
    # 回读接口的**真实当前状态**，而不是按本次包推断。
    # 否则给一条已验证的接口补了个残缺包，返回里会谎报 unverified。
    actual = None
    if norm["linked_type"] == "interface":
        row = conn.execute("SELECT verify_status FROM interfaces WHERE id=?",
                           (norm["linked_id"],)).fetchone()
        actual = row["verify_status"] if row else None
    conn.close()

    log_audit(g.actor, "api_create_packet", f"packet:{packet_id}",
              f"{norm['linked_type']}:{norm['linked_id']} {level} {meta['resp_chars']}字符")

    resp = dict(meta)
    if actual:
        resp["verify_status"] = actual
        if level != FULL:
            resp["hint"] = (f"数据包不完整（{meta['missing']}），未改动接口状态，"
                            f"接口仍为 {actual}；补齐后可再提交一条")
    return jsonify(resp), 201


@api_bp.route("/packets/<int:pkid>")
@token_required
def api_packet_detail(pkid):
    mode = (request.args.get("body") or "preview").strip().lower()
    if mode not in ("preview", "full", "none"):
        return jsonify({"error": "body 只能是 preview / full / none"}), 400
    conn = get_db()
    row = conn.execute("SELECT id FROM packets WHERE id=?", (pkid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "not found"}), 404
    data = packet_bodies(conn, pkid, preview=(mode != "full"))
    conn.close()
    if mode == "none":
        data.pop("resp_body", None)
    data["text"] = render_text(data, resp_body=data.get("resp_body"))
    return jsonify(data)


@api_bp.route("/packets/<int:pkid>/download")
@token_required
def api_packet_download(pkid):
    """下载响应体原文。落盘的直接发文件，内联的包成文本附件发出去。"""
    conn = get_db()
    row = conn.execute("SELECT * FROM packets WHERE id=?", (pkid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    body = row["resp_body"] or ""
    if not body and row["resp_body_file"]:
        # basename 兜底：即使库里的路径被改坏也出不了 uploads/ 目录
        path = os.path.join(UPLOAD_DIR, "packets", os.path.basename(row["resp_body_file"]))
        if not os.path.exists(path):
            return jsonify({"error": "响应体文件缺失"}), 410
        return send_file(path, mimetype="text/plain",
                         as_attachment=True,
                         download_name=f"packet-{pkid}-{row['resp_status']}.txt")
    return Response(body, content_type="text/plain; charset=utf-8", headers={
        "Content-Disposition": f"attachment; filename=packet-{pkid}-{row['resp_status']}.txt"})


@api_bp.route("/packets/<int:pkid>/raw")
@token_required
def api_packet_raw(pkid):
    """原始报文：请求段 + 响应段，纯文本。

    与 /download 的区别：那个只给响应体，请求行/请求头/响应头全丢；复核要的
    是整段报文。这里不裁头、不截体，大响应也读全量文件。
    """
    conn = get_db()
    data = packet_bodies(conn, pkid, preview=False)
    conn.close()
    if not data:
        return jsonify({"error": "not found"}), 404
    return Response(raw_text(data), content_type="text/plain; charset=utf-8")


@api_bp.route("/packets/<int:pkid>", methods=["DELETE"])
@token_required
def api_packet_delete(pkid):
    """删掉误录的数据包。落盘的响应体一并清理。"""
    conn = get_db()
    row = conn.execute("SELECT resp_body_file FROM packets WHERE id=?", (pkid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "not found"}), 404
    conn.execute("DELETE FROM packets WHERE id=?", (pkid,))
    conn.commit()
    conn.close()
    if row["resp_body_file"]:
        path = os.path.join(UPLOAD_DIR, "packets", os.path.basename(row["resp_body_file"]))
        try:
            os.remove(path)
        except OSError:
            pass
    log_audit(g.actor, "api_delete_packet", f"packet:{pkid}")
    return jsonify({"deleted": pkid})
