"""执行结果：直接回填，按步对齐。"""

from flask import g, jsonify, request

from . import api_bp

from .common import json_dumps, rows_to_list

from .deps import token_required

from core.generation import target_execution_state
from core.steps import derive_result, normalize_step_results, parse_step_list, parse_steps

from db import get_db, log_audit, now

@api_bp.route("/cases/<int:cid>/executions", methods=["POST"])
@token_required
def api_execution_new(cid):
    data = request.get_json(force=True)
    conn = get_db()
    case = conn.execute(
        "SELECT id, project_id, steps_json, target_id, intent_fingerprint FROM cases WHERE id=?",
        (cid,)).fetchone()
    if not case:
        conn.close()
        return jsonify({"error": "case not found"}), 404
    # 归到某一轮（P1）：只允许 running 的 run 回填，防止收尾后补写导致 summary 对不上
    run_id = data.get("run_id")
    if run_id is not None:
        try:
            run_id = int(run_id)
        except (TypeError, ValueError):
            conn.close()
            return jsonify({"error": "run_id 必须是数字"}), 400
        run = conn.execute("SELECT id, project_id, status FROM runs WHERE id=?",
                           (run_id,)).fetchone()
        if not run:
            conn.close()
            return jsonify({"error": f"run {run_id} 不存在"}), 400
        if run["project_id"] != case["project_id"]:
            conn.close()
            return jsonify({"error": "run 与该用例不属于同一项目"}), 400
        if run["status"] != "running":
            conn.close()
            return jsonify({"error": f"run 当前是 {run['status']}，只有 running 能回填"}), 400
    else:
        run_id = None
    case_steps = parse_steps(case["steps_json"])
    srs, err = normalize_step_results(data.get("step_results"), case_steps)
    if err:
        conn.close()
        return jsonify({"error": err}), 400
    result = (data.get("result") or "").strip()
    derived = derive_result(srs)
    if not result:
        if not derived:
            conn.close()
            return jsonify({"error": "result 或 step_results 至少给一个（推荐按步回填，系统自动推导总结果）"}), 400
        result = derived
    elif result not in ("pass", "fail", "blocked"):
        conn.close()
        return jsonify({"error": "result must be pass/fail/blocked"}), 400
    elif derived and derived != result:
        conn.close()
        return jsonify({"error": f"result={result} 与分步回填推导出的 {derived} 不一致，请核对 step_results"}), 400
    ts = now()
    cur = conn.execute(
        "INSERT INTO executions (case_id, result, step_results, intent_fingerprint, "
        "actual_result, evidence, executed_by, run_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (cid, result, json_dumps(srs) if srs else "", case["intent_fingerprint"],
         data.get("actual_result", ""), data.get("evidence", ""), g.actor, run_id, ts),
    )
    # 回填本身就是一次心跳：runner 每跑完一条就打点，平台据此判"这一轮还活着"
    if run_id:
        conn.execute("UPDATE runs SET last_heartbeat_at=? WHERE id=?", (ts, run_id))
    target_feedback = None
    if case["target_id"]:
        latest = [r["result"] for r in conn.execute(
            "SELECT (SELECT e.result FROM executions e WHERE e.case_id=c.id "
            "AND e.intent_fingerprint=c.intent_fingerprint ORDER BY e.id DESC LIMIT 1) "
            "result FROM cases c WHERE c.target_id=?", (case["target_id"],))]
        target_status, target_result = target_execution_state(latest)
        feedback = str(data.get("actual_result") or "")[:1000]
        conn.execute(
            "UPDATE test_targets SET status=?, last_result=?, feedback=?, covered_at=?, "
            "updated_at=? WHERE id=?",
            (target_status, target_result, feedback, ts if target_status == "covered" else "",
             ts, case["target_id"]))
        target_feedback = {"id": case["target_id"], "status": target_status,
                           "last_result": target_result}
    conn.commit()
    conn.close()
    log_audit(g.actor, "api_execute_case", f"case:{cid}",
              f"{result}" + (f" / run:{run_id}" if run_id else ""))
    return jsonify({"id": cur.lastrowid, "result": result, "step_results": srs,
                    "run_id": run_id, "target": target_feedback}), 201

@api_bp.route("/cases/<int:cid>/executions")
@token_required
def api_executions(cid):
    conn = get_db()
    rows = rows_to_list(conn.execute(
        "SELECT * FROM executions WHERE case_id=? ORDER BY id DESC", (cid,)))
    conn.close()
    for r in rows:
        r["step_results"] = parse_step_list(r.get("step_results"))
    return jsonify(rows)

