"""runs 生命周期校验：在数据库副本上跑，不污染真实数据。

覆盖 P1 新增的批次能力：
1) 创建：scope 校验（多键 / 空 / 非数字 / 不存在范围）、可执行与跳过分类
2) 列表 / 详情：summary、executions、with_cases
3) claim：原子认领、二次认领 409、返回 steps_json 对象 / 环境 / 鉴权配置
4) 回填：run_id 校验（不存在 / 跨项目 / 状态不对）
5) finish：summary 汇总（pass/fail/blocked/skipped）、重复收尾 409
6) 项目配置：auth 合法写入、非法被拒、读取原样
7) 执行观测：实时进度、心跳、僵死判定、收尾
8) 轮次类型 kind：缺省 regression、非法值、按类型筛选（API + 网页）

用法（在 ai-test-platform 目录下）：
    python tests/verify_runs.py
"""
import json
import os
import shutil
import sqlite3
import sys
import time

from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_verify_runs.db")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)
for extra in ("-wal", "-shm"):
    p = TEST_DB + extra
    if os.path.exists(p):
        os.remove(p)

import db  # noqa: E402
db.DB_PATH = TEST_DB
import app as platform  # noqa: E402

client = platform.app.test_client()

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


def execute(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    try:
        cur = conn.execute(query, args)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


TOKEN = scalar("SELECT token FROM tokens WHERE revoked=0 ORDER BY id LIMIT 1")
if not TOKEN:
    TOKEN = "atk_verify_runs"
    execute("INSERT INTO tokens (token, name, created_at, revoked) VALUES (?,?,?,0)",
            (TOKEN, "verify", "2026-10-23 00:00:00"))
API = {"X-API-Token": TOKEN}


def api(method, url, payload=None):
    kw = {"headers": API}
    if payload is not None:
        kw["json"] = payload
    resp = getattr(client, method.lower())(url, **kw)
    try:
        body = resp.get_json()
    except Exception:                                  # noqa: BLE001
        body = None
    return resp.status_code, body


STAMP = time.strftime("%Y-%m-%d %H:%M:%S")
PID = scalar("SELECT id FROM projects ORDER BY id LIMIT 1")
OTHER_PID = scalar("SELECT id FROM projects WHERE id<>? ORDER BY id LIMIT 1", (PID,))
if not OTHER_PID:
    OTHER_PID = execute("INSERT INTO projects (name, description, created_at) VALUES (?,?,?)",
                        ("跨项目校验", "", STAMP))


def add_case(pid, title, steps_json=None):
    return execute(
        "INSERT INTO cases (project_id, title, steps, steps_json, expected, priority, "
        "created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (pid, title, "", json.dumps(steps_json, ensure_ascii=False) if steps_json else "",
         "", "P2", "verify", STAMP, STAMP))


GOOD = {"kind": "api", "steps": [{
    "no": 1, "action": "探活", "request": {"method": "GET", "path": "/ping"},
    "expect": "200",
    "checks": [{"src": "status", "op": "eq", "value": 200},
               {"src": "body", "path": "$.ok", "op": "eq", "value": True}]}]}
NO_CHECK = {"kind": "api", "steps": [{
    "no": 1, "action": "探活", "request": {"method": "GET", "path": "/ping"},
    "expect": "200"}]}

C_GOOD = add_case(PID, "P1-可自动执行", GOOD)
C_NOCHECK = add_case(PID, "P1-无断言", NO_CHECK)
C_NOSTEPS = add_case(PID, "P1-无结构化步骤")
C_OTHER = add_case(OTHER_PID, "P1-别的项目的用例", GOOD)

print("== 1. 创建：scope 校验 ==")
code, body = api("POST", "/api/runs", {"project_id": PID,
                                       "scope": {"batch": "x", "module": ["y"]}})
check("两个键被拒", code == 400 and "只接受一个键" in body["error"], body)
code, body = api("POST", "/api/runs", {"project_id": PID, "scope": {}})
check("空 scope 被拒", code == 400, body)
code, body = api("POST", "/api/runs", {"project_id": PID, "scope": {"case_ids": []}})
check("空 case_ids 被拒", code == 400, body)
code, body = api("POST", "/api/runs", {"project_id": PID, "scope": {"case_ids": ["a"]}})
check("case_ids 非数字被拒", code == 400, body)
code, body = api("POST", "/api/runs", {"project_id": PID, "scope": "{不是json"})
check("scope 非法 JSON 被拒", code == 400 and "合法 JSON" in body["error"], body)
code, body = api("POST", "/api/runs", {"scope": {"case_ids": [C_GOOD]}})
check("缺 project_id 被拒", code == 400, body)
code, body = api("POST", "/api/runs", {"project_id": 99999, "scope": {"case_ids": [C_GOOD]}})
check("项目不存在 404", code == 404, body)
code, body = api("POST", "/api/runs", {"project_id": PID,
                                       "scope": {"batch": "根本不存在的批次"}})
check("范围内没有用例被拒", code == 400 and "没有用例" in body["error"], body)

print("\n== 2. 创建：可执行与跳过分类 ==")
code, run1 = api("POST", "/api/runs", {
    "project_id": PID, "name": "P1 校验轮次", "reason": "验证 runs",
    "scope": {"case_ids": [C_GOOD, C_NOCHECK, C_NOSTEPS]}})
check("创建成功 201", code == 201, run1)
RUN1 = run1["id"]
check("状态 queued", run1["status"] == "queued", run1["status"])
check("范围内 3 条", run1["cases_total"] == 3, run1["cases_total"])
check("可执行 1 条", run1["runnable"] == 1, run1["runnable"])
check("跳过 2 条", len(run1["skipped"]) == 2, run1["skipped"])
check("跳过原因可读", all(s["reason"] for s in run1["skipped"]),
      [s["reason"] for s in run1["skipped"]])
check("无断言的原因写明缺 checks",
      any("checks" in s["reason"] for s in run1["skipped"]),
      [s["reason"] for s in run1["skipped"]])

print("\n== 3. 列表 / 详情 ==")
code, rows = api("GET", f"/api/runs?project_id={PID}")
check("列表 200", code == 200 and isinstance(rows, list))
check("列表含本轮", any(r["id"] == RUN1 for r in rows))
check("列表 scope 是对象", isinstance(rows[0]["scope"], dict), rows[0]["scope"])
code, rows2 = api("GET", f"/api/runs?project_id={PID}&status=queued")
check("按状态过滤", all(r["status"] == "queued" for r in rows2) and rows2)
code, detail = api("GET", f"/api/runs/{RUN1}")
check("详情 200", code == 200, detail)
check("详情 summary.total=3", detail["summary"].get("total") == 3, detail["summary"])
check("详情 executions 为空", detail["executions"] == [], detail["executions"])
code, detail2 = api("GET", f"/api/runs/{RUN1}?with_cases=1")
check("with_cases 给出可执行清单", len(detail2["cases"]) == 1, detail2.get("cases"))
check("with_cases 给出跳过清单", len(detail2["skipped"]) == 2)
code, body = api("GET", "/api/runs/99999")
check("详情不存在 404", code == 404, body)

print("\n== 4. claim 原子认领 ==")
code, claim = api("POST", f"/api/runs/{RUN1}/claim")
check("认领 200", code == 200, claim)
check("只返回可执行用例", len(claim["cases"]) == 1, len(claim["cases"]))
check("steps_json 已解析成对象",
      isinstance(claim["cases"][0]["steps_json"], dict), type(claim["cases"][0]["steps_json"]))
check("带回跳过清单", len(claim["skipped"]) == 2)
check("带回环境 base_url", (claim.get("environment") or {}).get("base_url"), claim.get("environment"))
check("未配 auth 时为 null", claim.get("auth") is None, claim.get("auth"))
check("run 已转 running", claim["run"]["status"] == "running", claim["run"]["status"])
check("库里的 run 也是 running",
      scalar("SELECT status FROM runs WHERE id=?", (RUN1,)) == "running")
code, body = api("POST", f"/api/runs/{RUN1}/claim")
check("二次认领 409", code == 409, body)

print("\n== 5. 回填：run_id 校验 ==")
code, body = api("POST", f"/api/cases/{C_GOOD}/executions",
                 {"run_id": 99999, "step_results": [{"no": 1, "result": "pass"}]})
check("不存在的 run 被拒", code == 400 and "不存在" in body["error"], body)
code, body = api("POST", f"/api/cases/{C_OTHER}/executions",
                 {"run_id": RUN1, "step_results": [{"no": 1, "result": "pass"}]})
check("跨项目回填被拒", code == 400 and "同一项目" in body["error"], body)
code, body = api("POST", "/api/runs", {"project_id": PID, "scope": {"case_ids": [C_GOOD]}})
RUN_QUEUED = body["id"]
code, body = api("POST", f"/api/cases/{C_GOOD}/executions",
                 {"run_id": RUN_QUEUED, "step_results": [{"no": 1, "result": "pass"}]})
check("queued 的 run 不能回填", code == 400 and "只有 running" in body["error"], body)

print("\n== 6. 回填成功与 summary ==")
code, ex = api("POST", f"/api/cases/{C_GOOD}/executions", {
    "run_id": RUN1,
    "step_results": [{"no": 1, "result": "pass", "actual": "200"}],
    "actual_result": "", "evidence": "verify 脚本"})
check("回填 201", code == 201, ex)
check("返回 run_id", ex.get("run_id") == RUN1, ex)
check("库里 execution 挂了 run_id",
      scalar("SELECT run_id FROM executions WHERE id=?", (ex["id"],)) == RUN1)
code, body = api("POST", f"/api/runs/{RUN1}/finish", {"status": "done"})
check("收尾 200", code == 200, body)
check("summary total=3", body["summary"]["total"] == 3, body["summary"])
check("summary pass=1", body["summary"]["pass"] == 1, body["summary"])
check("summary skipped=2", body["summary"]["skipped"] == 2, body["summary"])
check("状态 done", body["status"] == "done")
code, body = api("POST", f"/api/runs/{RUN1}/finish", {"status": "done"})
check("重复收尾 409", code == 409, body)
code, body = api("POST", f"/api/runs/{RUN_QUEUED}/finish", {"status": "wat"})
check("非法收尾状态 400", code == 400, body)
code, body = api("POST", f"/api/cases/{C_GOOD}/executions",
                 {"run_id": RUN1, "step_results": [{"no": 1, "result": "pass"}]})
check("已收尾的 run 不能补写", code == 400 and "只有 running" in body["error"], body)
code, body = api("POST", f"/api/runs/{RUN1}/claim")
check("已收尾的 run 不能认领", code == 409, body)

print("\n== 7. 项目配置 auth ==")
bad_cases = [
    ("非法 type", {"type": "oauth"}),
    ("login 缺 path", {"type": "login", "token_path": "$.data.accessToken"}),
    ("login 缺 token_path", {"type": "login", "path": "/auth/login"}),
    ("path 带域名", {"type": "login", "path": "https://x.com/login",
                   "token_path": "$.t"}),
    ("static 缺 headers", {"type": "static"}),
]
for name, payload in bad_cases:
    code, body = api("PUT", f"/api/projects/{PID}/settings/auth", {"value": payload})
    check(f"auth {name} 被拒 400", code == 400, body)

AUTH = {"type": "login", "method": "POST", "path": "/admin-api/system/auth/login",
        "headers": {"tenant-id": "163"},
        "body": {"username": "{{username}}", "password": "{{password}}", "clientType": "h5"},
        "token_path": "$.data.accessToken"}
code, body = api("PUT", f"/api/projects/{PID}/settings/auth", {"value": AUTH})
check("合法 auth 写入 200", code == 200, body)
check("注入头有缺省值",
      body["value"]["inject"] == {"header": "Authorization", "prefix": "Bearer "},
      body["value"].get("inject"))
code, body = api("GET", f"/api/projects/{PID}/settings")
check("读回 auth", code == 200 and "auth" in body, list(body or {}))
check("读回内容与写入一致",
      body["auth"]["value"]["path"] == AUTH["path"], body["auth"]["value"].get("path"))
code, body = api("PUT", f"/api/projects/{PID}/settings/unknown", {"value": {}})
check("未知配置键被拒 400", code == 400, body)

print("\n== 7b. 项目变量 vars ==")
code, body = api("PUT", f"/api/projects/{PID}/settings/vars", {"value": {"memberToken": "tk-1"}})
check("vars 写入 200", code == 200 and body["value"]["memberToken"] == "tk-1", body)
code, body = api("PUT", f"/api/projects/{PID}/settings/vars", {"value": ["not", "dict"]})
check("vars 非对象被拒 400", code == 400, body)
code, body = api("GET", f"/api/projects/{PID}/settings")
check("vars 可读回", body["vars"]["value"]["memberToken"] == "tk-1", body.get("vars"))

print("\n== 8. claim 带回鉴权配置 ==")
code, body = api("POST", "/api/runs", {"project_id": PID, "scope": {"case_ids": [C_GOOD]}})
RUN_AUTH = body["id"]
code, claim2 = api("POST", f"/api/runs/{RUN_AUTH}/claim")
check("认领 200", code == 200, claim2)
check("auth 已带回", (claim2.get("auth") or {}).get("type") == "login", claim2.get("auth"))
check("auth 带 token_path",
      (claim2.get("auth") or {}).get("token_path") == "$.data.accessToken")
check("claim 同时带回 vars", (claim2.get("vars") or {}).get("memberToken") == "tk-1",
      claim2.get("vars"))

print("\n== 9. 执行观测：进度 / 心跳 / 僵死 / 收尾 ==")
OBS_CASE = add_case(PID, "P1-观测用", GOOD)
code, body = api("POST", "/api/runs", {
    "project_id": PID, "name": "观测轮", "reason": "验证进度与僵死",
    "scope": {"case_ids": [OBS_CASE, C_NOCHECK]}})
RUN_OBS = body["id"]
check("观测轮创建 201", code == 201, body)
code, d = api("GET", f"/api/runs/{RUN_OBS}")
check("初始进度 0/2", d["progress"]["done"] == 0 and d["progress"]["total"] == 2, d["progress"])
check("初始 runner_id 为空", d.get("runner_id") == "", d.get("runner_id"))
check("queued 不算僵死", d["stalled"] is False, d["stalled"])

code, claim = api("POST", f"/api/runs/{RUN_OBS}/claim", {"runner_id": "test-host:1234"})
check("claim 带回 runner_id", claim["run"]["runner_id"] == "test-host:1234",
      claim["run"].get("runner_id"))
check("claim 起心跳", bool(claim["run"]["last_heartbeat_at"]),
      claim["run"].get("last_heartbeat_at"))
check("库里的 runner_id 落了",
      scalar("SELECT runner_id FROM runs WHERE id=?", (RUN_OBS,)) == "test-host:1234")

hb1 = scalar("SELECT last_heartbeat_at FROM runs WHERE id=?", (RUN_OBS,))
time.sleep(1.1)
code, hb = api("POST", f"/api/runs/{RUN_OBS}/heartbeat")
hb2 = scalar("SELECT last_heartbeat_at FROM runs WHERE id=?", (RUN_OBS,))
check("心跳 200", code == 200 and hb["status"] == "running", hb)
check("心跳推进 last_heartbeat_at", hb2 > hb1, (hb1, hb2))

code, ex = api("POST", f"/api/cases/{OBS_CASE}/executions", {
    "run_id": RUN_OBS, "step_results": [{"no": 1, "result": "fail", "actual": "400"}]})
check("观测轮回填 201", code == 201, ex)
hb3 = scalar("SELECT last_heartbeat_at FROM runs WHERE id=?", (RUN_OBS,))
check("回填也刷心跳", hb3 >= hb2, (hb2, hb3))
code, d = api("GET", f"/api/runs/{RUN_OBS}")
check("进度实时到 1/2", d["progress"]["done"] == 1, d["progress"])
check("失败数实时到 1", d["progress"]["fail"] == 1, d["progress"])
check("未跑数 1", d["progress"]["left"] == 1, d["progress"])
check("summary 仍是创建时的终值口径（pass/fail 不随进度变）",
      d["summary"]["pass"] == 0 and d["summary"]["fail"] == 0, d["summary"])
code, rows = api("GET", f"/api/runs?project_id={PID}")
row = next(r for r in rows if r["id"] == RUN_OBS)
check("列表也带 progress", row["progress"]["done"] == 1, row["progress"])
check("列表带 stalled 标记", row["stalled"] is False, row["stalled"])

old = (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
execute("UPDATE runs SET last_heartbeat_at=? WHERE id=?", (old, RUN_OBS))
code, d = api("GET", f"/api/runs/{RUN_OBS}")
check("心跳超 3 分钟 → stalled", d["stalled"] is True, d.get("last_heartbeat_at"))
check("僵死不自动改状态", d["status"] == "running", d["status"])
code, rows = api("GET", f"/api/runs?project_id={PID}&status=stalled")
check("?status=stalled 能筛到", any(r["id"] == RUN_OBS for r in rows), [r["id"] for r in rows])
check("stalled 列表全是 running", all(r["status"] == "running" for r in rows))
code, rows = api("GET", f"/api/runs?project_id={PID}&status=done")
check("普通状态筛选不受影响", all(r["status"] == "done" for r in rows))

code, body = api("POST", f"/api/runs/{RUN_OBS}/cancel", {"note": ""})
check("取消必须给原因", code == 400 and "note" in body["error"], body)
code, body = api("POST", f"/api/runs/{RUN_OBS}/cancel", {"note": "runner 窗口被关掉"})
check("取消成功", code == 200 and body["status"] == "failed", body)
check("取消后 summary 按实际回填现算",
      body["summary"]["fail"] == 1 and body["summary"]["skipped"] == 1,
      body["summary"])
check("取消原因进 cancel_note",
      scalar("SELECT cancel_note FROM runs WHERE id=?", (RUN_OBS,)) == "runner 窗口被关掉")
check("取消后有 finished_at",
      bool(scalar("SELECT finished_at FROM runs WHERE id=?", (RUN_OBS,))))
code, d = api("GET", f"/api/runs/{RUN_OBS}")
check("终态进度读 summary（1 失败 / 1 未跑）",
      d["progress"]["fail"] == 1 and d["progress"]["left"] == 1, d["progress"])
check("终态不再报 stalled", d["stalled"] is False, d["stalled"])
code, body = api("POST", f"/api/runs/{RUN_OBS}/cancel", {"note": "再收一次"})
check("重复取消 409", code == 409, body)
code, body = api("POST", f"/api/runs/{RUN_OBS}/heartbeat")
check("收尾后心跳 409", code == 409, body)
code, body = api("POST", f"/api/runs/{RUN_OBS}/finish", {"status": "done"})
check("收尾后不能再 finish", code == 409, body)
code, body = api("POST", f"/api/cases/{OBS_CASE}/executions",
                 {"run_id": RUN_OBS, "step_results": [{"no": 1, "result": "pass"}]})
check("收尾后不能再回填", code == 400 and "只有 running" in body["error"], body)

print("\n== 10. 网页端运行列表与详情 ==")
with client.session_transaction() as sess:
    sess["user"] = "admin"
code, run_web = api("POST", "/api/runs", {
    "project_id": PID, "name": "网页观测轮", "scope": {"case_ids": [OBS_CASE]}})
RUN_WEB = run_web["id"]
api("POST", f"/api/runs/{RUN_WEB}/claim", {"runner_id": "web-host:9"})
resp = client.get(f"/projects/{PID}?tab=runs")
html = resp.get_data(as_text=True)
check("运行 tab 200", resp.status_code == 200, resp.status_code)
check("tab 里有『运行』入口", "?tab=runs" in html)
check("列表显示 run 名称", "网页观测轮" in html)
check("列表显示运行中徽标", "运行中" in html)
check("列表显示 runner 身份", "web-host:9" in html)
check("列表显示进度 0/1", "0/1" in html)
resp = client.get(f"/projects/{PID}?tab=runs&status=stalled")
check("网页 stalled 筛选 200", resp.status_code == 200, resp.status_code)

resp = client.get(f"/runs/{RUN_WEB}")
html = resp.get_data(as_text=True)
check("run 详情 200", resp.status_code == 200, resp.status_code)
check("详情显示范围", "用例 1 条" in html)
check("详情有收尾按钮", f"/runs/{RUN_WEB}/cancel" in html)
check("详情显示未跑 1", "未跑 1" in html)

resp = client.post(f"/runs/{RUN_WEB}/cancel", data={"note": ""}, follow_redirects=False)
check("网页收尾 302", resp.status_code == 302, resp.status_code)
check("网页收尾落库 failed",
      scalar("SELECT status FROM runs WHERE id=?", (RUN_WEB,)) == "failed")
check("网页收尾默认原因",
      scalar("SELECT cancel_note FROM runs WHERE id=?", (RUN_WEB,)) == "网页人工取消")
code, d = api("GET", f"/api/runs/{RUN_WEB}")
check("收尾后不再是 stalled", d["stalled"] is False, d["stalled"])
resp = client.post(f"/runs/{RUN_WEB}/cancel", data={"note": "x"}, follow_redirects=True)
check("已收尾的再点收尾只提示不报错", resp.status_code == 200, resp.status_code)
check("网页收尾记审计",
      scalar("SELECT COUNT(*) FROM audit WHERE action='run_cancel' AND target=?",
             (f"run:{RUN_WEB}",)) == 1)

print("\n== 11. 轮次类型 kind ==")
code, body = api("POST", "/api/runs", {
    "project_id": PID, "name": "类型-缺省", "scope": {"case_ids": [OBS_CASE]}})
K_DEF = body.get("id")
check("缺省 kind=regression", code == 201 and body.get("kind") == "regression", body)
code, body = api("POST", "/api/runs", {
    "project_id": PID, "name": "类型-自检", "kind": "selfcheck",
    "scope": {"case_ids": [OBS_CASE]}})
K_SELF = body["id"]
check("指定 selfcheck 生效", body.get("kind") == "selfcheck", body)
check("库里 kind 落了",
      scalar("SELECT kind FROM runs WHERE id=?", (K_SELF,)) == "selfcheck")
code, body = api("POST", "/api/runs", {
    "project_id": PID, "name": "类型-大小写", "kind": " Diagnostic ",
    "scope": {"case_ids": [OBS_CASE]}})
check("kind 大小写与空格被归一", body.get("kind") == "diagnostic", body)
code, body = api("POST", "/api/runs", {
    "project_id": PID, "name": "类型-非法", "kind": "smoke",
    "scope": {"case_ids": [OBS_CASE]}})
check("非法 kind 被拒 400", code == 400 and "kind" in body["error"], body)

code, rows = api("GET", f"/api/runs?project_id={PID}&kind=selfcheck")
check("按类型筛选", rows and all(r["kind"] == "selfcheck" for r in rows),
      [r["id"] for r in rows])
check("筛选含刚建的自检轮", any(r["id"] == K_SELF for r in rows))
code, rows = api("GET", f"/api/runs?project_id={PID}&kind=regression")
check("回归筛选不含自检轮", all(r["id"] != K_SELF for r in rows))
code, rows = api("GET", f"/api/runs?project_id={PID}&kind=selfcheck&status=queued")
check("类型与状态可组合",
      all(r["kind"] == "selfcheck" and r["status"] == "queued" for r in rows), len(rows))
code, body = api("GET", f"/api/runs?project_id={PID}&kind=smoke")
check("非法 kind 查询 400", code == 400, body)

resp = client.get(f"/projects/{PID}?tab=runs&kind=selfcheck")
html = resp.get_data(as_text=True)
check("网页按类型筛选 200", resp.status_code == 200, resp.status_code)
check("网页有类型下拉", 'name="kind"' in html)
check("网页只显示自检轮", "类型-自检" in html and "类型-缺省" not in html)
check("网页有类型徽标", "kind-selfcheck" in html)
resp = client.get(f"/runs/{K_SELF}")
check("详情显示类型徽标", "kind-selfcheck" in resp.get_data(as_text=True))
resp = client.get(f"/projects/{PID}?tab=runs&kind=smoke")
check("网页词表外类型当没传", "类型-缺省" in resp.get_data(as_text=True))

print("\n== 12. 网页默认只看回归（口径隔离） ==")
total_runs = scalar("SELECT COUNT(*) FROM runs WHERE project_id=?", (PID,))
reg_runs = scalar("SELECT COUNT(*) FROM runs WHERE project_id=? AND "
                  "COALESCE(NULLIF(kind,''),'regression')='regression'", (PID,))
resp = client.get(f"/projects/{PID}?tab=runs")
html = resp.get_data(as_text=True)
check("默认视图 200", resp.status_code == 200, resp.status_code)
check("默认视图只列回归轮", "类型-缺省" in html and "类型-自检" not in html)
check("默认视图不列诊断轮", "类型-大小写" not in html)
check("tab 徽标是 回归/全部", f"{reg_runs}/{total_runs}" in html, (reg_runs, total_runs))
check("提示自检/诊断不计入", "不计入质量结论" in html)
check("有查看全部入口", "kind=all" in html)

resp = client.get(f"/projects/{PID}?tab=runs&kind=all")
html = resp.get_data(as_text=True)
check("kind=all 列出全部类型",
      all(t in html for t in ("类型-缺省", "类型-自检", "类型-大小写")))
check("kind=all 结果行标全部类型", "全部类型" in html)

resp = client.get(f"/runs/{K_SELF}")
check("自检详情页有质量口径警示",
      "不作为被测对象的质量结论" in resp.get_data(as_text=True))
resp = client.get(f"/runs/{K_DEF}")
check("回归详情页没有该警示",
      "不作为被测对象的质量结论" not in resp.get_data(as_text=True))

print(f"\n{'全部通过' if not fails else '失败 %d 项：%s' % (len(fails), fails)}")
sys.exit(1 if fails else 0)
