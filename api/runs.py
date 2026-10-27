"""执行批次（run）：创建 → 认领 → 心跳 → 回填 → 收尾 / 取消。

设计见 docs/部署与执行引擎设计.md §6。要点：
- 状态机只有 queued → running → done/failed（queued/running 可直接 failed = 取消）
- claim 用一条 UPDATE ... WHERE status='queued' 原子抢占，抢不到回 409
- 创建时就把范围内用例分成「可执行 / 跳过」两类，跑之前就知道能跑几条
- 没有 checks 的用例一律跳过，不拿自然语言 expect 猜判定
- 观测（2026-10-23）：claim 记 runner_id，回填/心跳刷 last_heartbeat_at，
  列表与详情现算 progress + stalled（僵死只读展示，不自动收尾）
"""

import json

from flask import g, jsonify, request

from . import api_bp

from .common import as_id, json_dumps, rows_to_list

from .deps import token_required

from core import lists
from core.coverage import is_ui_case
from core.lists import results_by_run, scoped_cases

from core.notify import notify_run_finished

from core.runs import (RUN_KINDS, TRIGGERS, cancelled_summary, can_transition,
                       classify_cases, describe_scope, is_stalled, normalize_kind,
                       normalize_scope, regression_diff, run_progress, stall_cutoff,
                       summarize)
from db import get_db, log_audit, now

RUN_META = ("id", "project_id", "name", "scope", "trigger", "kind", "reason",
            "status", "baseline_run_id", "summary", "created_by", "created_at",
            "started_at", "finished_at", "runner_id", "last_heartbeat_at",
            "cancel_note")


def _loads(raw, default):
    if raw in (None, ""):
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


def _run_row(row):
    """把 scope / summary 从 JSON 串还原成对象，前端与 runner 都好读。"""
    d = dict(row)
    d["scope"] = _loads(d.get("scope"), {})
    d["summary"] = _loads(d.get("summary"), {})
    return d


def _decorate(conn, rows, now_str):
    """补上实时进度与僵死标记。

    运行中的轮次按 executions 现算，不读 summary 里的 pass/fail——那份只在 finish 时
    才是对的，跑到一半恒为 0（今天 run 11 卡在 8/21 却显示 0/0 就是这个原因）。
    终态则读 summary：那是这一轮的定稿，executions 被清理后仍能还原。
    """
    results = results_by_run(conn, [r["id"] for r in rows])
    for r in rows:
        r["progress"] = run_progress(r, results.get(r["id"], ()))
        r["stalled"] = is_stalled(r, now_str)
    return rows


def _default_environment(conn, project_id):
    row = conn.execute(
        "SELECT id, name, base_url FROM environments WHERE project_id=? ORDER BY id LIMIT 1",
        (project_id,)).fetchone()
    return dict(row) if row else None


def _auth_setting(conn, project_id):
    row = conn.execute(
        "SELECT value FROM project_settings WHERE project_id=? AND key='auth'",
        (project_id,)).fetchone()
    if not row:
        return None
    return _loads(row["value"], None)


def _vars_setting(conn, project_id):
    """项目级变量（token 等易过期值），用例里用 {{vars.xxx}} 引用。"""
    row = conn.execute(
        "SELECT value FROM project_settings WHERE project_id=? AND key='vars'",
        (project_id,)).fetchone()
    if not row:
        return {}
    val = _loads(row["value"], {})
    return val if isinstance(val, dict) else {}


def _notify_setting(conn, project_id):
    """运行收尾的 webhook 配置（修复项 12）。没配或配错都当没配——
    通知是锦上添花，不该拦住收尾。"""
    row = conn.execute(
        "SELECT value FROM project_settings WHERE project_id=? AND key='notify'",
        (project_id,)).fetchone()
    if not row:
        return None
    val = _loads(row["value"], None)
    if not isinstance(val, dict) or not val.get("webhook_url"):
        return None
    return val


def _notify_finished(conn, run, status, summary):
    """终态发 webhook。必须在 conn 关闭前读配置（配置在库里），发送本身异步、
    失败只记日志——见 core/notify.py 的边界说明。"""
    setting = _notify_setting(conn, run["project_id"])
    payload_run = {
        "id": run["id"], "project_id": run["project_id"], "name": run["name"],
        "kind": run.get("kind"), "status": status, "summary": summary,
        "finished_at": run.get("finished_at") or now(),
        "baseline_run_id": run.get("baseline_run_id"),
        "cancel_note": run.get("cancel_note"),
    }
    notify_run_finished(setting, payload_run)


@api_bp.route("/runs", methods=["POST"])
@token_required
def api_run_new():
    data = request.get_json(force=True) or {}
    try:
        pid = int(data.get("project_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "project_id 必填且为数字"}), 400
    scope, err = normalize_scope(data.get("scope"))
    if err:
        return jsonify({"error": err}), 400
    trigger = (data.get("trigger") or "ai").strip().lower()
    if trigger not in TRIGGERS:
        return jsonify({"error": f"trigger 只能是 {'/'.join(TRIGGERS)}"}), 400
    kind, err = normalize_kind(data.get("kind"))
    if err:
        return jsonify({"error": err}), 400

    baseline_run_id = None
    if data.get("baseline_run_id") not in (None, ""):
        baseline_run_id = as_id(data.get("baseline_run_id"))
        if baseline_run_id is None:
            return jsonify({"error": "baseline_run_id 必须是数字"}), 400

    conn = get_db()
    project = conn.execute("SELECT id FROM projects WHERE id=?", (pid,)).fetchone()
    if not project:
        conn.close()
        return jsonify({"error": "project not found"}), 404
    if baseline_run_id:
        brow = conn.execute("SELECT id, project_id FROM runs WHERE id=?",
                            (baseline_run_id,)).fetchone()
        if not brow:
            conn.close()
            return jsonify({"error": f"基准轮 {baseline_run_id} 不存在"}), 404
        if brow["project_id"] != pid:
            conn.close()
            return jsonify({"error": "基准轮必须是同一项目的 run"}), 400

    cases = scoped_cases(conn, pid, scope)
    if not cases:
        conn.close()
        return jsonify({"error": "scope 内没有用例，检查范围是否写对"}), 400
    runnable, skipped = classify_cases(cases)
    # UI 用例的执行前提不在平台侧（runner 机器是否有 playwright、uiBaseUrl 能不能打开），
    # 创建时显式说清，避免"写完 UI 用例跑成 skipped"被当成跑了
    ui_count = sum(1 for c in cases if is_ui_case(c.get("steps_json")))

    name = (data.get("name") or "").strip() or describe_scope(scope)
    # 创建阶段只是"待跑"：skipped 记 0，真实跳过数到 finish 时按实际回填算，
    # 否则 summary 一生成就显示 skipped=total，看起来像全被跳了。
    summary = {"total": len(cases), "pass": 0, "fail": 0, "blocked": 0, "skipped": 0}
    cur = conn.execute(
        "INSERT INTO runs (project_id, name, scope, trigger, kind, reason, status, "
        "baseline_run_id, summary, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pid, name, json_dumps(scope), trigger, kind, data.get("reason", ""),
         "queued", baseline_run_id, json_dumps(summary), g.actor, now()),
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    log_audit(g.actor, "api_run_create", f"run:{run_id}",
              f"{name} / {kind} / {len(cases)} 条，可执行 {len(runnable)}"
              + (f" / 基准轮 {baseline_run_id}" if baseline_run_id else ""))
    warnings = []
    if ui_count:
        warnings.append(
            f"本次含 {ui_count} 条 UI 用例：前提是 runner 容器在跑（--profile runner）"
            "且能打开 vars.uiBaseUrl（缺省退回环境 base_url）指向的页面。"
            "runner 镜像基于 playwright 官方镜像，浏览器已内置，不用另装；"
            "跑不了会记 skipped，不能当作通过")
    return jsonify({
        "id": run_id, "status": "queued", "name": name, "kind": kind, "scope": scope,
        "baseline_run_id": baseline_run_id,
        "cases_total": len(cases), "runnable": len(runnable),
        "ui_cases": ui_count, "warnings": warnings,
        "skipped": skipped,
        "hint": ("能跑的直接 POST /api/runs/%d/claim" % run_id) if runnable else
                "这个范围里没有带 checks 的用例，runner 会全部跳过；先用 PUT /api/cases/<id> 补 steps_json.checks",
    }), 201


@api_bp.route("/runs")
@token_required
def api_runs():
    pid = request.args.get("project_id")
    status = request.args.get("status", "").strip()
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
    except ValueError:
        limit = 50
    where, args = ["1=1"], []
    if pid:
        try:
            args.append(int(pid))
        except (TypeError, ValueError):
            return jsonify({"error": "project_id 必须是数字"}), 400
        where.append("project_id=?")
    kind = request.args.get("kind", "").strip().lower()
    if kind:
        if kind not in RUN_KINDS:
            return jsonify({"error": f"kind 只能是 {' / '.join(RUN_KINDS)}"}), 400
        where.append("kind=?")
        args.append(kind)
    if status == "stalled":
        # 派生状态：running 且心跳超时。用与 is_stalled 相同的时间界，SQL 里直接筛，
        # 这样 limit 截断的是"卡住的"而不是"全部的 running"。
        where.append("status='running'")
        where.append("COALESCE(NULLIF(last_heartbeat_at,''), NULLIF(started_at,''), "
                     "created_at) < ?")
        args.append(stall_cutoff(now()))
    elif status:
        where.append("status=?")
        args.append(status)
    conn = get_db()
    rows = rows_to_list(conn.execute(
        f"SELECT {', '.join(RUN_META)} FROM runs WHERE " + " AND ".join(where) +
        " ORDER BY id DESC LIMIT ?", args + [limit]))
    for r in rows:
        r["scope"] = _loads(r.get("scope"), {})
        r["summary"] = _loads(r.get("summary"), {})
    _decorate(conn, rows, now())
    conn.close()
    return jsonify(rows)


@api_bp.route("/runs/<int:rid>")
@token_required
def api_run_detail(rid):
    with_cases = request.args.get("with_cases", "").lower() in ("1", "true", "yes")
    conn = get_db()
    row = conn.execute(
        f"SELECT {', '.join(RUN_META)} FROM runs WHERE id=?", (rid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "run not found"}), 404
    run = _run_row(row)
    run["executions"] = rows_to_list(conn.execute(
        "SELECT id, case_id, result, actual_result, created_at, step_results, evidence "
        "FROM executions WHERE run_id=? ORDER BY id", (rid,)))
    for e in run["executions"]:
        e["step_results"] = _loads(e.get("step_results"), [])
    _decorate(conn, [run], now())
    # 基准轮对比（修复项 11）：与网页 /runs/<id> 共用 core/lists.attach_baseline_diff，
    # AI 读 API 与用户看看板必须同一套答案
    lists.attach_baseline_diff(conn, run, run["executions"])
    if with_cases:
        cases = scoped_cases(conn, run["project_id"], run["scope"])
        runnable, skipped = classify_cases(cases)
        run["cases"] = [{"id": c["id"], "title": c["title"], "module": c["module"]}
                        for c in runnable]
        run["skipped"] = skipped
    conn.close()
    return jsonify(run)


@api_bp.route("/runs/<int:rid>/claim", methods=["POST"])
@token_required
def api_run_claim(rid):
    """runner 原子认领：只有 queued 能被抢走，并发下第二个请求拿 409。

    `runner_id` 由 runner 上报（hostname:pid）——答"这一轮在哪台机器上跑"，
    以后多 runner 并存时也能看出是谁认领的。
    """
    data = request.get_json(silent=True) or {}
    runner_id = str(data.get("runner_id") or "").strip()[:120]
    conn = get_db()
    row = conn.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "run not found"}), 404
    run = _run_row(row)
    if run["status"] != "queued":
        conn.close()
        return jsonify({"error": f"run 当前是 {run['status']}，只有 queued 能认领"}), 409
    started = now()
    cur = conn.execute(
        "UPDATE runs SET status='running', started_at=?, runner_id=?, "
        "last_heartbeat_at=? WHERE id=? AND status='queued'",
        (started, runner_id, started, rid))
    conn.commit()
    if cur.rowcount == 0:                 # 被别的 runner 抢先
        conn.close()
        return jsonify({"error": "run 已被其他 runner 认领"}), 409
    # 返回值要反映认领后的状态，不能回认领前的快照
    run["status"] = "running"
    run["started_at"] = started
    run["runner_id"] = runner_id
    run["last_heartbeat_at"] = started
    cases = scoped_cases(conn, run["project_id"], run["scope"])
    runnable, skipped = classify_cases(cases)
    for c in runnable:
        c["steps_json"] = _loads(c.get("steps_json"), {})
    env = _default_environment(conn, run["project_id"])
    auth = _auth_setting(conn, run["project_id"])
    variables = _vars_setting(conn, run["project_id"])
    conn.close()
    log_audit(g.actor, "api_run_claim", f"run:{rid}",
              f"{len(runnable)} 条可执行 / 跳过 {len(skipped)}")
    return jsonify({
        "run": run,
        "cases": runnable,
        "skipped": skipped,
        "environment": env,
        "auth": auth,
        "vars": variables,
        "token_note": "auth 为空时，runner 只能跑不需要鉴权的用例；用 PUT /api/projects/<id>/settings/auth 配置",
    })


@api_bp.route("/runs/<int:rid>/heartbeat", methods=["POST"])
@token_required
def api_run_heartbeat(rid):
    """runner 报活：认领后、每条（每步）打一次，平台据此判"是不是还活着"。

    不写审计——一轮 21 条就是 21 条日志，会把操作记录刷满。
    """
    conn = get_db()
    row = conn.execute("SELECT id, status FROM runs WHERE id=?", (rid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "run not found"}), 404
    if row["status"] != "running":
        conn.close()
        return jsonify({"error": f"run 当前是 {row['status']}，已不需要心跳",
                        "status": row["status"]}), 409
    ts = now()
    conn.execute("UPDATE runs SET last_heartbeat_at=? WHERE id=?", (ts, rid))
    conn.commit()
    conn.close()
    return jsonify({"id": rid, "status": "running", "last_heartbeat_at": ts})


@api_bp.route("/runs/<int:rid>/cancel", methods=["POST"])
@token_required
def api_run_cancel(rid):
    """收掉一轮：running/queued → failed，落 cancel_note，summary 按已回填的执行现算。

    这是兜底，不是任务管理：僵尸 run 占着 running，没有任何出口就永远改不回来。
    但仍然**不自动收尾**——自动收尾会把"runner 为什么死的"一起埋掉。
    """
    data = request.get_json(silent=True) or {}
    note = str(data.get("note") or "").strip()
    if len(note) < 2:
        return jsonify({"error": "note 必填（写清为什么收掉这一轮）"}), 400
    conn = get_db()
    row = conn.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "run not found"}), 404
    run = _run_row(row)
    if not can_transition(run["status"], "failed"):
        conn.close()
        return jsonify({"error": f"run 当前是 {run['status']}，不能再取消"}), 409
    total = run["summary"].get("total") or 0
    results = [r["result"] for r in conn.execute(
        "SELECT result FROM executions WHERE run_id=?", (rid,))]
    summary = cancelled_summary(total, results, note)
    conn.execute(
        "UPDATE runs SET status='failed', summary=?, cancel_note=?, finished_at=? "
        "WHERE id=?", (json_dumps(summary), note[:500], now(), rid))
    conn.commit()
    _notify_finished(conn, run, "failed", summary)
    conn.close()
    log_audit(g.actor, "api_run_cancel", f"run:{rid}",
              f"{run['status']} → failed / {summary['pass']} pass "
              f"{summary['fail']} fail / {note[:80]}")
    return jsonify({"id": rid, "status": "failed", "summary": summary,
                    "cancel_note": note[:500]})


@api_bp.route("/runs/<int:rid>/finish", methods=["POST"])
@token_required
def api_run_finish(rid):
    """runner 收尾：按 run_id 汇总 executions，落 summary。"""
    data = request.get_json(silent=True) or {}
    target = (data.get("status") or "done").strip().lower()
    if target not in ("done", "failed"):
        return jsonify({"error": "status 只能是 done / failed"}), 400
    conn = get_db()
    row = conn.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "run not found"}), 404
    run = _run_row(row)
    if not can_transition(run["status"], target):
        conn.close()
        return jsonify({"error": f"run 当前是 {run['status']}，不能转为 {target}"}), 409
    total = run["summary"].get("total") or 0
    results = [r["result"] for r in conn.execute(
        "SELECT result FROM executions WHERE run_id=?", (rid,))]
    summary = summarize(total, results)
    if data.get("note"):
        summary["note"] = str(data["note"])[:500]
    conn.execute(
        "UPDATE runs SET status=?, summary=?, finished_at=? WHERE id=?",
        (target, json_dumps(summary), now(), rid))
    conn.commit()
    _notify_finished(conn, run, target, summary)
    conn.close()
    log_audit(g.actor, "api_run_finish", f"run:{rid}",
              f"{target} / pass {summary['pass']} fail {summary['fail']} "
              f"blocked {summary['blocked']} skipped {summary['skipped']}")
    return jsonify({"id": rid, "status": target, "summary": summary})
