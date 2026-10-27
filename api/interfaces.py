"""接口：一接口一记录，路径/域名规范化。

接口免审（2026-10-22）：实测 161 条零驳回零意见，approve 按钮是"标记已读"。
质量信号改为单一轴 verify_status：
    verified   —— 有**完整数据包**（packets 里一条 completeness=full 的报文）
    unverified —— 无完整数据包（文字摘要不算）
    changed    —— 契约字段被改过但没重测，下次生成用例前应复测

2026-10-22 二次修正：原来判定是 `bool(evidence.strip())`，于是 10 个字符的
`GET -> 200` 也能把接口标成"已验证"，161 条里 78% 的证据无法复核。
现在 evidence 退为一句人读摘要，验证身份只认 packets 里的完整报文。
"""

from flask import g, jsonify, request

from . import api_bp

from .common import INTERFACE_FIELD_SETS, api_list, pick_fields

from .deps import token_required

from .packets import insert_packet

from core.packets import FULL, normalize as normalize_packet

from core.validation import HOST_ERR, PATH_ERR, normalize_host, normalize_path

from db import get_db, log_audit, now

# 改动这些字段等于改了契约本身 → verify_status 降级为 changed
CONTRACT_FIELDS = ("module", "name", "method", "path", "host", "req_headers",
                   "req_params", "resp_example", "error_codes")

VERIFY_VOCAB = ("verified", "unverified", "changed")
# 2026-10-26 治理：verified 只能由"完整数据包"产生，不接受调用方自封。
# 起因——线上 161/161 全 verified，真有数据包的只有 3 条，质量轴失去分辨力。
# 历史导入请导成 unverified/changed，复测后补一条完整数据包自动升 verified。
SELF_SEALABLE = ("unverified", "changed")

@api_bp.route("/interfaces", methods=["GET", "POST"])
@token_required
def api_interfaces():
    if request.method == "GET":
        fields, field_key = pick_fields(
            INTERFACE_FIELD_SETS, request.args.get("fields"), "contract")
        prefix = (request.args.get("path_prefix") or "").strip()
        if prefix and not prefix.startswith("/"):
            prefix = "/" + prefix
        # module 可多值：?module=A&module=B → IN (?,?)。AI 生成用例时常要一次读多个模块，
        # 原来只取第一个值，第二个会被静默丢掉，生成时就会漏掉整个模块。
        mods = [m.strip() for m in request.args.getlist("module") if m.strip()]
        filters = [("project_id", request.args.get("project_id", type=int)),
                   ("method", request.args.get("method", "").upper()),
                   ("path__like", prefix)]
        if mods:
            filters.insert(1, ("module__in", mods))
        # 旧调用带的 &status= 静默忽略（该列已删除）
        return api_list("interfaces", filters, fields=fields,
                        order_by="path ASC", limit=request.args.get("limit", type=int),
                        offset=request.args.get("offset", type=int))
    data = request.get_json(force=True)
    if not data.get("project_id") or not data.get("path") or not data.get("name"):
        return jsonify({"error": "project_id, name, path required"}), 400
    path = normalize_path(data["path"])
    if not path:
        log_audit(g.actor, "api_create_interface_rejected", data.get("name", ""), PATH_ERR)
        return jsonify({"error": PATH_ERR}), 400
    host = normalize_host(data.get("host"))
    if host is None:
        log_audit(g.actor, "api_create_interface_rejected", data.get("name", ""), HOST_ERR)
        return jsonify({"error": HOST_ERR}), 400
    import json as _json
    for field in ("req_headers", "req_params", "error_codes"):
        v = data.get(field, "")
        if isinstance(v, (list, dict)):
            data[field] = _json.dumps(v, ensure_ascii=False)
    has_evidence = bool((data.get("evidence") or "").strip())
    # 显式声明状态只留给"从外部导入历史数据"的场景；verified 不许自封——
    # 它只能来自 packets 里一条 completeness=full 的报文（见 SELF_SEALABLE）。
    explicit = (data.get("verify_status") or "").strip() or None
    if explicit and explicit not in VERIFY_VOCAB:
        return jsonify({"error": f"verify_status 只能是 {list(VERIFY_VOCAB)} 之一"}), 400
    if explicit == "verified":
        return jsonify({"error": "verify_status=verified 不能自封：请随接口提交一条完整数据包"
                                 "（packet 字段），或复测后用 PUT 带 packet 升级"}), 400
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO interfaces (project_id, module, name, method, path, host, req_headers, req_params, "
        "resp_example, error_codes, notes, evidence, verified_at, verify_status, "
        "created_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (data["project_id"], data.get("module", ""), data["name"],
         data.get("method", "GET").upper(), path, host,
         data.get("req_headers", ""), data.get("req_params", ""),
         data.get("resp_example", ""), data.get("error_codes", ""),
         data.get("notes", ""), data.get("evidence", ""),
         data.get("verified_at", "") or "",
         explicit or "unverified",
         g.actor, now(), now()),
    )
    iid = cur.lastrowid
    if data.get("module"):
        conn.execute("INSERT OR IGNORE INTO modules (project_id, name) VALUES (?,?)",
                     (data["project_id"], data["module"]))

    # 可选：建接口时一并提交真实数据包，省掉"先建后挂"两次往返
    packet_meta = None
    if isinstance(data.get("packet"), dict):
        pin = dict(data["packet"])
        pin["project_id"] = data["project_id"]      # 服务端填，不信调用方
        pin["linked_type"] = "interface"
        pin["linked_id"] = iid
        pnorm, perr = normalize_packet(pin)
        if perr:
            conn.rollback()
            conn.close()
            return jsonify({"error": "packet: " + perr}), 400
        _, level, packet_meta = insert_packet(conn, pnorm, g.actor)
        if level == FULL:
            conn.execute("UPDATE interfaces SET verify_status='verified', verified_at=? "
                         "WHERE id=?", (now(), iid))
            explicit = "verified"
    conn.commit()
    conn.close()
    log_audit(g.actor, "api_create_interface", f"interface:{iid}", data["name"])
    out = {"id": iid, "verify_status": explicit or "unverified"}
    if packet_meta:
        out["packet"] = packet_meta
    if has_evidence and (explicit or "unverified") != "verified":
        out["evidence_note"] = "evidence 只是一句摘要，不再参与验证判定；要置为 verified 请提交完整数据包"
    return jsonify(out), 201

@api_bp.route("/interfaces/<int:iid>", methods=["PUT"])
@token_required
def api_interface_update(iid):
    """更新接口（复测后刷新定义/证据）。

    免审后不再有"重新待审核"，改为自动维护 verify_status：
    - 本次带**完整数据包**（packet.completeness=full）→ verified，刷新 verified_at
    - 只改了契约字段、没带包              → changed（提示下次生成用例前复测）
    - 只补 notes / evidence 摘要           → 状态不动（也不降级已验证的接口）
    显式传 verify_status 时以调用方为准（只留给补录历史数据的场景）。
    """
    import json as _json
    data = request.get_json(force=True)
    if data.get("verify_status") not in (None, "") and data["verify_status"] not in VERIFY_VOCAB:
        return jsonify({"error": f"verify_status 只能是 {list(VERIFY_VOCAB)} 之一"}), 400
    if data.get("verify_status") == "verified":
        return jsonify({"error": "verify_status=verified 不能自封：请随本次修改提交完整数据包"
                                 "（packet 字段），由完整度判定自动升级"}), 400
    if not data.get("verify_status"):
        data.pop("verify_status", None)      # 空值等于没传，不要写进库
    if "path" in data:
        p = normalize_path(data.get("path"))
        if not p:
            return jsonify({"error": PATH_ERR}), 400
        data["path"] = p
    if "host" in data:
        h = normalize_host(data.get("host"))
        if h is None:
            return jsonify({"error": HOST_ERR}), 400
        data["host"] = h
    conn = get_db()
    row = conn.execute("SELECT id, project_id FROM interfaces WHERE id=?", (iid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "not found"}), 404
    fields, args = [], []
    for f in ("module", "name", "method", "path", "host", "req_headers", "req_params",
              "resp_example", "error_codes", "notes", "evidence", "verify_status"):
        if f in data:
            v = data[f]
            if isinstance(v, (list, dict)):
                v = _json.dumps(v, ensure_ascii=False)
            fields.append(f"{f}=?")
            args.append(v)

    # 复测后补一个真实数据包（可与契约修改一起提交）
    packet_meta, packet_full = None, False
    if isinstance(data.get("packet"), dict):
        pin = dict(data["packet"])
        pin["project_id"] = row["project_id"]     # 一律以库里为准
        pin["linked_type"] = "interface"
        pin["linked_id"] = iid
        pnorm, perr = normalize_packet(pin)
        if perr:
            conn.close()
            return jsonify({"error": "packet: " + perr}), 400
        _, level, packet_meta = insert_packet(conn, pnorm, g.actor)
        packet_full = (level == FULL)

    if not fields and packet_meta is None:
        conn.close()
        return jsonify({"error": "nothing to update"}), 400
    if "verify_status" not in data:
        # 完整数据包 > 契约变更。只补 evidence 摘要不再能升级为 verified，
        # 也不会把已 verified 的接口降级（存量数据因此保持原样）。
        if packet_full:
            v = "verified"
        elif any(f in data for f in CONTRACT_FIELDS):
            v = "changed"
        else:
            v = None
        if v:
            fields.append("verify_status=?")
            args.append(v)
            if v == "verified":
                fields.append("verified_at=?")
                args.append(now())
    if fields:
        fields.append("updated_at=?")
        args += [now(), iid]
        conn.execute(f"UPDATE interfaces SET {', '.join(fields)} WHERE id=?", args)
    if data.get("module"):
        conn.execute("INSERT OR IGNORE INTO modules (project_id, name) VALUES (?,?)",
                     (row["project_id"], data["module"]))
    conn.commit()
    updated = conn.execute(
        "SELECT verify_status, verified_at FROM interfaces WHERE id=?", (iid,)).fetchone()
    conn.close()
    log_audit(g.actor, "api_update_interface", f"interface:{iid}", updated["verify_status"])
    out = {"id": iid, "verify_status": updated["verify_status"],
           "verified_at": updated["verified_at"]}
    if packet_meta:
        out["packet"] = packet_meta
    return jsonify(out)

@api_bp.route("/interfaces/<int:iid>", methods=["GET"])
@token_required
def api_interface_detail(iid):
    """单读一个接口（默认 contract 档，需要数据包原文时加 ?fields=full）。"""
    fields, _ = pick_fields(INTERFACE_FIELD_SETS, request.args.get("fields"), "contract")
    conn = get_db()
    row = conn.execute("SELECT * FROM interfaces WHERE id=?", (iid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    data = dict(row)
    return jsonify({k: data[k] for k in fields} if fields else data)

