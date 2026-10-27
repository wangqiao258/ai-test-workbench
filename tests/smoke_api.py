"""API 冒烟测试：在数据库副本上跑，不污染真实数据。

用法（在 ai-test-platform 目录下）：
    python tests/smoke_api.py
"""
import json
import os
import shutil
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_smoke.db")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)

import db  # noqa: E402
db.DB_PATH = TEST_DB
import app as platform  # noqa: E402  导入即触发 bootstrap + 迁移（作用于副本）

TOKEN = open(os.path.join(BASE, "data", "api-token.txt"), encoding="utf-8").read().strip()
client = platform.app.test_client()
H = {"X-API-Token": TOKEN}
fails = []


def get(path):
    r = client.get(path, headers=H)
    body = r.get_json()
    size = len(json.dumps(body, ensure_ascii=False)) if body is not None else 0
    return r.status_code, body, size


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not cond:
        fails.append(name)


def db_count(query, args=()):
    """期望值从库里算，避免数据增长后快照数字变成假失败。"""
    conn = sqlite3.connect(TEST_DB)
    try:
        return conn.execute(query, args).fetchone()[0]
    finally:
        conn.close()


print("== 1. 迁移 ==")
conn = db.get_db()
case_cols = [r[1] for r in conn.execute("PRAGMA table_info(cases)")]
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
check("cases 新增列 doc_id/dims/batch",
      all(c in case_cols for c in ("doc_id", "dims", "batch")), str(case_cols[-3:]))
check("用例审核状态已移除（无 status / review_comment）",
      "status" not in case_cols and "review_comment" not in case_cols)
for t in ("docs", "interfaces"):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
    check(f"{t} 审核状态已移除（无 status / review_comment）",
          "status" not in cols and "review_comment" not in cols, str(cols[-4:]))
check("case_interfaces 关联表存在", "case_interfaces" in tables)
check("modules 词表存在", "modules" in tables)
print("   关联表记录数:", conn.execute("SELECT COUNT(*) FROM case_interfaces").fetchone()[0])
print("   模块词表条数:", conn.execute("SELECT COUNT(*) FROM modules").fetchone()[0])
conn.close()

print("\n== 1b. 手册体积（开场不能被参考文件拖大） ==")
code, main_doc, _ = get("/api/guide")
main_chars = main_doc.get("chars", 0) if isinstance(main_doc, dict) else 0
check("开场手册可读", code == 200 and main_chars > 1000, f"{main_chars} 字符")
check("开场手册 < 9k 字符（超了就该拆，不要让它无限长）",
      0 < main_chars < 9000, f"{main_chars} 字符")
code, ref_doc, _ = get("/api/guide?part=reference")
ref_chars = ref_doc.get("chars", 0) if isinstance(ref_doc, dict) else 0
check("参考手册可单独取（接口字典/Bug/错误码）",
      code == 200 and ref_chars > main_chars, f"{ref_chars} 字符")
check("参考手册 < 40k 字符", 0 < ref_chars < 40000, f"{ref_chars} 字符")
code, _, _ = get("/api/guide?part=nope")
check("未知 part 返回 400", code == 400, str(code))

# 规则回退防线（2026-10-27）：覆盖缺口与 UI 用例的入口必须留在手册里。
# 少这两行，AI 又只补接口维度——161 个接口 125 个零用例、22 个模块只有 1 个
# 有 UI 用例时，首页四个质量指标全绿，没有任何东西提示它去测 UI。
main_text = main_doc.get("guide", "") if isinstance(main_doc, dict) else ""
ref_text = ref_doc.get("guide", "") if isinstance(ref_doc, dict) else ""
check("主手册写明覆盖缺口入口（gaps / from-gaps）",
      "gaps" in main_text and "from-gaps" in main_text)
check("主手册把 UI 用例写进必读工作流程", "UI 用例" in main_text)
check("参考手册保留 UI 执行口径（uiBaseUrl）", "uiBaseUrl" in ref_text)
check("参考手册写明覆盖率字段（interface_coverage）", "interface_coverage" in ref_text)

print("\n== 2. 旧参数兼容（文档/接口已免审，status= 静默忽略）==")
code, body, size = get("/api/cases?project_id=1&status=approved")
expect_cases = db_count("SELECT COUNT(*) FROM cases WHERE project_id=1")
check("cases 兼容 status 参数（已无审核状态，仍返回全量）",
      code == 200 and len(body) == expect_cases, f"{len(body)} 条 / 库内 {expect_cases}")
code, body, _ = get("/api/interfaces?project_id=1&status=approved")
expect_n = db_count("SELECT COUNT(*) FROM interfaces WHERE project_id=1")
check("interfaces?status=approved 不再返回空", code == 200 and len(body) == expect_n,
      f"{len(body)} 条 / 库内 {expect_n}")
code, body, _ = get("/api/docs?project_id=1&status=approved")
check("docs?status=approved 正常", code == 200, f"{len(body)} 条")
code, body, _ = get("/api/interfaces?project_id=1&fields=meta")
check("接口清单不再返回 status 字段", code == 200 and all("status" not in x for x in body))
code, oa, _ = get("/api/projects/1/openapi.json")
oa_text = json.dumps(oa, ensure_ascii=False)
check("OpenAPI 不再带【待审核】前缀", code == 200 and "【待审核】" not in oa_text)
check("OpenAPI 保留 x-verify-status（可信度看这个轴）", "x-verify-status" in oa_text
      and "x-review-status" not in oa_text)
# 列表页只有 summary；可信度必须落到 description 首行（导入 Apifox/Swagger 后展开即见）
check("OpenAPI description 首行给可信度",
      "**可信度：" in oa_text)

print("\n== 2b. 接口免审：verify_status 自动维护 ==")
r = client.post("/api/interfaces", headers=H, json={
    "project_id": 1, "module": "自测模块", "name": "自测接口-无证据",
    "method": "GET", "path": "/selftest/probe"})
sel = r.get_json()
sel_id = sel.get("id")
check("无证据新建 → unverified", r.status_code == 201 and sel.get("verify_status") == "unverified",
      str(sel))
r = client.put(f"/api/interfaces/{sel_id}", headers=H, json={"notes": "只改备注"})
check("只改备注不动验证状态", r.status_code == 200 and r.get_json().get("verify_status") == "unverified",
      str(r.get_json()))
r = client.put(f"/api/interfaces/{sel_id}", headers=H, json={"resp_example": '{"code":0}'})
check("改契约字段 → changed", r.status_code == 200 and r.get_json().get("verify_status") == "changed",
      str(r.get_json()))
r = client.put(f"/api/interfaces/{sel_id}", headers=H, json={"evidence": "REQ/RESP 实测 ..."})
put = r.get_json()
check("只补文字证据不再升级为 verified（新规则只认完整数据包）",
      r.status_code == 200 and put.get("verify_status") == "changed", str(put))
r = client.put(f"/api/interfaces/{sel_id}", headers=H, json={
    "packet": {"request": {"method": "GET", "url": "/selftest/probe",
                           "headers": {"tenant-id": "163"}},
               "response": {"status": 200, "headers": {"Content-Type": "application/json"},
                            "body": '{"code":0}'}}})
put = r.get_json()
check("提交完整数据包 → verified 并刷新验证时间",
      r.status_code == 200 and put.get("verify_status") == "verified" and put.get("verified_at"),
      str(put))
r = client.put(f"/api/interfaces/{sel_id}", headers=H, json={"verify_status": "乱写"})
check("非法 verify_status 被拒 400", r.status_code == 400,
      r.get_json().get("error", "")[:40])

print("\n== 3. 字段裁剪 ==")
_, body_full, s_full = get("/api/interfaces?project_id=1")
_, _, s_meta = get("/api/interfaces?project_id=1&fields=meta")
_, _, s_case_full = get("/api/cases?project_id=1")
_, _, s_case_sum = get("/api/cases?project_id=1&fields=summary")
has_evidence = "evidence" in json.dumps(body_full, ensure_ascii=False)
check("接口默认 contract 不含 evidence", not has_evidence, f"{s_full:,} 字符")
# meta 的绝对体积随接口条数线性涨（服务端 244 条时 37 KB），写死 30000 会变成
# "数据一多就红"的假警报——2026-10-27 部署时正是它把 update.sh 挡在第 4 步。
# 判两条：仍是全量的小头 + 每条成本可控，数据长到 1000 条也不用改这里。
n_itf = db_count("SELECT COUNT(*) FROM interfaces WHERE project_id=1")
per_itf = s_meta / max(n_itf, 1)
check("接口 fields=meta 更轻", s_meta < s_full * 0.4 and per_itf < 220,
      f"{s_meta:,} 字符（全量的 {s_meta / s_full:.0%}，{per_itf:.0f} B/条 × {n_itf} 条）")
check("用例 fields=summary 更轻", s_case_sum < s_case_full, f"{s_case_sum:,} vs {s_case_full:,}")
code, one, _ = get("/api/interfaces/3?fields=full")
check("GET /api/interfaces/{id} 可单读", code == 200 and one.get("id") == 3)

print("\n== 4. 分片过滤 ==")
_, body, size = get("/api/interfaces?project_id=1&module=侧边栏-素材&fields=contract")
expect_n = db_count("SELECT COUNT(*) FROM interfaces WHERE project_id=1 AND module='侧边栏-素材'")
check("按 module 取接口", len(body) == expect_n, f"{len(body)} 个 / 库内 {expect_n}，{size:,} 字符")
_, body, _ = get("/api/interfaces?project_id=1&path_prefix=/app-api/video")
expect_n = db_count("SELECT COUNT(*) FROM interfaces WHERE project_id=1 AND path LIKE '/app-api/video%'")
check("按 path_prefix 取接口", len(body) == expect_n, f"{len(body)} 个 / 库内 {expect_n}")
_, body, _ = get("/api/cases?project_id=1&interface_id=49")
expect_n = db_count("SELECT COUNT(*) FROM cases c WHERE c.project_id=1 AND (c.interface_id=49 "
                    "OR c.id IN (SELECT case_id FROM case_interfaces WHERE interface_id=49))")
check("按 interface_id 取用例", len(body) == expect_n, f"{len(body)} 条 / 库内 {expect_n}")
_, body, _ = get("/api/cases?project_id=1&unlinked=1")
expect_n = db_count("SELECT COUNT(*) FROM cases WHERE project_id=1 AND interface_id IS NULL "
                    "AND id NOT IN (SELECT case_id FROM case_interfaces)")
check("取未挂接口的用例（含页面/流程类）", len(body) == expect_n, f"{len(body)} 条 / 库内 {expect_n}")
r = client.get("/api/cases?project_id=1&limit=5", headers=H)
expect_total = str(db_count("SELECT COUNT(*) FROM cases WHERE project_id=1"))
check("分页 + X-Total-Count", len(r.get_json()) == 5 and r.headers.get("X-Total-Count") == expect_total,
      f"total={r.headers.get('X-Total-Count')} / 库内 {expect_total}")

print("\n== 5. 覆盖矩阵 ==")
code, cov, size = get("/api/coverage?project_id=1")
expect_n = db_count("SELECT COUNT(*) FROM interfaces WHERE project_id=1")
check("coverage 全项目可读", code == 200 and cov["totals"]["interfaces"] == expect_n,
      f"{size:,} 字符 / 库内 {expect_n} 接口")
code, cov_m, size_m = get("/api/coverage?project_id=1&module=侧边栏-素材")
expect_n = db_count("SELECT COUNT(*) FROM interfaces WHERE project_id=1 AND module='侧边栏-素材'")
check("coverage 按模块更轻", code == 200 and len(cov_m["interfaces"]) == expect_n,
      f"{size_m:,} 字符 / 库内 {expect_n} 条")
check("coverage 返回缺口维度", bool(cov_m["interfaces"][0]["dims_missing"]))
expect_n = db_count("SELECT COUNT(*) FROM cases WHERE project_id=1 AND interface_id IS NULL "
                    "AND id NOT IN (SELECT case_id FROM case_interfaces)")
check("coverage 带未挂接口用例", len(cov["unlinked_cases"]) == expect_n,
      f"{len(cov['unlinked_cases'])} 条 / 库内 {expect_n}")

print("\n== 6. 写入校验 ==")
code, body, _ = get("/api/modules?project_id=1")
check("模块词表可读且有接口数", code == 200 and any(m["interfaces"] > 0 for m in body),
      f"{len(body)} 个模块")

r = client.post("/api/cases", headers=H, json={
    "project_id": 1, "title": "没有锚点的用例", "steps": "1. x", "expected": "y"})
check("无锚点被拒 400", r.status_code == 400, r.get_json().get("error", "")[:40])

r = client.post("/api/cases", headers=H, json={
    "project_id": 1, "interface_id": 3, "title": "跨租户访问应被拒绝", "dims": ["越权"]})
check("近似重复被拒 409（跨锚点也能抓到）", r.status_code == 409,
      f"duplicate_of={r.get_json().get('duplicate_of')}")

r = client.post("/api/cases", headers=H, json={
    "project_id": 1, "interface_id": 3, "title": "登录接口 tenant-id 缺失时应拒绝",
    "dims": ["异常", "鉴权"], "module": "错填的模块", "steps": "1. 不带 tenant-id 调登录",
    "expected": "返回租户缺失错误，不发 token"})
ok = r.status_code == 201
new_id = r.get_json().get("id") if ok else None
check("正常写入 201 且 module 由接口派生", ok and r.get_json()["module"] == "认证",
      f"module={r.get_json().get('module')} dims={r.get_json().get('dims')}")

r = client.put(f"/api/cases/{new_id}", headers=H, json={"dims": ["异常", "鉴权", "越权"]})
check("PUT 补维度生效", r.status_code == 200 and "越权" in (r.get_json().get("dims") or ""),
      str(r.get_json().get("dims")))

r = client.post("/api/cases", headers=H, json={
    "project_id": 1, "interface_id": 3, "title": "维度非法", "dims": ["随便写的"]})
check("非法维度被拒 400", r.status_code == 400, r.get_json().get("error", "")[:40])

r = client.post("/api/cases", headers=H, json={
    "project_id": 1, "doc_id": 1, "title": "页面类用例挂文档",
    "steps": "1. 打开页面", "expected": "正常渲染"})
check("doc_id 锚点可写入", r.status_code == 201, str(r.get_json())[:60])

print("\n== 7. 一条用例覆盖多个接口 ==")
r = client.post("/api/cases", headers=H, json={
    "project_id": 1, "interface_ids": [12, 13, 107], "interface_id": 12,
    "title": "素材列表接口的 pageSize 上限应统一为 100", "dims": ["边界", "兼容"],
    "steps": "1. 三个列表接口分别传 pageSize=101", "expected": "均返回参数错误，不返回 500"})
multi = r.get_json() if r.status_code == 201 else {}
check("多接口写入 201", r.status_code == 201, f"interface_ids={multi.get('interface_ids')}")
mid = multi.get("id")

_, body, _ = get(f"/api/cases?project_id=1&interface_id=13")
check("按次要接口也能查到该用例", any(c["id"] == mid for c in body), f"{len(body)} 条")
_, body, _ = get(f"/api/cases?project_id=1&interface_id=107")
check("按第三个接口也能查到", any(c["id"] == mid for c in body), f"{len(body)} 条")
_, cov2, _ = get("/api/coverage?project_id=1&module=侧边栏-素材")
itf12 = next(i for i in cov2["interfaces"] if i["id"] == 12)
check("覆盖矩阵里该用例计入主接口", any(c["id"] == mid for c in itf12["cases"]),
      f"itf12 覆盖维度={itf12['dims_covered']}")
_, cov3, _ = get("/api/coverage?project_id=1")
itf13 = next(i for i in cov3["interfaces"] if i["id"] == 13)
check("覆盖矩阵里同一用例也计入次接口", any(c["id"] == mid for c in itf13["cases"]),
      f"itf13 用例数={itf13['n_cases']}")

r = client.put(f"/api/cases/{mid}", headers=H, json={"interface_ids": [12]})
_, links, _ = get(f"/api/cases/{mid}")
check("PUT 可缩回单接口", r.status_code == 200 and links.get("interface_ids") == [12],
      str(links.get("interface_ids")))

r = client.post(f"/api/cases/{mid}/executions", headers=H,
                json={"result": "pass", "actual_result": "三个接口均返回 400",
                      "evidence": "REQ/RESP ..."})
check("免审用例可直接回填执行（不再有 409 审核门）", r.status_code == 201, str(r.get_json()))

print("\n== 8. 结构化步骤 ==")
steps_payload = {
    "project_id": 1, "interface_id": 3, "dims": ["异常"],
    "title": "登录接口结构化步骤示例：缺 tenant-id 时应拒绝",
    "steps_json": {"kind": "api", "steps": [
        {"action": "用错误密码调用登录接口",
         "request": {"method": "POST", "path": "/admin-api/system/auth/login",
                     "headers": {"tenant-id": "163"},
                     "body": {"username": "13800000000", "password": "wrong"}},
         "expect": "code != 0 且不返回 accessToken"},
        {"action": "用正确密码登录", "expect": "返回 code=0 与 accessToken"},
    ]},
}
r = client.post("/api/cases", headers=H, json=steps_payload)
sid = r.get_json().get("id") if r.status_code == 201 else None
check("带 steps_json 写入 201", r.status_code == 201, f"id={sid}")
code, case_detail, _ = get(f"/api/cases/{sid}")
check("steps 文本由结构自动渲染",
      code == 200 and case_detail["steps"].startswith("1. 用错误密码调用登录接口")
      and "-> POST /admin-api/system/auth/login" in case_detail["steps"],
      repr((case_detail.get("steps") or "")[:40]))
check("steps_json 读出来是对象", isinstance(case_detail.get("steps_json"), dict)
      and len(case_detail["steps_json"]["steps"]) == 2)

bad = dict(steps_payload, title="坏路径示例",
           steps_json={"kind": "api", "steps": [
               {"action": "调接口", "request": {"method": "POST", "path": "https://x.com/a"},
                "expect": "ok"}]})
r = client.post("/api/cases", headers=H, json=bad)
check("步骤 path 带域名被拒 400", r.status_code == 400, r.get_json().get("error", "")[:40])

bad = dict(steps_payload, title="缺断言示例",
           steps_json={"kind": "api", "steps": [{"action": "调接口"}]})
r = client.post("/api/cases", headers=H, json=bad)
check("步骤缺 expect 被拒 400", r.status_code == 400, r.get_json().get("error", "")[:40])

bad = dict(steps_payload, title="坏方法示例",
           steps_json={"kind": "api", "steps": [
               {"action": "调接口", "request": {"method": "FETCH", "path": "/a"}, "expect": "ok"}]})
r = client.post("/api/cases", headers=H, json=bad)
check("步骤 method 非法被拒 400", r.status_code == 400, r.get_json().get("error", "")[:40])

r = client.post(f"/api/cases/{sid}/executions", headers=H, json={
    "step_results": [
        {"no": 1, "result": "pass", "actual": "返回 401，未发 token"},
        {"no": 2, "result": "fail", "actual": "正确密码也返回 401"},
    ],
    "evidence": "REQ/RESP ..."})
check("按步回填自动推导 fail", r.status_code == 201 and r.get_json()["result"] == "fail",
      f"{r.get_json().get('result')}")
_, exs, _ = get(f"/api/cases/{sid}/executions")
check("执行记录里步骤结果是数组", bool(exs) and isinstance(exs[0]["step_results"], list)
      and len(exs[0]["step_results"]) == 2, str(exs[0]["step_results"])[:60])

r = client.post(f"/api/cases/{sid}/executions", headers=H, json={
    "result": "pass",
    "step_results": [{"no": 1, "result": "fail", "actual": "挂了"}]})
check("总结果与分步矛盾时拒收 400", r.status_code == 400, r.get_json().get("error", "")[:40])

r = client.post(f"/api/cases/{sid}/executions", headers=H, json={
    "step_results": [{"no": 9, "result": "pass", "actual": "步骤号不存在"}]})
check("分步步骤号越界被拒 400", r.status_code == 400, r.get_json().get("error", "")[:40])

print("\n== 8.5 上传限制（白名单 + 大小上限）==")
import io
import api.upload as upl
TMP_UP = os.path.join(BASE, "data", "_smoke_uploads")
os.makedirs(TMP_UP, exist_ok=True)
upl.UPLOAD_DIR = TMP_UP  # 重定向到临时目录，不碰真实 uploads/

r = client.post("/api/upload", headers=H,
                data={"file": (io.BytesIO(b"MZ evil"), "evil.exe")})
check("可执行文件 .exe 被拒 400", r.status_code == 400, r.get_json().get("error", "")[:40])

r = client.post("/api/upload", headers=H,
                data={"file": (io.BytesIO(b"\x89PNG\r\n\x1a\n fake"), "ok.png")})
check("png 正常上传 201", r.status_code == 201 and r.get_json().get("url", "").startswith("/files/"),
      "" if r.status_code == 201 else r.get_json().get("error", "")[:40])

platform.app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # smoke 用小上限验证 413
r = client.post("/api/upload", headers=H,
                data={"file": (io.BytesIO(b"x" * (2 * 1024 * 1024)), "big.png")})
body = r.get_json(silent=True)
check("超限被 413 且返回 JSON", r.status_code == 413 and body is not None
      and "上限" in body.get("error", ""), f"status={r.status_code}")

shutil.rmtree(TMP_UP, ignore_errors=True)

print("\n== 8.7 输入健壮性与安全边界（2026-10-26 修复，探针复现过 500/XSS/开放重定向）==")
for path, payload in (
        ("/api/bugs", {"project_id": 99999, "title": "不存在的项目"}),
        ("/api/cases", {"project_id": 99999, "title": "不存在的项目", "module": "x"}),
        ("/api/docs", {"project_id": 99999, "title": "不存在的项目", "content": "x" * 300})):
    r = client.post(path, headers=H, json=payload)
    check(f"POST {path} 项目不存在 → 404 不是 500", r.status_code == 404,
          f"HTTP {r.status_code} {(r.get_json(silent=True) or {}).get('error', '')[:40]}")

r = client.post("/api/bugs", headers=H, json={"project_id": 1, "title": "坏外键", "case_id": {"x": 1}})
check("POST /api/bugs case_id 是对象 → 400 不是 500", r.status_code == 400,
      f"HTTP {r.status_code} {(r.get_json(silent=True) or {}).get('error', '')[:40]}")
r = client.get("/api/runs?project_id=abc", headers=H)
check("GET /api/runs?project_id=abc → 400 不是 500", r.status_code == 400,
      f"HTTP {r.status_code}")

md = platform.app.jinja_env.filters["md"]
dirty = ("前文\n\n<script>alert(1)</script>\n\n<img src=x onerror=alert(2)>\n\n"
         "[坏链](javascript:alert(3))\n\n| a | b |\n|---|---|\n| 1 | 2 |")
clean = md(dirty)
check("md 剥掉 script", "<script>" not in clean, clean[:60].replace("\n", " "))
check("md 剥掉 onerror", "onerror" not in clean, "")
check("md 剥掉 javascript: 链接", "javascript:" not in clean, "")
check("md 保留表格与安全标签", "<table>" in clean and "<td>" in clean, "")

check("_safe_next 拒绝外链", platform._safe_next("https://evil.com/x") is None, "")
check("_safe_next 拒绝协议相对地址", platform._safe_next("//evil.com/x") is None, "")
check("_safe_next 放行站内路径", platform._safe_next("/projects/1?tab=bugs") == "/projects/1?tab=bugs", "")

print("\n== 8.8 运行通知（修复项 12）：配置校验 + 收尾真的发 webhook ==")
import core.notify as notify_mod
import threading as _th

_hook_hits, _hook_ev = [], _th.Event()


def _capture(url, payload, timeout=5):
    _hook_hits.append((url, payload))
    _hook_ev.set()
    return True, "HTTP 200"


_orig_post = notify_mod.post_webhook
notify_mod.post_webhook = _capture
try:
    r = client.put("/api/projects/1/settings/notify", headers=H,
                   json={"value": {"webhook_url": "file:///etc/passwd"}})
    check("PUT notify 非法 URL → 400", r.status_code == 400,
          f"HTTP {r.status_code} {(r.get_json(silent=True) or {}).get('error', '')[:40]}")
    r = client.put("/api/projects/1/settings/notify", headers=H,
                   json={"value": {"webhook_url": "http://127.0.0.1:9/hook",
                                   "on": ["failed"], "format": "wecom"}})
    check("PUT notify 合法配置 200", r.status_code == 200, f"HTTP {r.status_code}")

    # cancel（queued → failed）：on=["failed"] 命中，应发出
    r = client.post("/api/runs", headers=H, json={
        "project_id": 1, "scope": {"case_ids": [sid]}, "name": "通知自测轮-取消"})
    cancel_run = r.get_json().get("id")
    client.post(f"/api/runs/{cancel_run}/cancel", headers=H,
                json={"note": "通知自测：取消应触发"})
    got = _hook_ev.wait(3)
    check("cancel 后 webhook 真的发出", got and len(_hook_hits) == 1,
          f"hits={len(_hook_hits)}")
    if _hook_hits:
        _, pl = _hook_hits[0]
        check("发的 URL 是配置里的那个", _hook_hits[0][0] == "http://127.0.0.1:9/hook")
        check("payload 是 wecom 形状", pl.get("msgtype") == "text"
              and "通知自测轮-取消" in pl["text"]["content"])

    # finish(done)：不在 on 里，不应发出
    _hook_hits.clear()
    r = client.post("/api/runs", headers=H, json={
        "project_id": 1, "scope": {"case_ids": [sid]}, "name": "通知自测轮-完成"})
    done_run = r.get_json().get("id")
    client.post(f"/api/runs/{done_run}/claim", headers=H, json={"runner_id": "smoke:1"})
    client.post(f"/api/runs/{done_run}/finish", headers=H, json={"status": "done"})
    import time as _time
    _time.sleep(0.3)                     # 异步线程若误发，这点时间足够落盘
    check("finish(done) 不在 on 里 → 不发", not _hook_hits, f"hits={len(_hook_hits)}")

    # 换成 on=["done"] 再 finish 一条：应发出且 summary 在正文里
    client.put("/api/projects/1/settings/notify", headers=H,
               json={"value": {"webhook_url": "http://127.0.0.1:9/hook",
                               "on": ["done"], "format": "generic"}})
    r = client.post("/api/runs", headers=H, json={
        "project_id": 1, "scope": {"case_ids": [sid]}, "name": "通知自测轮-完成2"})
    done2 = r.get_json().get("id")
    client.post(f"/api/runs/{done2}/claim", headers=H, json={"runner_id": "smoke:1"})
    client.post(f"/api/runs/{done2}/finish", headers=H, json={"status": "done"})
    got2 = _hook_ev.wait(3)
    check("finish(done) 在 on 里 → 发出", got2 and len(_hook_hits) == 1,
          f"hits={len(_hook_hits)}")
    if _hook_hits:
        check("generic 形状带 summary", _hook_hits[0][1].get("event") == "run.finished"
              and _hook_hits[0][1]["run"]["summary"]["total"] >= 1)
finally:
    notify_mod.post_webhook = _orig_post
    client.delete("/api/projects/1/settings/notify", headers=H)

print("\n== 9. 上下文收益（同一任务维度对比）==")
_, _, via_all = get("/api/interfaces?project_id=1&fields=full")
_, _, via_meta = get("/api/interfaces?project_id=1&fields=meta")
_, _, via_mod = get("/api/coverage?project_id=1&module=侧边栏-素材")
_, _, case_sum = get("/api/cases?project_id=1&fields=summary")
print(f"  改前：接口全量 + 用例全量            ≈ {via_all + case_sum:>8,} 字符")
print(f"  改后：一个模块 coverage + 用例索引   ≈ {via_mod + case_sum:>8,} 字符")
print(f"  改后：接口清单 meta + 用例索引       ≈ {via_meta + case_sum:>8,} 字符")

print("\n" + ("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}"))
os.remove(TEST_DB)
sys.exit(1 if fails else 0)
