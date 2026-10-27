"""AI 持续生成：测试目标登记、原子领取、反馈与生成批次收尾。"""
from flask import g, jsonify, request

from . import api_bp
from .common import as_id, check_project, rows_to_list
from .deps import token_required

from core.coverage import gap_targets, load_summary
from core.generation import (FEEDBACK_OUTCOMES, TARGET_PRIORITIES, TARGET_STATUSES,
                             normalize_strategy, target_fingerprint)
from db import get_db, log_audit, now


def _close_error(conn, message, status=400, rollback=False):
    if rollback:
        conn.rollback()
    conn.close()
    return jsonify({"error": message}), status


def _optional_id(data, key):
    if data.get(key) in (None, ""):
        return None, None
    value = as_id(data.get(key))
    if value is None:
        return None, f"{key} 必须是数字"
    return value, None


def _owned_row(conn, table, row_id, project_id):
    row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
    if not row:
        return None, f"{table} {row_id} 不存在", 404
    if row["project_id"] != project_id:
        return None, f"{table} {row_id} 不属于项目 {project_id}", 400
    return row, None, 200


def _hints(conn, project_id):
    fields = "id, title, intent, strategy, module, feedback, updated_at"
    failures = rows_to_list(conn.execute(
        f"SELECT {fields} FROM test_targets WHERE project_id=? AND last_result='fail' "
        "ORDER BY updated_at DESC, id DESC LIMIT 5", (project_id,)))
    blocked = rows_to_list(conn.execute(
        f"SELECT {fields} FROM test_targets WHERE project_id=? AND status='blocked' "
        "ORDER BY updated_at DESC, id DESC LIMIT 5", (project_id,)))
    return failures, blocked


def _batch_stats(conn, batch_id):
    case_row = conn.execute(
        "SELECT COUNT(*) cases, COUNT(DISTINCT target_id) targets FROM cases "
        "WHERE generation_batch_id=?", (batch_id,)).fetchone()
    results = {"pass": 0, "fail": 0, "blocked": 0}
    for row in conn.execute(
            "SELECT e.result, COUNT(*) n FROM executions e JOIN cases c ON c.id=e.case_id "
            "WHERE c.generation_batch_id=? GROUP BY e.result", (batch_id,)):
        if row["result"] in results:
            results[row["result"]] = row["n"]
    return {"cases": case_row["cases"], "targets": case_row["targets"], "results": results}


@api_bp.route("/test-targets", methods=["GET", "POST"])
@token_required
def api_test_targets():
    if request.method == "GET":
        pid = request.args.get("project_id", type=int)
        if not pid:
            return jsonify({"error": "project_id required"}), 400
        status = (request.args.get("status") or "").strip().lower()
        if status and status not in TARGET_STATUSES:
            return jsonify({"error": f"status 只能是 {'/'.join(TARGET_STATUSES)} 之一"}), 400
        strategy, err = normalize_strategy(request.args.get("strategy"), allow_empty=True)
        if err:
            return jsonify({"error": err}), 400
        where, args = ["project_id=?"], [pid]
        if status:
            where.append("status=?")
            args.append(status)
        if strategy:
            where.append("strategy=?")
            args.append(strategy)
        module = (request.args.get("module") or "").strip()
        if module:
            where.append("module=?")
            args.append(module)
        try:
            limit = max(1, min(int(request.args.get("limit", 100)), 200))
        except (TypeError, ValueError):
            limit = 100
        conn = get_db()
        rows = rows_to_list(conn.execute(
            "SELECT * FROM test_targets WHERE " + " AND ".join(where) +
            " ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 "
            "WHEN 'P2' THEN 2 ELSE 3 END, attempts, id LIMIT ?", args + [limit]))
        conn.close()
        return jsonify(rows)

    data = request.get_json(force=True) or {}
    title = str(data.get("title") or "").strip()
    intent = str(data.get("intent") or "").strip()
    if not title or not intent:
        return jsonify({"error": "title 和 intent 必填；intent 要写清具体验证风险"}), 400
    strategy, err = normalize_strategy(data.get("strategy") or "breadth")
    if err:
        return jsonify({"error": err}), 400
    priority = str(data.get("priority") or "P2").strip().upper()
    if priority not in TARGET_PRIORITIES:
        return jsonify({"error": "priority 只能是 P0/P1/P2/P3"}), 400
    ids = {}
    for key in ("interface_id", "doc_id", "parent_target_id"):
        ids[key], err = _optional_id(data, key)
        if err:
            return jsonify({"error": err}), 400

    conn = get_db()
    pid, err = check_project(conn, data.get("project_id"))
    if err:
        return _close_error(conn, err, 404 if "不存在" in err else 400)
    module = str(data.get("module") or "").strip()
    parent = None
    if ids["parent_target_id"]:
        parent, err, code = _owned_row(conn, "test_targets", ids["parent_target_id"], pid)
        if err:
            return _close_error(conn, err, code)
        module = module or parent["module"]
        ids["interface_id"] = ids["interface_id"] or parent["interface_id"]
        ids["doc_id"] = ids["doc_id"] or parent["doc_id"]
    if ids["interface_id"]:
        interface, err, code = _owned_row(conn, "interfaces", ids["interface_id"], pid)
        if err:
            return _close_error(conn, err, code)
        module = interface["module"] or module
    if ids["doc_id"]:
        _, err, code = _owned_row(conn, "docs", ids["doc_id"], pid)
        if err:
            return _close_error(conn, err, code)
    if not any((ids["interface_id"], ids["doc_id"], ids["parent_target_id"], module)):
        return _close_error(conn, "interface_id / doc_id / parent_target_id / module 至少给一个")

    target_data = {
        **ids, "module": module, "intent": intent,
        "source_ref": str(data.get("source_ref") or "").strip(),
    }
    fingerprint = target_fingerprint(target_data)
    duplicate = conn.execute(
        "SELECT id, title, status FROM test_targets WHERE project_id=? AND fingerprint=?",
        (pid, fingerprint)).fetchone()
    if duplicate and not data.get("force"):
        conn.close()
        return jsonify({
            "error": "项目里已存在相同测试意图的目标",
            "duplicate_of": duplicate["id"], "existing_title": duplicate["title"],
            "existing_status": duplicate["status"],
            "hint": "确认是不同风险再带 force=true；否则直接领取或更新已有目标",
        }), 409
    ts = now()
    cur = conn.execute(
        "INSERT INTO test_targets (project_id, module, title, intent, strategy, priority, status, "
        "interface_id, doc_id, parent_target_id, source_ref, fingerprint, created_by, created_at, "
        "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid, module, title[:200], intent, strategy, priority, "open",
         ids["interface_id"], ids["doc_id"], ids["parent_target_id"],
         target_data["source_ref"][:500], fingerprint, g.actor, ts, ts))
    target_id = cur.lastrowid
    target = dict(conn.execute("SELECT * FROM test_targets WHERE id=?", (target_id,)).fetchone())
    conn.commit()
    conn.close()
    log_audit(g.actor, "api_create_test_target", f"target:{target_id}", title)
    return jsonify(target), 201


@api_bp.route("/test-targets/<int:tid>")
@token_required
def api_test_target_detail(tid):
    conn = get_db()
    row = conn.execute("SELECT * FROM test_targets WHERE id=?", (tid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "target not found"}), 404
    target = dict(row)
    target["cases"] = rows_to_list(conn.execute(
        "SELECT id, title, priority, generation_batch_id, novelty FROM cases "
        "WHERE target_id=? ORDER BY id", (tid,)))
    conn.close()
    return jsonify(target)


@api_bp.route("/test-targets/from-gaps", methods=["POST"])
@token_required
def api_test_targets_from_gaps():
    """按覆盖缺口批量登记目标：零用例模块优先，其次零 UI 用例模块。

    没有这个入口时，AI 看到"没有 open 目标"只能自己拍脑袋选题，结果每轮都挑
    已有用例的接口补一条维度——161 个接口里 125 个永远空白。缺口由
    core.coverage 统一算，与覆盖矩阵、首页质量面板同一份口径。
    """
    data = request.get_json(silent=True) or {}
    include = (data.get("include") or "both").strip().lower()
    if include not in ("api", "ui", "both"):
        return jsonify({"error": "include 只能是 api / ui / both"}), 400
    try:
        limit = max(1, min(int(data.get("limit", 8)), 20))
    except (TypeError, ValueError):
        limit = 8

    conn = get_db()
    pid, err = check_project(conn, data.get("project_id"))
    if err:
        return _close_error(conn, err, 404 if "不存在" in err else 400)

    summary = load_summary(conn, pid)
    gaps = gap_targets(summary, include, limit)
    created, skipped = [], []
    ts = now()
    for gap in gaps:
        fingerprint = target_fingerprint(gap)
        dup = conn.execute(
            "SELECT id, title, status FROM test_targets WHERE project_id=? AND fingerprint=?",
            (pid, fingerprint)).fetchone()
        if dup:
            skipped.append({
                "module": gap["module"], "gap_kind": gap["gap_kind"],
                "duplicate_of": dup["id"], "existing_title": dup["title"],
                "existing_status": dup["status"],
            })
            continue
        cur = conn.execute(
            "INSERT INTO test_targets (project_id, module, title, intent, strategy, priority, "
            "status, interface_id, doc_id, parent_target_id, source_ref, fingerprint, "
            "created_by, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,'open',NULL,NULL,NULL,?,?,?,?,?)",
            (pid, gap["module"], gap["title"][:200], gap["intent"], "breadth", "P1",
             gap["source_ref"], fingerprint, g.actor, ts, ts))
        created.append({"id": cur.lastrowid, "module": gap["module"],
                        "gap_kind": gap["gap_kind"], "title": gap["title"],
                        "source_ref": gap["source_ref"],
                        "priority": "P1"})
    conn.commit()
    totals = summary["totals"]
    gap_counts = {
        "modules_without_cases": len(summary["gaps"]["modules_without_cases"]),
        "modules_without_ui": len(summary["gaps"]["modules_without_ui"]),
    }
    conn.close()
    # log_audit 自开连接，必须等业务事务 commit + close 之后调，否则 database is locked
    for item in created:
        log_audit(g.actor, "api_create_test_target", f"target:{item['id']}",
                  f"from-gaps: {item['title']}")
    return jsonify({
        "created": created,
        "skipped": skipped,
        "gaps": gap_counts,
        "totals": totals,
        "hint": ("缺口已登记，用 POST /api/test-targets/next 逐个领取" if created
                 else "这些缺口都已登记过；用 GET /api/test-targets?status=open 看剩余目标"),
    }), 201 if created else 200


@api_bp.route("/test-targets/next", methods=["POST"])
@token_required
def api_test_target_next():
    data = request.get_json(silent=True) or {}
    strategy, err = normalize_strategy(data.get("strategy"), allow_empty=True)
    if err:
        return jsonify({"error": err}), 400
    batch_id, err = _optional_id(data, "generation_batch_id")
    if err:
        return jsonify({"error": err}), 400
    conn = get_db()
    pid, err = check_project(conn, data.get("project_id"))
    if err:
        return _close_error(conn, err, 404 if "不存在" in err else 400)
    conn.execute("BEGIN IMMEDIATE")
    if batch_id:
        batch = conn.execute("SELECT * FROM generation_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            return _close_error(conn, "generation batch not found", 404, True)
        if batch["project_id"] != pid:
            return _close_error(conn, "生成批次与目标不属于同一项目", 400, True)
        if batch["status"] != "open":
            return _close_error(conn, "生成批次已结束，不能继续领取目标", 409, True)
        if strategy and batch["strategy"] and strategy != batch["strategy"]:
            return _close_error(conn, "strategy 与生成批次不一致", 400, True)
    where, args = ["project_id=?", "status='open'"], [pid]
    if strategy:
        where.append("strategy=?")
        args.append(strategy)
    row = conn.execute(
        "SELECT * FROM test_targets WHERE " + " AND ".join(where) +
        " ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 "
        "WHEN 'P2' THEN 2 ELSE 3 END, attempts, id LIMIT 1", args).fetchone()
    if not row:
        failures, blocked = _hints(conn, pid)
        # 空转是最常见的行为退化点：没有目标时把缺口直接摆出来，
        # 让"下一轮测什么"有具体答案，而不是靠 AI 自由发挥
        hints = gap_targets(load_summary(conn, pid), "both", 5)
        conn.commit()
        conn.close()
        return jsonify({"target": None, "generation_batch_id": batch_id,
                        "message": "当前筛选下没有待生成目标；先用 POST /api/test-targets/from-gaps "
                                   "按覆盖缺口登记目标，再领取",
                        "gap_hints": hints,
                        "failure_hints": failures, "blocked_targets": blocked})
    if not batch_id:
        ts = now()
        cur = conn.execute(
            "INSERT INTO generation_batches (project_id, strategy, created_by, created_at) "
            "VALUES (?,?,?,?)", (pid, strategy or row["strategy"], g.actor, ts))
        batch_id = cur.lastrowid
    ts = now()
    cur = conn.execute(
        "UPDATE test_targets SET status='claimed', claimed_by=?, generation_batch_id=?, "
        "attempts=attempts+1, updated_at=? WHERE id=? AND status='open'",
        (g.actor, batch_id, ts, row["id"]))
    if cur.rowcount != 1:
        return _close_error(conn, "目标已被其他生成会话领取，请重试", 409, True)
    target = dict(conn.execute("SELECT * FROM test_targets WHERE id=?", (row["id"],)).fetchone())
    failures, blocked = _hints(conn, pid)
    conn.commit()
    conn.close()
    log_audit(g.actor, "api_claim_test_target", f"target:{row['id']}", f"batch:{batch_id}")
    return jsonify({"target": target, "generation_batch_id": batch_id,
                    "failure_hints": failures, "blocked_targets": blocked})


@api_bp.route("/test-targets/<int:tid>/feedback", methods=["POST"])
@token_required
def api_test_target_feedback(tid):
    data = request.get_json(force=True) or {}
    outcome = str(data.get("outcome") or "").strip().lower()
    if outcome not in FEEDBACK_OUTCOMES:
        return jsonify({"error": f"outcome 只能是 {'/'.join(FEEDBACK_OUTCOMES)} 之一"}), 400
    conn = get_db()
    row = conn.execute("SELECT * FROM test_targets WHERE id=?", (tid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "target not found"}), 404
    if row["status"] == "covered":
        conn.close()
        return jsonify({"error": "已覆盖目标不能通过反馈重新打开；请登记新的变更驱动目标"}), 409
    if outcome == "reopen" and row["status"] not in ("deferred", "blocked"):
        conn.close()
        return jsonify({"error": "只有 deferred / blocked 目标需要 reopen"}), 409
    status = {"duplicate": "deferred", "invalid": "open",
              "deferred": "deferred", "reopen": "open"}[outcome]
    feedback = str(data.get("note") or "").strip()[:1000]
    conn.execute(
        "UPDATE test_targets SET status=?, last_result=?, feedback=?, claimed_by='', "
        "generation_batch_id=NULL, covered_at='', updated_at=? WHERE id=?",
        (status, "" if outcome == "reopen" else outcome, feedback, now(), tid))
    target = dict(conn.execute("SELECT * FROM test_targets WHERE id=?", (tid,)).fetchone())
    conn.commit()
    conn.close()
    log_audit(g.actor, "api_test_target_feedback", f"target:{tid}", outcome)
    return jsonify(target)


@api_bp.route("/generation-batches/<int:bid>")
@token_required
def api_generation_batch(bid):
    conn = get_db()
    row = conn.execute("SELECT * FROM generation_batches WHERE id=?", (bid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "generation batch not found"}), 404
    batch = dict(row)
    batch["stats"] = _batch_stats(conn, bid)
    conn.close()
    return jsonify(batch)


@api_bp.route("/generation-batches/<int:bid>/finish", methods=["POST"])
@token_required
def api_generation_batch_finish(bid):
    conn = get_db()
    row = conn.execute("SELECT * FROM generation_batches WHERE id=?", (bid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "generation batch not found"}), 404
    if row["status"] != "open":
        conn.close()
        return jsonify({"error": "生成批次已结束"}), 409
    ts = now()
    released = conn.execute(
        "UPDATE test_targets SET status='open', claimed_by='', generation_batch_id=NULL, "
        "last_result='released', feedback='批次结束时未生成用例，已自动释放', updated_at=? "
        "WHERE generation_batch_id=? AND status='claimed'", (ts, bid)).rowcount
    conn.execute(
        "UPDATE generation_batches SET status='finished', finished_at=? WHERE id=?", (ts, bid))
    stats = _batch_stats(conn, bid)
    conn.commit()
    conn.close()
    log_audit(g.actor, "api_finish_generation_batch", f"generation_batch:{bid}",
              f"cases:{stats['cases']} / released:{released}")
    return jsonify({"id": bid, "status": "finished", "released_targets": released, "stats": stats})
