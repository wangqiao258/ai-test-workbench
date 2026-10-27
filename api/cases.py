"""用例：锚点、覆盖维度、结构化步骤、服务端查重。"""

from flask import g, jsonify, request

from . import api_bp

from .common import CASE_FIELD_SETS, api_list, as_id, check_project, json_dumps, pick_fields, table_cols

from .deps import token_required

from core.anchors import case_interface_ids, decorate_case, find_similar_case, sync_case_links
from core.generation import case_intent_fingerprint
from core.steps import normalize_steps, render_steps

from core.validation import normalize_dims, parse_dims

from db import get_db, log_audit, now

@api_bp.route("/cases", methods=["GET", "POST"])
@token_required
def api_cases():
    if request.method == "GET":
        fields, _ = pick_fields(CASE_FIELD_SETS, request.args.get("fields"), "full")
        cols = table_cols("cases")
        if fields:
            fields = tuple(f for f in fields if f in cols)
        unlinked = request.args.get("unlinked") in ("1", "true", "yes")
        iid = request.args.get("interface_id", type=int)
        # module 可多值：?module=A&module=B → IN (?,?)。与 /api/interfaces 同口径。
        mods = [m.strip() for m in request.args.getlist("module") if m.strip()]
        filters = [
            ("project_id", request.args.get("project_id", type=int)),
            ("status", request.args.get("status", "")),   # 用例已免审，该参数仅为兼容旧调用
            ("priority", request.args.get("priority", "")),
            ("doc_id", request.args.get("doc_id", type=int)),
            ("batch", request.args.get("batch", "")),
            ("target_id", request.args.get("target_id", type=int)),
            ("generation_batch_id", request.args.get("generation_batch_id", type=int)),
        ]
        if mods:
            filters.append(("module__in", mods))
        if iid:
            # 按接口取用例：主锚点 + 关联表都算（一条用例可覆盖多个接口）
            conn = get_db()
            linked = [r[0] for r in conn.execute(
                "SELECT case_id FROM case_interfaces WHERE interface_id=?", (iid,))]
            conn.close()
            filters.append(("id__in", linked))
        elif unlinked:
            filters.append(("interface_id", "__null__"))
        filters = [(c, v) for c, v in filters if c in cols or c.endswith("__in")]
        resp = api_list("cases", filters, fields=fields, order_by="id ASC",
                        limit=request.args.get("limit", type=int),
                        offset=request.args.get("offset", type=int))
        data = resp.get_json()
        total = resp.headers.get("X-Total-Count")
        for c in data:
            decorate_case(c)
        if request.args.get("with_links") in ("1", "true", "yes"):
            conn = get_db()
            for c in data:
                c["interface_ids"] = case_interface_ids(conn, c["id"])
            conn.close()
        out = jsonify(data)
        if total:
            out.headers["X-Total-Count"] = total
        return out
    data = request.get_json(force=True)
    if not data.get("project_id") or not data.get("title"):
        return jsonify({"error": "project_id and title required"}), 400
    conn = get_db()
    pid, err = check_project(conn, data.get("project_id"))
    if err:
        conn.close()
        return jsonify({"error": err}), 404 if "不存在" in err else 400
    target_id = as_id(data.get("target_id"))
    generation_batch_id = as_id(data.get("generation_batch_id"))
    if data.get("target_id") not in (None, "") and target_id is None:
        conn.close()
        return jsonify({"error": "target_id 必须是数字"}), 400
    if data.get("generation_batch_id") not in (None, "") and generation_batch_id is None:
        conn.close()
        return jsonify({"error": "generation_batch_id 必须是数字"}), 400
    target, novelty, generation_strategy = None, "", ""
    if target_id is not None:
        if generation_batch_id is None:
            conn.close()
            return jsonify({"error": "目标生成用例必须带 generation_batch_id"}), 400
        target = conn.execute("SELECT * FROM test_targets WHERE id=?", (target_id,)).fetchone()
        if not target:
            conn.close()
            return jsonify({"error": f"test target {target_id} 不存在"}), 404
        if target["project_id"] != pid:
            conn.close()
            return jsonify({"error": "测试目标与用例不属于同一项目"}), 400
        if target["status"] not in ("claimed", "generated") \
                or target["generation_batch_id"] != generation_batch_id:
            conn.close()
            return jsonify({"error": "目标未由该生成批次领取，请先 POST /api/test-targets/next"}), 409
        if target["claimed_by"] != g.actor:
            conn.close()
            return jsonify({"error": "目标已由其他 AI 身份领取"}), 409
        batch = conn.execute(
            "SELECT project_id, status FROM generation_batches WHERE id=?",
            (generation_batch_id,)).fetchone()
        if not batch or batch["project_id"] != pid:
            conn.close()
            return jsonify({"error": "生成批次不存在或不属于该项目"}), 404
        if batch["status"] != "open":
            conn.close()
            return jsonify({"error": "生成批次已结束，不能继续提交用例"}), 409
        novelty = str(data.get("novelty") or "").strip()
        if not novelty:
            conn.close()
            return jsonify({"error": "目标生成用例必须填写 novelty：相对已有用例新增什么覆盖"}), 400
        generation_strategy = target["strategy"]
        if data.get("generation_strategy") and data["generation_strategy"] != generation_strategy:
            conn.close()
            return jsonify({"error": "generation_strategy 必须与目标策略一致"}), 400
        data = dict(data)
        for key in ("interface_id", "doc_id", "module"):
            if data.get(key) in (None, "") and target[key]:
                data[key] = target[key]
    elif generation_batch_id is not None:
        conn.close()
        return jsonify({"error": "generation_batch_id 必须与 target_id 一起使用"}), 400
    cols = table_cols("cases")
    itf_id = as_id(data.get("interface_id"))
    doc_id = as_id(data.get("doc_id"))
    if data.get("interface_id") not in (None, "") and itf_id is None:
        conn.close()
        return jsonify({"error": "interface_id 必须是数字"}), 400
    if data.get("doc_id") not in (None, "") and doc_id is None:
        conn.close()
        return jsonify({"error": "doc_id 必须是数字"}), 400
    module = (data.get("module") or "").strip()
    # 一条用例可以覆盖多个接口（如"分页边界"同时覆盖 3 个列表接口）：
    # interface_id 是主锚点（决定 module、页面归属），interface_ids 是全量关联。
    link_ids = [as_id(i) for i in (data.get("interface_ids") or [])]
    if any(i is None for i in link_ids) and data.get("interface_ids"):
        conn.close()
        return jsonify({"error": "interface_ids 里的元素必须是数字"}), 400
    link_ids = [i for i in link_ids if i]
    if itf_id is not None and itf_id not in link_ids:
        link_ids = [itf_id] + link_ids
    if itf_id is None and link_ids:
        itf_id = link_ids[0]
    for lid in link_ids:
        row = conn.execute("SELECT id, module FROM interfaces WHERE id=?", (lid,)).fetchone()
        if not row:
            conn.close()
            return jsonify({"error": f"interface_ids 里的 {lid} 不存在"}), 400
        if lid == itf_id:
            module = row["module"] or module   # module 由主锚点接口派生，不接受手填
    if doc_id is not None:
        doc = conn.execute("SELECT id FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not doc:
            conn.close()
            return jsonify({"error": f"doc_id {doc_id} 不存在"}), 400
    if itf_id is None and doc_id is None and not module:
        conn.close()
        return jsonify({"error": "缺锚点：interface_id / doc_id / module 至少给一个，"
                                 "否则用例无法归集，后续生成时无法避免重复"}), 400
    dims, err = normalize_dims(data.get("dims"))
    if err:
        conn.close()
        return jsonify({"error": err}), 400
    steps_struct, err = normalize_steps(data.get("steps_json"))
    if err:
        conn.close()
        return jsonify({"error": err}), 400
    steps_text = (data.get("steps") or "").strip()
    if steps_struct and not steps_text:
        steps_text = render_steps(steps_struct)     # 有结构就自动渲染，避免两份数据各写各的
    case_data = {**data, "project_id": pid, "interface_id": itf_id,
                 "interface_ids": link_ids, "doc_id": doc_id, "module": module,
                 "steps": steps_text, "steps_json": steps_struct or data.get("steps_json")}
    fingerprint = case_intent_fingerprint(case_data, link_ids)
    # force 也先查一次：409 的拦截面不改，但要能把"覆盖了哪条"写进审计
    dup = find_similar_case(conn, case_data, itf_id, module)
    forced = bool(data.get("force"))
    if dup and not forced:
        kind = dup.get("duplicate_kind", "title")
        conn.close()
        return jsonify({
            "error": ("项目里已存在测试行为相同的用例，未新增" if kind == "intent"
                      else "项目里已存在标题高度相似的用例（相似度 ≥0.85），未新增"),
            "duplicate_kind": kind,
            "duplicate_of": dup["id"], "existing_title": dup["title"],
            "existing_anchor": {"interface_id": dup["interface_id"], "module": dup["module"]},
            # 让 AI 一眼看出已有那条覆盖了哪些维度，别为了"换个维度"去 force
            "existing_dims": parse_dims(dup.get("dims")),
            "hint": ("若是重复目标，POST /api/test-targets/<target_id>/feedback "
                     "{\"outcome\":\"duplicate\"}；" if target_id else "")
                    + "行为确实不同再重发并带 force=true + force_reason",
        }), 409
    fields = ["project_id", "module", "title", "preconditions", "steps", "expected",
              "priority", "source", "created_by", "interface_id"]
    vals = [pid, module, data["title"],
            data.get("preconditions", ""), steps_text, data.get("expected", ""),
            data.get("priority", "P2"), "ai", g.actor, itf_id]
    for opt, val in (("doc_id", doc_id), ("dims", json_dumps(dims) if dims else ""),
                     ("batch", data.get("batch", "")),
                     ("steps_json", json_dumps(steps_struct) if steps_struct else ""),
                     ("target_id", target_id), ("generation_batch_id", generation_batch_id),
                     ("generation_strategy", generation_strategy),
                     ("intent_fingerprint", fingerprint), ("novelty", novelty[:1000])):
        if opt in cols:
            fields.append(opt)
            vals.append(val)
    fields += ["created_at", "updated_at"]
    vals += [now(), now()]
    cur = conn.execute(
        f"INSERT INTO cases ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
        vals,
    )
    case_id = cur.lastrowid
    sync_case_links(conn, case_id, link_ids)
    if target_id:
        conn.execute(
            "UPDATE test_targets SET status='generated', last_result='', feedback='', "
            "covered_at='', updated_at=? WHERE id=?", (now(), target_id))
    conn.commit()
    conn.close()
    if forced:
        # force 是唯一的查重旁路，必须留痕：谁放过了哪条、理由是什么
        detail = data["title"] + (f" / target:{target_id}" if target_id else "")
        if dup:
            detail += (f" / 放过了 case:{dup['id']}（{dup.get('duplicate_kind', 'title')}"
                       f"，{dup['title']}）")
        else:
            detail += " / 未与既有用例重复"
        detail += " / 理由：" + ((data.get("force_reason") or "").strip()[:300] or "未填")
        log_audit(g.actor, "api_create_case_force", f"case:{case_id}", detail)
    else:
        log_audit(g.actor, "api_create_case", f"case:{case_id}",
                  data["title"] + (f" / target:{target_id}" if target_id else ""))
    return jsonify({"id": case_id, "module": module, "dims": dims,
                    "interface_ids": link_ids, "steps_json": steps_struct,
                    "target_id": target_id, "generation_batch_id": generation_batch_id,
                    "generation_strategy": generation_strategy,
                    "intent_fingerprint": fingerprint, "novelty": novelty}), 201

@api_bp.route("/cases/<int:cid>", methods=["GET"])
@token_required
def api_case_detail(cid):
    """单读一条用例（含完整步骤，执行前用它拿 steps，不要为此拉全项目用例）。"""
    conn = get_db()
    row = conn.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    data = dict(row)
    conn = get_db()
    data["interface_ids"] = case_interface_ids(conn, cid)
    conn.close()
    decorate_case(data)
    return jsonify(data)

@api_bp.route("/cases/<int:cid>", methods=["PUT"])
@token_required
def api_case_update(cid):
    """改用例（补维度、改步骤、重新挂锚点）。用例免审，改完直接生效。"""
    data = request.get_json(force=True)
    conn = get_db()
    row = conn.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "not found"}), 404
    cols = table_cols("cases")
    fields, args = [], []
    for f in ("title", "preconditions", "steps", "expected", "priority", "batch", "doc_id"):
        if f in data and f in cols:
            fields.append(f"{f}=?")
            args.append(data[f])
    if "interface_id" in data or "interface_ids" in data:
        if "interface_ids" in data:
            ids = [i for i in (data.get("interface_ids") or []) if i]
        else:                                   # 只改主锚点：保留其余关联
            ids = case_interface_ids(conn, cid)
            iid = data.get("interface_id")
            ids = ([iid] if iid else []) + [x for x in ids if x != iid]
        primary = data.get("interface_id")
        if primary not in ids:
            primary = ids[0] if ids else None
        for lid in ids:
            if not conn.execute("SELECT 1 FROM interfaces WHERE id=?", (lid,)).fetchone():
                conn.close()
                return jsonify({"error": f"interface_id {lid} 不存在"}), 400
        fields.append("interface_id=?")
        args.append(primary)
        if primary:
            im = conn.execute("SELECT module FROM interfaces WHERE id=?", (primary,)).fetchone()
            fields.append("module=?")
            args.append(im["module"] if im else row["module"])
        sync_case_links(conn, cid, ids)
    if "dims" in data and "dims" in cols:
        dims, err = normalize_dims(data.get("dims"))
        if err:
            conn.close()
            return jsonify({"error": err}), 400
        fields.append("dims=?")
        args.append(json_dumps(dims))
    if "steps_json" in data and "steps_json" in cols:
        struct, err = normalize_steps(data.get("steps_json"))
        if err:
            conn.close()
            return jsonify({"error": err}), 400
        fields.append("steps_json=?")
        args.append(json_dumps(struct) if struct else "")
        if struct and not (data.get("steps") or "").strip():
            fields.append("steps=?")
            args.append(render_steps(struct))
    if not fields:
        conn.close()
        return jsonify({"error": "nothing to update"}), 400
    fields.append("updated_at=?")
    args += [now(), cid]
    conn.execute(f"UPDATE cases SET {', '.join(fields)} WHERE id=?", args)
    updated = dict(conn.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone())
    updated["interface_ids"] = case_interface_ids(conn, cid)
    fingerprint = case_intent_fingerprint(updated, updated["interface_ids"])
    conn.execute("UPDATE cases SET intent_fingerprint=? WHERE id=?", (fingerprint, cid))
    intent_fields = {"preconditions", "steps", "steps_json", "expected",
                     "interface_id", "interface_ids", "doc_id"}
    if updated.get("target_id") and intent_fields.intersection(data):
        conn.execute(
            "UPDATE test_targets SET status='generated', last_result='', covered_at='', "
            "feedback='关联用例已修改，需要重新执行验证', updated_at=? WHERE id=?",
            (now(), updated["target_id"]))
    updated["intent_fingerprint"] = fingerprint
    conn.commit()
    conn.close()
    log_audit(g.actor, "api_update_case", f"case:{cid}")
    decorate_case(updated)
    return jsonify(updated)

