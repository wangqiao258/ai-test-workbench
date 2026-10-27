"""AI 持续生成闭环：独立空库验证目标、查重、批次与执行反馈。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
TEST_DB = os.path.join(BASE, "data", "_generation.db")
for suffix in ("", "-wal", "-shm"):
    if os.path.exists(TEST_DB + suffix):
        os.remove(TEST_DB + suffix)

import db  # noqa: E402
db.DB_PATH = TEST_DB
db.init_db()
import app as platform  # noqa: E402

conn = db.get_db()
conn.execute("INSERT INTO projects (name, created_at) VALUES ('生成闭环测试', '2026-10-26')")
PID = conn.execute("SELECT MAX(id) FROM projects").fetchone()[0]
conn.execute(
    "INSERT INTO interfaces (project_id, module, name, method, path, created_at, updated_at) "
    "VALUES (?, '认证', '登录', 'POST', '/login', '2026-10-26', '2026-10-26')", (PID,))
IID = conn.execute("SELECT MAX(id) FROM interfaces").fetchone()[0]
conn.execute("INSERT INTO tokens (token, name, created_at) VALUES ('generation-test', 'test', '2026-10-26')")
conn.commit()
conn.close()

client = platform.app.test_client()
H = {"X-API-Token": "generation-test"}
fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not cond:
        fails.append(name)


def body(response):
    return response.get_json() or {}


def make_target(title, intent, strategy, source_ref, parent=None):
    payload = {"project_id": PID, "interface_id": IID, "title": title, "intent": intent,
               "strategy": strategy, "source_ref": source_ref, "priority": "P1"}
    if parent:
        payload["parent_target_id"] = parent
    return client.post("/api/test-targets", json=payload, headers=H)


def steps(value):
    return {"kind": "api", "steps": [{
        "action": "提交测试输入",
        "request": {"method": "POST", "path": "/login", "body": {"value": value}},
        "expect": "响应符合当前测试目标",
        "checks": [{"src": "status", "op": "eq", "value": 200}],
    }]}


def make_case(target_id, batch_id, title, value, dims=None, **extra):
    payload = {
        "project_id": PID, "target_id": target_id, "generation_batch_id": batch_id,
        "title": title, "novelty": f"验证输入 {value} 对应的新风险",
        "steps_json": steps(value), "expected": "响应符合目标",
    }
    if dims:
        payload["dims"] = dims
    payload.update(extra)
    return client.post("/api/cases", json=payload, headers=H)


r = make_target("错误密码拒绝", "验证错误密码不会签发登录令牌", "interface_depth", "body.password")
t1 = body(r).get("id")
check("登记测试目标", r.status_code == 201 and body(r).get("status") == "open")
check("目标生成持久化指纹", len(body(r).get("fingerprint", "")) == 64)
r = make_target("换个标题", "验证错误密码不会签发登录令牌", "interface_depth", "body.password")
check("相同测试意图目标被查重", r.status_code == 409 and body(r).get("duplicate_of") == t1)
r = make_target("缺失密码", "验证缺失密码时返回参数错误", "breadth", "body.password.required")
t2 = body(r).get("id")
check("不同测试意图可登记", r.status_code == 201 and bool(t2))

r = client.post("/api/test-targets/next", json={"project_id": PID, "strategy": "interface_depth"}, headers=H)
b1 = body(r).get("generation_batch_id")
check("领取最高优先级目标", body(r).get("target", {}).get("id") == t1 and bool(b1))
check("领取后记录次数和身份", body(r).get("target", {}).get("attempts") == 1
      and body(r).get("target", {}).get("status") == "claimed")
r = client.post("/api/test-targets/next", json={
    "project_id": PID, "strategy": "interface_depth", "generation_batch_id": b1}, headers=H)
check("同一目标不能被重复领取", r.status_code == 200 and body(r).get("target") is None)

r = client.post("/api/cases", json={
    "project_id": PID, "target_id": t1, "generation_batch_id": b1,
    "title": "没有新增说明", "steps_json": steps("x")}, headers=H)
check("目标用例必须说明新增覆盖", r.status_code == 400)
r = make_case(t1, b1, "错误密码不签发令牌", "a", dims=["异常"])
c1 = body(r).get("id")
check("生成用例关联目标和批次", r.status_code == 201 and body(r).get("generation_batch_id") == b1)
check("生成策略来自目标", body(r).get("generation_strategy") == "interface_depth")
r = client.get(f"/api/test-targets/{t1}", headers=H)
check("提交用例后目标为已生成", body(r).get("status") == "generated")
r = make_case(t1, b1, "完全不同的标题但行为相同", "a")
check("换标题不能绕过测试行为查重", r.status_code == 409
      and body(r).get("duplicate_kind") == "intent" and body(r).get("duplicate_of") == c1)
check("409 带出已有用例覆盖的维度", body(r).get("existing_dims") == ["异常"],
      str(body(r).get("existing_dims")))
r = make_case(t1, b1, "另一种输入边界", "b")
c2 = body(r).get("id")
check("不同测试输入可生成变体", r.status_code == 201 and c2 != c1)

r = client.post(f"/api/cases/{c1}/executions", json={"result": "pass"}, headers=H)
check("仍有未执行变体时不提前覆盖", body(r).get("target", {}).get("status") == "generated")
r = client.post(f"/api/cases/{c2}/executions", json={"result": "blocked"}, headers=H)
check("阻塞结果回写目标", body(r).get("target", {}).get("status") == "blocked")
r = client.post("/api/test-targets/next", json={"project_id": PID}, headers=H)
b2 = body(r).get("generation_batch_id")
check("领取时返回阻塞线索", any(t["id"] == t1 for t in body(r).get("blocked_targets", [])))
check("自动领取下一个待生成目标", body(r).get("target", {}).get("id") == t2)
r = client.post(f"/api/cases/{c2}/executions", json={"result": "fail", "actual_result": "边界仍放行"}, headers=H)
check("失败不会标记覆盖", body(r).get("target", {}).get("status") == "generated"
      and body(r).get("target", {}).get("last_result") == "fail")
r = make_case(t2, b2, "复用已有行为的另一目标", "a")
check("跨目标也拦截相同测试行为", r.status_code == 409 and body(r).get("duplicate_kind") == "intent")
r = client.post(f"/api/test-targets/{t2}/feedback", json={"outcome": "duplicate", "note": "已有同行为用例"}, headers=H)
check("重复反馈暂缓目标", body(r).get("status") == "deferred"
      and body(r).get("last_result") == "duplicate")
r = client.post(f"/api/generation-batches/{b2}/finish", headers=H)
check("空生成批次可收尾", body(r).get("status") == "finished"
      and body(r).get("stats", {}).get("cases") == 0)

r = make_target("失败后的重复提交探索", "验证同一错误输入重复提交不会产生额外状态", "failure_driven",
                "execution:duplicate", t1)
t3 = body(r).get("id")
check("失败目标可派生子目标", r.status_code == 201 and body(r).get("parent_target_id") == t1)
r = client.post("/api/test-targets/next", json={"project_id": PID, "strategy": "failure_driven"}, headers=H)
b3 = body(r).get("generation_batch_id")
check("失败线索随下一次领取返回", any(t["id"] == t1 for t in body(r).get("failure_hints", [])))
check("子目标可被领取", body(r).get("target", {}).get("id") == t3)
r = make_case(t3, b3, "重复提交状态检查", "c")
c3 = body(r).get("id")
r = client.post(f"/api/cases/{c3}/executions", json={"result": "pass"}, headers=H)
check("子目标全部通过后覆盖", body(r).get("target", {}).get("status") == "covered")
r = client.post(f"/api/generation-batches/{b3}/finish", headers=H)
check("批次统计生成和执行结果", body(r).get("stats", {}).get("cases") == 1
      and body(r).get("stats", {}).get("results", {}).get("pass") == 1)

client.post(f"/api/cases/{c1}/executions", json={"result": "pass"}, headers=H)
r = client.post(f"/api/cases/{c2}/executions", json={"result": "pass"}, headers=H)
check("原目标所有变体通过后覆盖", body(r).get("target", {}).get("status") == "covered")
r = client.put(f"/api/cases/{c2}", json={"preconditions": "新增一个前置数据状态"}, headers=H)
check("修改测试行为保留新指纹", r.status_code == 200 and body(r).get("intent_fingerprint"))
r = client.get(f"/api/test-targets/{t1}", headers=H)
check("修改目标用例后要求重新验证", body(r).get("status") == "generated" and not body(r).get("covered_at"))
r = client.post(f"/api/cases/{c1}/executions", json={"result": "pass"}, headers=H)
check("其他用例的旧 pass 不能覆盖已修改变体", body(r).get("target", {}).get("status") == "generated")
r = client.post(f"/api/cases/{c2}/executions", json={"result": "pass"}, headers=H)
check("修改后的用例重新通过才恢复覆盖", body(r).get("target", {}).get("status") == "covered")

r = make_target("变更后的新错误码", "验证新增错误码被正确映射", "change_driven", "error_codes.new")
t4 = body(r).get("id")
r = client.post("/api/test-targets/next", json={"project_id": PID, "strategy": "change_driven"}, headers=H)
b4 = body(r).get("generation_batch_id")
check("变更驱动目标可领取", body(r).get("target", {}).get("id") == t4)
r = client.post(f"/api/generation-batches/{b4}/finish", headers=H)
check("批次结束释放未生成目标", body(r).get("released_targets") == 1)
r = client.get(f"/api/test-targets/{t4}", headers=H)
check("释放后目标可再次领取", body(r).get("status") == "open"
      and body(r).get("last_result") == "released")

r = client.post("/api/cases", json={
    "project_id": PID, "interface_id": IID, "title": "旧方式独立用例",
    "steps_json": steps("legacy")}, headers=H)
check("不关联目标的旧用例接口保持兼容", r.status_code == 201 and body(r).get("target_id") is None)
r = client.get(f"/api/cases?project_id={PID}&generation_batch_id={b3}&fields=summary", headers=H)
check("按生成批次筛选用例", r.status_code == 200 and len(body(r)) == 1
      and body(r)[0].get("id") == c3)

# force 是唯一能跳过查重的口子，必须留下"谁放过了哪条、为什么"。
# 放在最后、且不挂 target/批次（目标已 covered、批次已结束），只复现 c1 的测试行为。
r = client.post("/api/cases", json={
    "project_id": PID, "interface_id": IID,
    "title": "强制放行的重复行为", "novelty": "验证 force 审计留痕",
    "steps_json": steps("a"), "expected": "响应符合目标",
    "force": True, "force_reason": "验证 force 审计留痕"}, headers=H)
forced_id = body(r).get("id")
check("force 可放行重复行为", r.status_code == 201 and bool(forced_id), body(r).get("error", ""))
aconn = db.get_db()
audit = aconn.execute(
    "SELECT action, detail FROM audit WHERE target=? ORDER BY id DESC LIMIT 1",
    (f"case:{forced_id}",)).fetchone()
aconn.close()
check("force 写入独立审计并带理由",
      audit is not None and audit["action"] == "api_create_case_force"
      and "验证 force 审计留痕" in audit["detail"] and f"放过了 case:{c1}" in audit["detail"],
      audit["detail"] if audit else "无审计记录")

for suffix in ("", "-wal", "-shm"):
    if os.path.exists(TEST_DB + suffix):
        os.remove(TEST_DB + suffix)
print()
if fails:
    print(f"失败 {len(fails)} 项：" + "；".join(fails))
    sys.exit(1)
print("全部通过")
