"""覆盖缺口口径：接口覆盖 / UI 覆盖 / 按缺口派活。

2026-10-27 改造的验收脚本。改造前 161 个接口里 125 个零用例、22 个模块只有
1 个有 UI 用例，首页四个质量指标却全绿——因为"覆盖"根本不在指标里，UI 用例
也只出现在 unlinked_cases，不参与任何统计。

这个脚本锁四件事：
1. `/api/coverage` 的 totals/ui/gaps 与库里真实数据一致（口径不能飘）；
2. UI 覆盖只认 steps_json 里的 ui 步骤，补 dims 不会让它变大；
3. `/api/test-targets/from-gaps` 按缺口派活且幂等，next 空转时给出缺口线索；
4. 含 UI 用例的 run 创建时就把执行前提说清楚。

用法（在 ai-test-platform 目录下）：
    python tests/verify_coverage_gaps.py
"""
import json
import os
import shutil
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_verify_coverage_gaps.db")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)
for extra in ("-wal", "-shm"):
    p = TEST_DB + extra
    if os.path.exists(p):
        os.remove(p)

import db  # noqa: E402
db.DB_PATH = TEST_DB

import app as platform  # noqa: E402
import core.lists as lists  # noqa: E402

TOKEN = open(os.path.join(BASE, "data", "api-token.txt"), encoding="utf-8").read().strip()
client = platform.app.test_client()
H = {"X-API-Token": TOKEN}
fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail else ''}")
    if not cond:
        fails.append(name)


def sql(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(query, args)]
    finally:
        conn.close()


def scalar(query, args=()):
    rows = sql(query, args)
    return list(rows[0].values())[0] if rows else None


def api(method, path, payload=None, headers=None):
    r = getattr(client, method)(path, headers=headers or H, json=payload)
    return r.status_code, r.get_json(silent=True), r


def is_ui_case(row):
    raw = row.get("steps_json")
    try:
        struct = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return False
    return any(isinstance(s.get("ui"), dict) for s in struct.get("steps") or [])


PID = scalar("SELECT id FROM projects ORDER BY id LIMIT 1")
check("库里有可用项目", PID is not None, f"pid={PID}")

CASE_ROWS = sql("SELECT id, module, steps_json, interface_id FROM cases WHERE project_id=?", (PID,))
ITF_MODULES = {r["module"] for r in sql(
    "SELECT DISTINCT module FROM interfaces WHERE project_id=? AND module!=''", (PID,))}
UI_CASES = [c for c in CASE_ROWS if is_ui_case(c)]

print("== 1. 覆盖矩阵：接口覆盖与 UI 覆盖口径 ==")
code, cov, _ = api("get", f"/api/coverage?project_id={PID}")
check("coverage 可读", code == 200 and isinstance(cov, dict), str(code))
t = cov.get("totals", {})
n_itf = scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=?", (PID,))
check("totals.interfaces 与库一致", t.get("interfaces") == n_itf, f"{t.get('interfaces')}/{n_itf}")
check("覆盖率 = 有用例接口 ÷ 总接口",
      t.get("interface_coverage") == round(t["interfaces_with_cases"] / t["interfaces"], 4)
      if t.get("interfaces") else True,
      f"{t.get('interfaces_with_cases')}/{t.get('interfaces')} = {t.get('interface_coverage')}")
check("零用例接口数 = 总数 - 有用例数",
      t.get("interfaces_without_cases") == t["interfaces"] - t["interfaces_with_cases"])

check("UI 用例数与解析 steps_json 的结果一致",
      t.get("ui_cases") == len(UI_CASES), f"{t.get('ui_cases')} / 解析 {len(UI_CASES)}")
check("UI 模块分母 = 有接口的模块数",
      t.get("ui_modules_total") == len(ITF_MODULES),
      f"{t.get('ui_modules_total')} / 库内 {len(ITF_MODULES)}")
ui_modules = {c["module"] for c in UI_CASES if c.get("module")}
check("UI 模块分子 = 有 UI 用例的模块数",
      t.get("ui_modules_covered") == len(ui_modules), f"{t.get('ui_modules_covered')} / {ui_modules}")
check("UI 覆盖率 = 分子 ÷ 分母",
      t.get("ui_modules_coverage") == round(len(ui_modules) / len(ITF_MODULES), 4)
      if ITF_MODULES else True, str(t.get("ui_modules_coverage")))

print("\n== 2. 模块级明细与 gaps 的对应关系 ==")
modules = cov.get("ui", {}).get("modules", [])
check("ui.modules 覆盖全部接口模块", {m["module"] for m in modules} == ITF_MODULES,
      f"{len(modules)} 个 / 库内 {len(ITF_MODULES)} 个")
check("每个模块的接口数与库一致",
      all(m["interfaces"] == scalar(
          "SELECT COUNT(*) FROM interfaces WHERE project_id=? AND module=?", (PID, m["module"]))
          for m in modules))
check("模块 cases 数与 cases.ui_cases 不矛盾",
      all(m["ui_cases"] <= m["cases"] for m in modules))
gap_no_case = {g["module"] for g in cov["gaps"]["modules_without_cases"]}
gap_no_ui = {g["module"] for g in cov["gaps"]["modules_without_ui"]}
check("modules_without_cases = 模块行里 cases==0 的",
      gap_no_case == {m["module"] for m in modules if m["cases"] == 0}, str(sorted(gap_no_case)))
check("modules_without_ui = 模块行里 ui_cases==0 的",
      gap_no_ui == {m["module"] for m in modules if m["ui_cases"] == 0},
      f"{len(gap_no_ui)} 个")

print("\n== 3. UI 覆盖不认 dims ==")
# 找一条纯接口用例，给它补满维度：UI 覆盖不能因此增加
api_case = next((c for c in CASE_ROWS if not is_ui_case(c)), None)
if api_case and PID:
    before = api("get", f"/api/coverage?project_id={PID}")[1]["totals"]
    api("put", f"/api/cases/{api_case['id']}", {
        "dims": ["正常", "边界", "异常", "鉴权", "越权", "幂等", "并发", "兼容", "性能", "安全"]})
    after = api("get", f"/api/coverage?project_id={PID}")[1]["totals"]
    check("给接口用例补满 10 个维度，ui_cases 不变",
          before["ui_cases"] == after["ui_cases"],
          f"{before['ui_cases']} → {after['ui_cases']}")
    check("补维度也不会改变 UI 模块覆盖率",
          before["ui_modules_coverage"] == after["ui_modules_coverage"])
else:
    print("SKIP  没有可用接口用例")

# 反证：把一条 UI 用例的 ui 步骤去掉，UI 覆盖必须减少。改完立刻恢复，
# 否则后面的 run 警告与质量面板会拿到"库里已经没有 UI 用例"的状态。
if UI_CASES:
    target = UI_CASES[0]
    original = scalar("SELECT steps_json FROM cases WHERE id=?", (target["id"],))
    before = api("get", f"/api/coverage?project_id={PID}")[1]["totals"]
    api("put", f"/api/cases/{target['id']}", {
        "steps_json": {"kind": "api", "steps": [
            {"action": "改成接口步骤", "request": {"method": "GET", "path": "/probe"},
             "expect": "返回 200", "checks": [{"src": "status", "op": "eq", "value": 200}]}]}})
    after = api("get", f"/api/coverage?project_id={PID}")[1]["totals"]
    check("去掉 ui 步骤后 ui_cases 立刻减少",
          after["ui_cases"] == before["ui_cases"] - 1,
          f"{before['ui_cases']} → {after['ui_cases']}")
    check("UI 模块覆盖率同步下降",
          after["ui_modules_coverage"] != before["ui_modules_coverage"],
          f"{before['ui_modules_coverage']} → {after['ui_modules_coverage']}")
    conn = sqlite3.connect(TEST_DB)
    conn.execute("UPDATE cases SET steps_json=? WHERE id=?", (original, target["id"]))
    conn.commit()
    conn.close()
    restored = api("get", f"/api/coverage?project_id={PID}")[1]["totals"]
    check("恢复 ui 步骤后 UI 覆盖回到原值",
          restored["ui_cases"] == before["ui_cases"],
          f"{after['ui_cases']} → {restored['ui_cases']}")
else:
    print("SKIP 库里没有 UI 用例")

print("\n== 4. 响应体积：默认不展开页面明细 ==")
code, brief, _ = api("get", f"/api/coverage?project_id={PID}")
code2, full, _ = api("get", f"/api/coverage?project_id={PID}&ui=full")
check("默认 ui.pages 是计数", code == 200 and isinstance(brief["ui"]["pages"], dict),
      str(type(brief["ui"]["pages"])))
check("?ui=full 才给明细数组", code2 == 200 and isinstance(full["ui"]["pages"], list))
check("ui=full 的页面明细带归属模块与 UI 用例数",
      all("module" in p and "ui_cases" in p for p in full["ui"]["pages"]),
      str(full["ui"]["pages"][:1]))

print("\n== 5. 按模块取时缺口一起收窄 ==")
one = next(iter(ITF_MODULES), None)
if one:
    code, part, _ = api("get", f"/api/coverage?project_id={PID}&module={one}")
    check("单模块 ui.modules 只有该模块",
          {m["module"] for m in part["ui"]["modules"]} == {one}, str(part["ui"]["modules"])[:80])
    check("单模块 gaps 只在该模块范围内判定",
          all(g["module"] == one for g in part["gaps"]["modules_without_cases"]
              + part["gaps"]["modules_without_ui"]),
          str(part["gaps"])[:80])
else:
    print("SKIP 没有模块")

print("\n== 6. 首页质量面板 ==")
with client.session_transaction() as sess:
    sess["user"] = "admin"
home = client.get("/").get_data(as_text=True)
check("首页显示接口覆盖", "接口覆盖" in home)
check("首页显示 UI 覆盖", "UI 覆盖" in home)
check("首页覆盖率与 API 一致",
      f'接口覆盖 {t["interfaces_with_cases"]}/{t["interfaces"]}' in home,
      f'{t["interfaces_with_cases"]}/{t["interfaces"]}')
conn = db.get_db()
q = lists.quality_stats(conn, PID)
conn.close()
# 用当前快照比较：前面改过用例内容，第 1 节的 t 已经不是最新状态
_, current, _ = api("get", f"/api/coverage?project_id={PID}")
check("quality_stats 的接口覆盖率与覆盖矩阵同源",
      q["coverage"]["rate"] == current["totals"]["interface_coverage"],
      f'{q["coverage"]["rate"]} / {current["totals"]["interface_coverage"]}')
check("quality_stats 的 UI 覆盖率与覆盖矩阵同源",
      q["ui"]["rate"] == current["totals"]["ui_modules_coverage"],
      f'{q["ui"]["rate"]} / {current["totals"]["ui_modules_coverage"]}')

print("\n== 7. 按缺口派活（from-gaps）==")
check("初始没有登记过目标", scalar("SELECT COUNT(*) FROM test_targets") == 0)
code, payload, _ = api("post", "/api/test-targets/from-gaps",
                       {"project_id": PID, "limit": 3})
check("首次调用创建目标 201", code == 201 and len(payload["created"]) == 3,
      f"{code} / {len(payload.get('created', []))} 个")
check("创建的目标都是 P1 open",
      scalar("SELECT COUNT(*) FROM test_targets WHERE status='open' AND priority='P1'") == 3)
check("目标锚定了模块并写明缺口",
      all(g.get("module") and "coverage.gaps" in (g.get("source_ref") or "")
          for g in payload["created"]), str(payload["created"][:1]))

code, again, _ = api("post", "/api/test-targets/from-gaps",
                     {"project_id": PID, "limit": 3})
check("重复调用按指纹去重（0 新建 / 3 跳过）",
      code == 200 and not again["created"] and len(again["skipped"]) == 3,
      f"{code} / created={len(again['created'])} skipped={len(again['skipped'])}")
check("跳过项带 duplicate_of", all(s.get("duplicate_of") for s in again["skipped"]))

code, ui_only, _ = api("post", "/api/test-targets/from-gaps",
                       {"project_id": PID, "limit": 5, "include": "ui"})
check("include=ui 只派 UI 缺口",
      code in (200, 201) and all(g["gap_kind"] == "ui" for g in ui_only["created"]),
      str([g["gap_kind"] for g in ui_only["created"]]))

code, body, _ = api("post", "/api/test-targets/from-gaps",
                    {"project_id": PID, "include": "nope"})
check("include 非法 → 400", code == 400, str(body)[:60])
code, body, _ = api("post", "/api/test-targets/from-gaps", {"project_id": 999999})
check("项目不存在 → 404", code == 404, str(code))

print("\n== 8. next：有目标就领，没目标给缺口线索 ==")
code, claimed, _ = api("post", "/api/test-targets/next", {"project_id": PID})
check("next 能领到 from-gaps 登记的目标",
      code == 200 and claimed.get("target") is not None,
      str((claimed.get("target") or {}).get("module")))
check("领到的目标带回 generation_batch_id", bool(claimed.get("generation_batch_id")))

conn = sqlite3.connect(TEST_DB)
conn.execute("DELETE FROM test_targets")
conn.commit()
conn.close()
code, empty, _ = api("post", "/api/test-targets/next", {"project_id": PID})
check("没有目标时返回 gap_hints 而不是空响应",
      code == 200 and empty.get("target") is None and len(empty.get("gap_hints") or []) > 0,
      f"{len(empty.get('gap_hints') or [])} 条")
check("gap_hints 的提示指向 from-gaps",
      "from-gaps" in (empty.get("message") or ""), empty.get("message"))
check("gap_hints 每条都有 module 与 intent",
      all(h.get("module") and h.get("intent") for h in empty["gap_hints"]))

print("\n== 9. 含 UI 用例的 run 要提前说明执行前提 ==")
ui_id = UI_CASES[0]["id"] if UI_CASES else None
api_id = next((c["id"] for c in CASE_ROWS if not is_ui_case(c) and c.get("interface_id")), None)
if ui_id:
    code, run, _ = api("post", "/api/runs",
                       {"project_id": PID, "name": "UI 提示自测",
                        "scope": {"case_ids": [ui_id]}})
    check("含 UI 用例的 run 创建成功", code == 201, str(code))
    check("返回 ui_cases 计数", run.get("ui_cases") == 1, run.get("ui_cases"))
    check("warnings 说明 playwright 与 uiBaseUrl",
          run.get("warnings") and "playwright" in run["warnings"][0]
          and "uiBaseUrl" in run["warnings"][0], str(run.get("warnings"))[:80])
else:
    print("SKIP 没有 UI 用例")

if api_id:
    code, run2, _ = api("post", "/api/runs",
                        {"project_id": PID, "name": "纯接口自测",
                         "scope": {"case_ids": [api_id]}})
    check("纯接口 run 不产生 UI 警告", code == 201 and not run2.get("warnings"),
          str(run2.get("warnings")))
else:
    print("SKIP 没有接口用例")

print("\n" + ("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}"))
os.remove(TEST_DB)
sys.exit(1 if fails else 0)
