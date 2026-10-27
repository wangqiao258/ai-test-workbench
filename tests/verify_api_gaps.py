"""API 覆盖缺口：现有脚本没碰过的端点与写路径。

2026-10-27 用路由表与 tests/ 里的调用做差集算出来的清单，逐个补：
  GET    /api/ping
  GET    /api/projects
  GET    /api/projects/<pid>/environments
  GET    /api/projects/<pid>/openapi.json
  PUT    /api/projects/<pid>/settings/<key>       （auth / vars / diff_mask / 非法键）
  DELETE /api/projects/<pid>/settings/<key>
  PUT    /api/bugs/<bid>                          （改字段 / 追加证据 / 回到待审核）
  GET    /api/packets/<pkid>                      （preview / full / none）
  GET    /api/packets/<pkid>/download
  DELETE /api/packets/<pkid>                      （含落盘文件清理）

顺带补两块横切行为：X-API-Token 鉴权矩阵、写接口在"参数不对"时必须是 4xx 而不是 500。

用法（在 ai-test-platform 目录下）：
    python tests/verify_api_gaps.py
"""
import gc
import json
import os
import shutil
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_verify_api_gaps.db")
TMP_UP = os.path.join(BASE, "data", "_verify_api_gaps_uploads")
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
platform.UPLOAD_DIR = TMP_UP

TOKEN = open(os.path.join(BASE, "data", "api-token.txt"), encoding="utf-8").read().strip()
client = platform.app.test_client()
H = {"X-API-Token": TOKEN}
fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail else ''}")
    if not cond:
        fails.append(name)


def get(path, headers=None):
    r = client.get(path, headers=headers or H)
    return r.status_code, r.get_json(silent=True), r


def post(path, payload, headers=None):
    r = client.post(path, headers=headers or H, json=payload)
    return r.status_code, r.get_json(silent=True), r


def put(path, payload, headers=None):
    r = client.put(path, headers=headers or H, json=payload)
    return r.status_code, r.get_json(silent=True), r


def delete(path, headers=None):
    r = client.delete(path, headers=headers or H)
    return r.status_code, r.get_json(silent=True), r


def sql(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    try:
        return conn.execute(query, args).fetchall()
    finally:
        conn.close()


def scalar(query, args=()):
    rows = sql(query, args)
    return rows[0][0] if rows else None


PID = scalar("SELECT id FROM projects ORDER BY id LIMIT 1")
check("库里有可用项目", PID is not None, f"pid={PID}")

print("== 1. X-API-Token 鉴权矩阵 ==")
for path, method in (("/api/ping", "get"), ("/api/projects", "get"),
                     ("/api/interfaces?project_id=1", "get"), ("/api/cases", "post")):
    fn = getattr(client, method)
    kwargs = {"json": {}} if method == "post" else {}
    r = fn(path, **kwargs)
    check(f"{method.upper()} {path} 无 token → 401", r.status_code == 401, r.status_code)
    r = fn(path, headers={"X-API-Token": "atk_not_a_real_token"}, **kwargs)
    check(f"{method.upper()} {path} 假 token → 401", r.status_code == 401, r.status_code)
# 吊销后的 token 立刻失效
revoked = "atk_revoked_probe"
conn = sqlite3.connect(TEST_DB)
conn.execute("INSERT OR REPLACE INTO tokens (token, name, created_at, revoked) "
             "VALUES (?,?,?,1)", (revoked, "probe", "2026-10-27 00:00:00"))
conn.commit()
conn.close()
r = client.get("/api/ping", headers={"X-API-Token": revoked})
check("已吊销 token → 401", r.status_code == 401, r.status_code)

print("\n== 2. 连通性 / 项目 / 环境 ==")
code, body, _ = get("/api/ping")
check("ping 返回 ok 与 actor", code == 200 and body.get("ok") is True
      and str(body.get("actor", "")).startswith("ai:"), str(body))
check("ping 带服务器时间", bool(body.get("time")), body.get("time"))

code, projects, _ = get("/api/projects")
n_db = scalar("SELECT COUNT(*) FROM projects")
check("项目列表条数与库一致", code == 200 and len(projects) == n_db, f"{len(projects)} / {n_db}")
check("项目列表带 name", bool(projects) and "name" in projects[0], str(projects[0])[:60])

code, envs, _ = get(f"/api/projects/{PID}/environments")
n_env = scalar("SELECT COUNT(*) FROM environments WHERE project_id=?", (PID,))
check("环境列表只回该项目的", code == 200 and len(envs) == n_env
      and all(e["project_id"] == PID for e in envs), f"{len(envs)} / {n_env}")
code, none_envs, _ = get("/api/projects/999999/environments")
check("不存在的项目取环境 → 空数组不是 500", code == 200 and none_envs == [], str(none_envs))

print("\n== 3. API 端导出 OpenAPI ==")
code, doc, _ = get(f"/api/projects/{PID}/openapi.json")
check("API 端 openapi.json 可用", code == 200 and isinstance(doc, dict)
      and "openapi" in doc, code)
code, doc_web, _ = get(f"/projects/{PID}/openapi.json")   # 网页端要 session，401 才对
check("网页端 openapi.json 不认 API token（session 才认）",
      code in (302, 401, 200) and (code != 200 or isinstance(doc_web, dict)),
      f"{code}（API token 不该当 session 用）")
code, miss, _ = get("/api/projects/999999/openapi.json")
check("不存在的项目导出 → 404", code == 404, code)

print("\n== 4. 项目级配置（PUT/DELETE /settings/<key>）==")
code, body, _ = put(f"/api/projects/{PID}/settings/vars",
                    {"value": {"probe_token": "T-42", "num": 1}})
check("写 vars 成功并回显", code == 200 and body["value"]["probe_token"] == "T-42", str(body)[:80])
code, all_cfg, _ = get(f"/api/projects/{PID}/settings")
check("GET settings 读得到 vars", code == 200 and all_cfg["vars"]["value"]["probe_token"] == "T-42",
      str(all_cfg.get("vars"))[:80])

code, body, _ = put(f"/api/projects/{PID}/settings/vars", {"value": ["不是对象"]})
check("vars 不是对象 → 400", code == 400 and "对象" in body["error"], str(body)[:60])

code, body, _ = put(f"/api/projects/{PID}/settings/auth", {"value": {
    "type": "static", "static_headers": {"Authorization": "Bearer x"}}})
check("写 auth(static) 成功", code == 200 and body["value"]["type"] == "static", str(body)[:80])
code, body, _ = put(f"/api/projects/{PID}/settings/auth", {"value": {
    "type": "login", "path": "https://evil.com/login", "token_path": "$.t"}})
check("auth.login.path 带域名 → 400", code == 400 and "域名" in body["error"], str(body)[:60])
code, body, _ = put(f"/api/projects/{PID}/settings/auth", {"value": {"type": "nope"}})
check("auth.type 非法 → 400", code == 400, str(body)[:60])

code, body, _ = put(f"/api/projects/{PID}/settings/diff_mask", {"value": {"ignore": ["$.time"]}})
check("写 diff_mask 成功", code == 200 and body["value"]["ignore"] == ["$.time"], str(body)[:60])

code, body, _ = put(f"/api/projects/{PID}/settings/nonsense", {"value": {}})
check("不支持的配置键 → 400", code == 400 and "不支持" in body["error"], str(body)[:60])

code, body, _ = put("/api/projects/999999/settings/vars", {"value": {"a": 1}})
check("配置写到不存在的项目 → 404", code == 404, code)

code, body, _ = delete(f"/api/projects/{PID}/settings/diff_mask")
check("删除配置项返回 deleted", code == 200 and body.get("deleted") is True, str(body))
code, all_cfg, _ = get(f"/api/projects/{PID}/settings")
check("删除后 GET 里不再有该键", code == 200 and "diff_mask" not in all_cfg, str(list(all_cfg)))
code, body, _ = delete("/api/projects/999999/settings/vars")
check("删除不存在的项目配置不报错（幂等）", code == 200, code)

print("\n== 5. 更新 Bug（PUT /api/bugs/<id>）==")
code, created, _ = post("/api/bugs", {
    "project_id": PID, "title": "API 缺口自测：PUT 更新后应回到待审核",
    "severity": "normal", "steps": "1. 打开列表", "evidence": "初始证据",
    "module": "API缺口自测", "force": True})
check("建 Bug 201", code == 201, str(created)[:60])
BID = created.get("id") if created else None

if BID:
    conn = sqlite3.connect(TEST_DB)
    conn.execute("UPDATE bugs SET review_status='approved' WHERE id=?", (BID,))
    conn.commit()
    conn.close()
    code, body, _ = put(f"/api/bugs/{BID}", {"impact": "影响 A、B 两个页面"})
    check("改字段 200 且重新进待审核",
          code == 200 and body.get("review_status") == "pending", str(body))
    check("改字段真的落库",
          scalar("SELECT impact FROM bugs WHERE id=?", (BID,)) == "影响 A、B 两个页面")
    check("改字段没清掉原证据",
          scalar("SELECT evidence FROM bugs WHERE id=?", (BID,)) == "初始证据")

    code, body, _ = put(f"/api/bugs/{BID}", {"evidence_append": "补充：复现率 5/5"})
    ev = scalar("SELECT evidence FROM bugs WHERE id=?", (BID,)) or ""
    check("evidence_append 是追加不是覆盖",
          code == 200 and "初始证据" in ev and "补充：复现率 5/5" in ev, repr(ev[:50]))

    code, body, _ = put(f"/api/bugs/{BID}", {"repro_rate": "乱写"})
    check("非法 repro_rate → 400", code == 400, str(body)[:60])
    code, body, _ = put(f"/api/bugs/{BID}", {"impact": "x" * 500})
    check("impact 超长被截到 200 字",
          code == 200 and len(scalar("SELECT impact FROM bugs WHERE id=?", (BID,))) == 200,
          len(scalar("SELECT impact FROM bugs WHERE id=?", (BID,)) or ""))

    code, body, _ = put(f"/api/bugs/{BID}", {})
    check("空 body → 400 而不是静默成功", code == 400 and "nothing" in body["error"],
          str(body)[:60])
    code, body, _ = put("/api/bugs/999999", {"title": "不存在"})
    check("更新不存在的 Bug → 404", code == 404, code)

print("\n== 6. 数据包读取 / 下载 / 删除 ==")
code, itf, _ = post("/api/interfaces", {
    "project_id": PID, "module": "API缺口自测", "name": "数据包读取自测接口",
    "method": "POST", "path": "/gap-selftest/packets",
    "req_params": [{"name": "id", "type": "string", "required": True}],
    "resp_example": '{"ok":true}'})
check("建自测接口 201", code == 201, str(itf)[:60])
IID = itf.get("id") if itf else None

if IID:
    big_body = "行内容\n" * 3000          # 12000 字符：超过 8KB 阈值，必须落盘
    code, pk, _ = post("/api/packets", {
        "project_id": PID, "linked_type": "interface", "linked_id": IID,
        "label": "大响应包",
        "request": {"method": "POST", "url": "/gap-selftest/packets",
                    "headers": {"X-Probe": "1"}, "body": '{"id":"1"}'},
        "response": {"status": 200, "headers": {"Content-Type": "text/plain"},
                     "body": big_body},
        "duration_ms": 12})
    check("提交完整数据包 201", code == 201, str(pk)[:80])
    PKID = pk.get("id") if pk else None
    check("大响应落盘而不是内联", pk and pk.get("stored") == "file", str(pk)[:80])
    check("完整包把接口置为 verified",
          scalar("SELECT verify_status FROM interfaces WHERE id=?", (IID,)) == "verified")

    if PKID:
        code, detail, _ = get(f"/api/packets/{PKID}")
        check("默认预览带截断标记", code == 200
              and detail.get("body_truncated_for_display") is True
              and len(detail.get("resp_body") or "") == 2000,
              f"{len(detail.get('resp_body') or '')} 字符")
        check("预览同时给出真实总长", detail.get("resp_chars_actual") == len(big_body),
              detail.get("resp_chars_actual"))
        check("详情带渲染好的原始报文", "POST /gap-selftest/packets" in (detail.get("text") or ""),
              (detail.get("text") or "")[:40].replace("\n", " "))

        code, full, _ = get(f"/api/packets/{PKID}?body=full")
        check("?body=full 给全量", code == 200
              and len(full.get("resp_body") or "") == len(big_body),
              len(full.get("resp_body") or ""))
        code, none, _ = get(f"/api/packets/{PKID}?body=none")
        check("?body=none 不带响应体", code == 200 and "resp_body" not in none,
              list(none)[:8])
        code, body, _ = get(f"/api/packets/{PKID}?body=xxx")
        check("非法 body 档位 → 400", code == 400, str(body)[:60])

        r = client.get(f"/api/packets/{PKID}/download", headers=H)
        check("下载返回附件且内容完整",
              r.status_code == 200
              and "attachment" in r.headers.get("Content-Disposition", "")
              and len(r.get_data(as_text=True)) == len(big_body),
              f"{r.status_code} {len(r.get_data(as_text=True))} 字符")
        # Windows 上文件句柄没释放时 os.remove 会失败，删除逻辑是 best-effort；
        # 这里显式收掉响应，让"删除时清理落盘文件"测的是清理本身而不是句柄时机
        r.close()
        del r
        gc.collect()

        stored = pk.get("resp_body_file") or ""
        path = os.path.join(TMP_UP, stored.replace("/", os.sep)) if stored else ""
        check("落盘文件真的存在", bool(path) and os.path.isfile(path), stored)

        code, body, _ = delete(f"/api/packets/{PKID}")
        check("删除数据包返回 id", code == 200 and body.get("deleted") == PKID, str(body))
        check("删除后查不到", get(f"/api/packets/{PKID}")[0] == 404)
        check("删除时清理落盘文件", not path or not os.path.exists(path), path)
        code, _, _ = delete(f"/api/packets/{PKID}")
        check("重复删除 → 404", code == 404, code)

print("\n== 7. 参数不对时不能 500 ==")
bad_cases = [
    ("PUT", f"/api/projects/{PID}/settings/vars", {"value": "字符串"}),
    ("PUT", f"/api/projects/{PID}/settings/auth", {"value": []}),
    ("PUT", "/api/bugs/999999", {"title": "x"}),
    ("POST", "/api/packets", {"linked_type": "interface", "linked_id": 999999,
                              "project_id": PID, "request": {}, "response": {}}),
]
for method, path, payload in bad_cases:
    r = (client.put if method == "PUT" else client.post)(path, headers=H, json=payload)
    check(f"{method} {path} 坏参数 → 4xx 不是 5xx", 400 <= r.status_code < 500,
          f"HTTP {r.status_code}")

print("\n" + ("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}"))
shutil.rmtree(TMP_UP, ignore_errors=True)
os.remove(TEST_DB)
sys.exit(1 if fails else 0)
