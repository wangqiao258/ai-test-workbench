"""runner 端到端验证：起一个本地平台实例 + 一个假被测服务，真跑一轮 run。

不走 mock：runner 用真实 HTTP 认领、执行、回填；平台用真实 Flask 进程（线程内）。
验证的是"整条链路能不能跑通"，不是规则细节（规则在 test_asserts / verify_runs）。

用法（在 ai-test-platform 目录下，会占用 8898/8899 两个本地端口）：
    python tests/e2e_runner.py
"""
import json
import os
import shutil
import sqlite3
import sys
import threading
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_e2e_runner.db")
TMP_UP = os.path.join(BASE, "data", "_e2e_uploads")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)
for extra in ("-wal", "-shm"):
    p = TEST_DB + extra
    if os.path.exists(p):
        os.remove(p)
shutil.rmtree(TMP_UP, ignore_errors=True)
os.makedirs(TMP_UP, exist_ok=True)

import db  # noqa: E402
db.DB_PATH = TEST_DB
db.UPLOAD_DIR = TMP_UP

import app as platform  # noqa: E402
from flask import Flask, jsonify  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

PLATFORM_PORT, TARGET_PORT = 8898, 8899
fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail else ''}")
    if not cond:
        fails.append(name)


def scalar(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    try:
        row = conn.execute(query, args).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def rows(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(query, args)]
    finally:
        conn.close()


# ---- 假被测服务 -------------------------------------------------
target = Flask("target")


@target.route("/api/ok")
def target_ok():
    return jsonify({"ok": True, "value": 42, "items": [{"id": 1}, {"id": 2}]})


@target.route("/api/with-header")
def target_header():
    from flask import request
    return jsonify({"ok": True, "seen": request.headers.get("X-Case", "")})


@target.route("/api/token")
def target_token():
    return jsonify({"token": "abc123", "expires": 3600})


@target.route("/api/echo-token")
def target_echo_token():
    from flask import request
    return jsonify({"seen": request.args.get("t", "")})


srv_platform = make_server("127.0.0.1", PLATFORM_PORT, platform.app, threaded=True)
srv_target = make_server("127.0.0.1", TARGET_PORT, target, threaded=True)
for srv in (srv_platform, srv_target):
    threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.4)

import requests  # noqa: E402

PID = scalar("SELECT id FROM projects ORDER BY id LIMIT 1")
TOKEN = scalar("SELECT token FROM tokens WHERE revoked=0 ORDER BY id LIMIT 1")
if not TOKEN:
    TOKEN = "atk_e2e_runner"
    conn = sqlite3.connect(TEST_DB)
    conn.execute("INSERT INTO tokens (token, name, created_at, revoked) VALUES (?,?,?,0)",
                 (TOKEN, "e2e", "2026-10-23 00:00:00"))
    conn.commit()
    conn.close()
API = {"X-API-Token": TOKEN}
BASE_URL = f"http://127.0.0.1:{PLATFORM_PORT}"

conn = sqlite3.connect(TEST_DB)
conn.execute("UPDATE environments SET base_url=? WHERE project_id=?",
             (f"http://127.0.0.1:{TARGET_PORT}", PID))
conn.execute("INSERT OR REPLACE INTO project_settings (project_id, key, value, updated_by, updated_at) "
             "VALUES (?, 'vars', ?, 'e2e', ?)",
             (PID, json.dumps({"probe": "V-1"}), "2026-10-23 00:00:00"))
conn.commit()
conn.close()

STAMP = time.strftime("%Y-%m-%d %H:%M:%S")


def add_case(title, steps_json):
    conn = sqlite3.connect(TEST_DB)
    cur = conn.execute(
        "INSERT INTO cases (project_id, title, steps, steps_json, expected, priority, "
        "created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (PID, title, "", json.dumps(steps_json, ensure_ascii=False), "", "P2",
         "e2e", STAMP, STAMP))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def steps(*items):
    return {"kind": "api", "steps": [
        {"no": i, "action": a, "request": r, "expect": e, "checks": c}
        for i, (a, r, e, c) in enumerate(items, 1)]}


C_PASS = add_case("E2E-应当通过", steps(
    ("调 /api/ok", {"method": "GET", "path": "/api/ok"}, "200 且 ok=true",
     [{"src": "status", "op": "eq", "value": 200},
      {"src": "body", "path": "$.ok", "op": "eq", "value": True},
      {"src": "body", "path": "$.items[1].id", "op": "eq", "value": 2},
      {"src": "duration_ms", "op": "lt", "value": 3000}])))
C_FAIL = add_case("E2E-应当失败", steps(
    ("调 /api/ok", {"method": "GET", "path": "/api/ok"}, "value 应为 999",
     [{"src": "body", "path": "$.value", "op": "eq", "value": 999}])))
C_HEADER = add_case("E2E-步骤自定义请求头", steps(
    ("带 X-Case 调接口", {"method": "GET", "path": "/api/with-header",
                     "headers": {"X-Case": "hello"}}, "回显 hello",
     [{"src": "body", "path": "$.seen", "op": "eq", "value": "hello"}])))
# 第 2 步用第 1 步响应里的 token —— 回归集里"登录→用 token"的典型形态
C_CHAIN = add_case("E2E-多步取值", steps(
    ("先取 token", {"method": "GET", "path": "/api/token"}, "返回 token",
     [{"src": "body", "path": "$.token", "op": "present"}]),
    ("用上一步的 token 调接口",
     {"method": "GET", "path": "/api/echo-token",
      "query": {"t": "{{steps.1.body.token}}"}},
     "回显 abc123",
     [{"src": "body", "path": "$.seen", "op": "eq", "value": "abc123"}])))
# 项目级变量：token 这类会过期的东西只存一处
C_VARS = add_case("E2E-项目变量", steps(
    ("用项目变量做参数", {"method": "GET", "path": "/api/echo-token",
                    "query": {"t": "{{vars.probe}}"}}, "回显 V-1",
     [{"src": "body", "path": "$.seen", "op": "eq", "value": "V-1"}])))

print("== 建 run ==")
resp = requests.post(f"{BASE_URL}/api/runs", headers=API, timeout=10, json={
    "project_id": PID, "name": "E2E 跑一轮", "reason": "端到端验证 runner",
    "scope": {"case_ids": [C_PASS, C_FAIL, C_HEADER, C_CHAIN, C_VARS]}})
run = resp.json()
check("创建 201", resp.status_code == 201, run)
check("5 条都可执行", run["runnable"] == 5, run.get("runnable"))
RUN_ID = run["id"]

print("\n== 跑 runner（RUN_ONCE=1）==")
os.environ.update({
    "PLATFORM_URL": BASE_URL,
    "API_TOKEN": TOKEN,
    "RUN_ONCE": "1",
    "POLL_SECONDS": "0.2",
    "PROJECT_ID": str(PID),
})
from runner.__main__ import main as runner_main  # noqa: E402

runner_main()

print("\n== 结果校验 ==")
detail = requests.get(f"{BASE_URL}/api/runs/{RUN_ID}", headers=API, timeout=10).json()
check("run 已收尾", detail["status"] == "done", detail["status"])
check("有 started_at", bool(detail["started_at"]), detail["started_at"])
check("有 finished_at", bool(detail["finished_at"]), detail["finished_at"])
summary = detail["summary"]
check("summary total=5", summary.get("total") == 5, summary)
check("summary pass=4", summary.get("pass") == 4, summary)
check("summary fail=1", summary.get("fail") == 1, summary)
check("summary skipped=0", summary.get("skipped") == 0, summary)

execs = detail["executions"]
check("产出 5 条执行记录", len(execs) == 5, len(execs))
by_case = {e["case_id"]: e for e in execs}
check("通过用例结果 pass", by_case[C_PASS]["result"] == "pass", by_case[C_PASS]["result"])
check("失败用例结果 fail", by_case[C_FAIL]["result"] == "fail", by_case[C_FAIL]["result"])
check("失败原因写明实际值", "999" in (by_case[C_FAIL].get("actual_result") or ""),
      by_case[C_FAIL].get("actual_result"))
check("自定义请求头生效", by_case[C_HEADER]["result"] == "pass",
      by_case[C_HEADER]["result"])
check("分步结果已落库", len(by_case[C_PASS]["step_results"]) == 1,
      by_case[C_PASS]["step_results"])
check("跨步骤取值生效", by_case[C_CHAIN]["result"] == "pass",
      by_case[C_CHAIN].get("actual_result"))
check("项目变量替换生效", by_case[C_VARS]["result"] == "pass",
      by_case[C_VARS].get("actual_result"))
check("链式用例两步都通过",
      [s["result"] for s in by_case[C_CHAIN]["step_results"]] == ["pass", "pass"],
      by_case[C_CHAIN]["step_results"])

print("\n== 数据包 ==")
packets = rows("SELECT * FROM packets WHERE linked_type='execution' ORDER BY id")
check("每步一条数据包", len(packets) == 6, len(packets))
check("数据包完整度 full", all(p["completeness"] == "full" for p in packets),
      [p["completeness"] for p in packets])
check("数据包挂了 execution id", all(p["linked_id"] for p in packets))
check("请求地址记录正确",
      all(f":{TARGET_PORT}/api/" in (p["req_url"] or "") for p in packets),
      [p["req_url"] for p in packets])
check("响应状态码记录", all(p["resp_status"] == 200 for p in packets),
      [p["resp_status"] for p in packets])
check("响应体含业务字段",
      any('"value"' in (p["resp_body"] or "") and "42" in (p["resp_body"] or "")
          for p in packets),
      (packets[0]["resp_body"] or "")[:60])

print("\n== 收尾后不可再认领 ==")
resp = requests.post(f"{BASE_URL}/api/runs/{RUN_ID}/claim", headers=API, timeout=10)
check("已完成 run 认领 409", resp.status_code == 409, resp.status_code)

for srv in (srv_platform, srv_target):
    srv.shutdown()

print(f"\n{'全部通过' if not fails else '失败 %d 项：%s' % (len(fails), fails)}")
sys.exit(1 if fails else 0)
