"""数据包证据的校验：core 纯函数 + API + 页面 + 存量保护。

起因（2026-10-22）：页面标题写着「验证证据（真实数据包）」，实际 161 条接口里
只有 22% 含请求行+状态码+响应体，最短的一条是 10 个字符 `GET -> 200`，
却照样是 verified。本测试盯住三件事：

1. 10 个字符的摘要不能再冒充"已验证"（回归本次 bug）
2. 大响应落盘后**一个字符都不能少**（旧数据里已有 20000 字符被切在半个 JSON 中间）
3. 存量 161 条的状态一个都不许变（用户选的是"存量不动，只管新增"）

用法（在 ai-test-platform 目录下）：
    python tests/test_packets.py
"""
import json
import os
import shutil
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_test_packets.db")
TEST_UPLOAD = os.path.join(BASE, "data", "_test_packets_uploads")

for sfx in ("", "-wal", "-shm"):
    src = os.path.join(BASE, "data", "app.db" + sfx)
    dst = TEST_DB + sfx
    if os.path.exists(src):
        shutil.copy(src, dst)
    elif os.path.exists(dst):
        os.remove(dst)
if os.path.isdir(TEST_UPLOAD):
    shutil.rmtree(TEST_UPLOAD)


def _sql(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(query, args).fetchall()
    finally:
        conn.close()


# 改造前的存量快照：状态分布与证据长度，导入 app（触发迁移）后必须一模一样
BEFORE = {(r["id"], r["verify_status"], r["verified_at"])
          for r in _sql("SELECT id, verify_status, verified_at FROM interfaces")}

import db  # noqa: E402
db.DB_PATH = TEST_DB
db.UPLOAD_DIR = TEST_UPLOAD          # 数据包文件也落在副本目录，不碰真实 uploads

import app as platform  # noqa: E402  导入即 bootstrap + 建 packets 表
from api import packets as pktapi  # noqa: E402
from core import packets as pk  # noqa: E402

TOKEN = open(os.path.join(BASE, "data", "api-token.txt"), encoding="utf-8").read().strip()
client = platform.app.test_client()
H = {"X-API-Token": TOKEN}
fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail else ''}")
    if not cond:
        fails.append(name)


def post(path, payload):
    r = client.post(path, json=payload, headers=H)
    try:
        return r.status_code, r.get_json()
    except Exception:
        return r.status_code, None


PROJ = _sql("SELECT id FROM projects ORDER BY id")[0]["id"]
CASE = _sql("SELECT id FROM cases ORDER BY id")[0]["id"]


def new_interface(name, path):
    code, body = post("/api/interfaces", {"project_id": PROJ, "name": name,
                                          "method": "GET", "path": path,
                                          "module": "_pkt_test"})
    return body["id"] if code == 201 else None


print("== 1. core 校验：不成形的报文要当场拒绝 ==")
bad_cases = [
    ("method 非法", {"request": {"method": "FETCH", "url": "/a"},
                   "response": {"status": 200, "body": "x"}}, "request.method"),
    ("url 为空", {"request": {"method": "GET", "url": ""},
                "response": {"status": 200, "body": "x"}}, "request.url"),
    ("url 既非绝对也非路径", {"request": {"method": "GET", "url": "abc.com/x"},
                         "response": {"status": 200, "body": "x"}}, "request.url"),
    ("status 越界", {"request": {"method": "GET", "url": "/a"},
                   "response": {"status": 999, "body": "x"}}, "response.status"),
    ("status 缺失", {"request": {"method": "GET", "url": "/a"},
                   "response": {"body": "x"}}, "response.status"),
]
base = {"project_id": PROJ, "linked_type": "interface", "linked_id": 1}
for label, frag, want in bad_cases:
    payload = dict(base)
    payload.update(frag)
    _, err = pk.normalize(payload)
    check(f"拒绝：{label}", err is not None and want in err, err)

_, err = pk.normalize({"project_id": PROJ, "linked_type": "case", "linked_id": 1,
                       "request": {"method": "GET", "url": "/a"},
                       "response": {"status": 200, "body": "x"}})
check("拒绝：linked_type 不在白名单", err is not None and "linked_type" in err, err)

print("\n== 2. core 归一：头/体的各种写法 ==")
norm, _ = pk.normalize({"project_id": PROJ, "linked_type": "interface", "linked_id": 1,
                        "request": {"method": "post", "url": "https://a/b?x=1",
                                    "headers": [["tenant-id", "163"], ["Authorization", "Bearer t"]],
                                    "body": {"sku": "A1"}},
                        "response": {"status": "201", "body": {"code": 0},
                                     "headers": "Content-Type: application/json"}})
check("method 大写", norm["req_method"] == "POST", norm["req_method"])
check("headers 列表写法转 dict",
      json.loads(norm["req_headers"]) == {"tenant-id": "163", "Authorization": "Bearer t"},
      norm["req_headers"])
check("headers 冒号文本写法转 dict",
      json.loads(norm["resp_headers"]).get("Content-Type") == "application/json",
      norm["resp_headers"])
check("body 为 dict 时存 JSON 串", json.loads(norm["req_body"]) == {"sku": "A1"})
check("status 字符串转 int", norm["resp_status"] == 201, norm["resp_status"])

print("\n== 3. core 完整度判定 ==")
def level(req, resp):
    n, e = pk.normalize({"project_id": PROJ, "linked_type": "interface", "linked_id": 1,
                         "request": req, "response": resp})
    assert e is None, e
    return pk.completeness(n)

lvl, miss = level({"method": "GET", "url": "/a", "headers": {"t": "1"}},
                  {"status": 200, "headers": {"c": "1"}, "body": '{"code":0}'})
check("四要素齐全 = full", lvl == "full", f"{lvl} {miss}")
lvl, miss = level({"method": "GET", "url": "/a"}, {"status": 200, "body": '{"code":0}'})
check("缺头但四要素齐 = full（只提示）", lvl == "full" and "请求头" in miss, f"{lvl} {miss}")
lvl, miss = level({"method": "GET", "url": "/a", "headers": {"t": "1"}},
                  {"status": 200, "headers": {"c": "1"}, "body": ""})
check("缺响应体 = partial", lvl == "partial" and "响应体" in miss, f"{lvl} {miss}")
lvl, miss = level({"method": "GET", "url": "/a", "headers": {"t": "1"}},
                  {"status": 204, "headers": {"c": "1"}, "body": ""})
check("204 无体不算缺 = full", lvl == "full", f"{lvl} {miss}")
lvl, miss = level({"method": "HEAD", "url": "/a", "headers": {"t": "1"}},
                  {"status": 200, "headers": {"c": "1"}, "body": ""})
check("HEAD 无体不算缺 = full", lvl == "full", f"{lvl} {miss}")
lvl, miss = level({"method": "GET", "url": "/a", "headers": {"t": "1"}},
                  {"status": 200, "headers": {"c": "1"}, "body": "   "})
check("响应体只有空白 = partial", lvl == "partial", f"{lvl} {miss}")

print("\n== 4. core 落盘判定 ==")
spill, chars, nbytes, sha = pk.spill_figure("x" * pk.INLINE_CHARS)
check(f"{pk.INLINE_CHARS} 字符正好不落盘", spill is False and chars == pk.INLINE_CHARS)
spill, chars, nbytes, sha = pk.spill_figure("中" * 10000)
check("超阈值落盘", spill is True and chars == 10000)
check("字节数按 UTF-8 算（中文 3 字节）", nbytes == 30000, nbytes)
check("sha256 稳定", sha == pk.spill_figure("中" * 10000)[3] and len(sha) == 64)
name = pk.spill_name("a" * 64, 12345)
check("落盘名只含 sha 与长度", name == "a" * 16 + "-12345.txt", name)

print("\n== 5. API：完整数据包把接口置为已验证 ==")
iid = new_interface("_pkt_test_完整包", "/_pkt_test/full")
check("建接口成功", iid is not None, iid)
check("新接口初始 unverified",
      _sql("SELECT verify_status FROM interfaces WHERE id=?", (iid,))[0][0] == "unverified")

code, body = post("/api/packets", {
    "project_id": PROJ, "linked_type": "interface", "linked_id": iid,
    "label": "带 tenant-id 正常查询",
    "request": {"method": "GET", "url": "https://test.example.com/_pkt_test/full?a=1",
                "query": {"a": 1},
                "headers": {"tenant-id": "163", "Authorization": "Bearer xxx"}},
    "response": {"status": 200, "duration_ms": 210,
                 "headers": {"Content-Type": "application/json"},
                 "body": '{"code":0,"data":[{"id":1}]}'},
})
check("POST /api/packets 返回 201", code == 201, code)
check("判为完整", body and body.get("completeness") == "full", body)
check("小响应内联存储", body and body.get("stored") == "inline", body and body.get("stored"))
check("回带 verify_status=verified", body and body.get("verify_status") == "verified")
SMALL_PID = body["id"]      # 后面步骤会覆盖 body，页面断言要用这个 id
check("接口状态已变为 verified",
      _sql("SELECT verify_status FROM interfaces WHERE id=?", (iid,))[0][0] == "verified")
check("verified_at 已写入",
      bool(_sql("SELECT verified_at FROM interfaces WHERE id=?", (iid,))[0][0]))

print("\n== 6. 回归：10 个字符的证据不再能冒充已验证 ==")
iid2 = new_interface("_pkt_test_只有摘要", "/_pkt_test/summary")
code, body = post("/api/interfaces", {"project_id": PROJ, "name": "_pkt_test_纯摘要",
                                      "method": "GET", "path": "/_pkt_test/sum",
                                      "evidence": "GET -> 200", "module": "_pkt_test"})
check("带 10 字符 evidence 建接口 → unverified", body.get("verify_status") == "unverified", body)
check("并明确告知 evidence 不参与判定",
      "evidence_note" in (body or {}), (body or {}).get("evidence_note"))

code, body = post("/api/packets", {
    "project_id": PROJ, "linked_type": "interface", "linked_id": iid2,
    "request": {"method": "GET", "url": "/_pkt_test/summary", "headers": {"a": "b"}},
    "response": {"status": 200, "headers": {"c": "d"}, "body": ""},
})
check("缺响应体的包 → partial", body.get("completeness") == "partial", body)
check("partial 不升级接口", body.get("verify_status") == "unverified", body)
check("给出补齐提示", "hint" in (body or {}), (body or {}).get("hint"))
check("接口仍是 unverified",
      _sql("SELECT verify_status FROM interfaces WHERE id=?", (iid2,))[0][0] == "unverified")

# 诚实性：给一条已验证的接口补个残缺包，返回里的 verify_status 必须是接口真实状态。
# 早先的实现按"本次包"推断，会谎报 unverified，而库里其实还是 verified。
code, bp = post("/api/packets", {
    "project_id": PROJ, "linked_type": "interface", "linked_id": iid,
    "request": {"method": "GET", "url": "/_pkt_test/full", "headers": {"a": "b"}},
    "response": {"status": 200, "headers": {"c": "d"}, "body": ""}})
check("已验证接口补残缺包：返回真实状态，不谎报", bp.get("verify_status") == "verified", bp)
check("并说明本次包未改动接口状态", "未改动接口状态" in bp.get("hint", ""), bp.get("hint"))

print("\n== 7. 大响应：落盘且一个字符都不能少 ==")
big = json.dumps({"code": 0, "msg": "",
                  "data": [{"i": i, "name": f"项目{i}", "unit": "盒"} for i in range(6000)]},
                 ensure_ascii=False)
check("构造的响应体足够大（>10 万字符）", len(big) > 100000, len(big))
iid3 = new_interface("_pkt_test_大响应", "/_pkt_test/big")
code, body = post("/api/packets", {
    "project_id": PROJ, "linked_type": "interface", "linked_id": iid3,
    "label": "字典全量返回",
    "request": {"method": "GET", "url": "/_pkt_test/big", "headers": {"tenant-id": "163"}},
    "response": {"status": 200, "headers": {"Content-Type": "application/json"}, "body": big},
})
check("202/201 落盘", code == 201 and body.get("stored") == "file", body and body.get("stored"))
check("回带字符数与原文一致", body.get("resp_chars") == len(big), body.get("resp_chars"))
check("回带字节数与 UTF-8 一致", body.get("resp_bytes") == len(big.encode("utf-8")))
BIG_PID = body["id"]      # 大包 id：页面截断提示与下载入口断言要用
row = _sql("SELECT resp_body, resp_body_file, resp_chars, resp_bytes, sha256 "
           "FROM packets WHERE id=?", (body["id"],))[0]
check("库里不再存大响应的内联副本", row["resp_body"] == "")
check("库里记了文件引用", bool(row["resp_body_file"]), row["resp_body_file"])
check("库里字符数是全量", row["resp_chars"] == len(big), row["resp_chars"])
path = os.path.join(TEST_UPLOAD, row["resp_body_file"])
check("文件确实写到了 uploads/packets/", os.path.exists(path), path)
disk = open(path, encoding="utf-8").read()
check("文件内容与原文逐字符相同（未截断）", disk == big, f"{len(disk)} vs {len(big)}")
check("结尾完整（不是半个 JSON）", disk.rstrip().endswith("]}"))
check("括号平衡", disk.count("{") == disk.count("}") and disk.count("[") == disk.count("]"))
check("文件字节数 = resp_bytes", os.path.getsize(path) == row["resp_bytes"])

print("\n== 8. 读取分档：预览必须自报「这是预览」 ==")
r = client.get(f"/api/packets/{body['id']}", headers=H)
d = r.get_json()
check("默认档响应体只给 2000 字符", len(d["resp_body"]) == pktapi.PREVIEW_CHARS, len(d["resp_body"]))
check("标了 body_truncated_for_display", d["body_truncated_for_display"] is True)
check("给了 preview_chars", d["preview_chars"] == pktapi.PREVIEW_CHARS)
check("同时给了真实总长", d["resp_chars_actual"] == len(big), d["resp_chars_actual"])
check("text 字段是人读全文骨架",
      "GET /_pkt_test/big" in d["text"] and "RESPONSE 200" in d["text"] and "RESPONSE BODY" in d["text"])

r = client.get(f"/api/packets/{body['id']}?body=full", headers=H)
d = r.get_json()
check("?body=full 给全量", len(d["resp_body"]) == len(big), len(d["resp_body"]))
check("?body=full 不再标截断", d["body_truncated_for_display"] is False)

r = client.get(f"/api/packets/{body['id']}?body=none", headers=H)
check("?body=none 不带正文", "resp_body" not in r.get_json())

r = client.get(f"/api/packets/{body['id']}/download", headers=H)
check("下载返回 200", r.status_code == 200)
check("下载内容完整", r.get_data(as_text=True) == big)
check("下载附带文件名", "attachment" in r.headers.get("Content-Disposition", ""))

print("\n== 9. 列表与校验 ==")
r = client.get(f"/api/packets?linked_type=interface&linked_id={iid3}&limit=10", headers=H)
rows = r.get_json()
check("按锚点列表取到 1 条", len(rows) == 1, len(rows))
check("列表不带报文正文", "resp_body" not in rows[0] and "req_headers" not in rows[0])
check("列表带 X-Total-Count", r.headers.get("X-Total-Count") == "1", r.headers.get("X-Total-Count"))

code, body_bad = post("/api/packets", {
    "project_id": PROJ + 9999, "linked_type": "interface", "linked_id": iid3,
    "request": {"method": "GET", "url": "/x"}, "response": {"status": 200, "body": "x"}})
check("跨项目挂包被拒", code == 400 and "不一致" in body_bad.get("error", ""), body_bad)

code, body_bad = post("/api/packets", {
    "project_id": PROJ, "linked_type": "interface", "linked_id": 999999,
    "request": {"method": "GET", "url": "/x"}, "response": {"status": 200, "body": "x"}})
check("挂到不存在的对象被拒", code == 400, body_bad)

code, body_bad = post("/api/packets", {
    "project_id": PROJ, "linked_type": "blog", "linked_id": iid3,
    "request": {"method": "GET", "url": "/x"}, "response": {"status": 200, "body": "x"}})
check("linked_type 白名单生效", code == 400, body_bad)

print("\n== 10. 挂到 Bug / 执行 ==")
bug_id = _sql("SELECT id FROM bugs ORDER BY id")[0]["id"]
bug_pid = _sql("SELECT project_id FROM bugs WHERE id=?", (bug_id,))[0]["project_id"]
code, bb = post("/api/packets", {
    "project_id": bug_pid, "linked_type": "bug", "linked_id": bug_id,
    "label": "复现越权访问",
    "request": {"method": "GET", "url": "https://t.example.com/a?uid=2",
                "headers": {"tenant-id": "163"}},
    "response": {"status": 200, "headers": {"c": "d"}, "body": '{"total":1}'}})
check("Bug 挂包成功", code == 201, bb)
check("Bug 挂包不影响接口状态轴", "verify_status" not in (bb or {}))

code, eb = post("/api/packets", {
    "project_id": PROJ, "linked_type": "execution", "linked_id":
        _sql("SELECT id FROM executions LIMIT 1")[0]["id"],
    "request": {"method": "POST", "url": "/a", "headers": {"k": "v"}, "body": '{"a":1}'},
    "response": {"status": 400, "headers": {"c": "d"}, "body": '{"code":400}'}})
check("执行挂包成功（executions 无 project_id，走 cases 反查）", code == 201, eb)

print("\n== 11. 页面渲染：原生报文展示（2026-10-26 去花里胡哨后） ==")
with client.session_transaction() as sess:
    sess["user"] = "admin"
html = client.get(f"/interfaces/{iid}").get_data(as_text=True)
check("接口页出现「数据包证据」", "数据包证据" in html)
# 原生报文：绝对 URL 转 origin-form 请求行 + Host 头（raw_text 的口径）
check("页面含 origin-form 请求行", "GET /_pkt_test/full?a=1 HTTP/1.1" in html)
check("绝对 URL 转成 Host 头", "Host: test.example.com" in html)
check("页面含请求头", "tenant-id: 163" in html)
check("页面含响应状态", "HTTP/1.1 200 OK" in html)
check("页面含响应体原文", "&#34;code&#34;:0" in html or '"code":0' in html)
check("没有双栏/头表格残留", "pkt-cols" not in html and "pkt-hdrs" not in html)
check("小包页面不带下载链接（下载入口只在截断时给）",
      f"/packets/{SMALL_PID}/download" not in html)
check("小包页面有原始报文页入口", f"/packets/{SMALL_PID}/raw" in html)

html_big = client.get(f"/interfaces/{iid3}").get_data(as_text=True)
check("大响应页出现预览截断提示", "预览只显示前" in html_big)
check("大响应页明说存储未截断", "存储未截断" in html_big)
check("大响应页给出真实总长", f"{len(big):,}" in html_big, f"期望 {len(big):,}")
check("大响应页给 .http 下载入口（截断时才出现）",
      f"/packets/{BIG_PID}/raw?download=1" in html_big and "下载完整原文" in html_big)
check("大响应页的报文体按 20000 截断", "pkt-raw" in html_big)

html_old = client.get("/interfaces/11").get_data(as_text=True)
check("存量接口（无包）显式提示「没有原始报文」", "没有原始报文" in html_old)
check("存量接口标出无法复核", "无法复核" in html_old)

html_bug = client.get(f"/bugs/{bug_id}").get_data(as_text=True)
check("Bug 详情页渲染数据包", "数据包证据" in html_bug)

print("\n== 11b. 原始报文出口：整段请求 + 整段响应，一个字不裁 ==")
n4, _ = pk.normalize({
    "project_id": PROJ, "linked_type": "interface", "linked_id": iid,
    "request": {"method": "GET", "url": "https://t.example.com/a/b?x=1&y=2",
                "headers": [["tenant-id", "163"], ["Authorization", "Bearer tk"],
                            ["User-Agent", "python-requests/2.34.2"]]},
    "response": {"status": 404, "headers": {"Content-Type": "application/json"},
                 "body": '{"code":404}'}})
raw = pk.raw_text(n4)
first = raw.splitlines()[0]
check("请求行用 origin-form（不带 scheme/host）", first == "GET /a/b?x=1&y=2 HTTP/1.1", first)
check("Host 从绝对 URL 补上（头里没记才补）", raw.splitlines()[1] == "Host: t.example.com",
      raw.splitlines()[1])
hdrs = [l.split(":", 1)[0] for l in raw.split("\n\n")[0].splitlines()[1:] if ":" in l]
check("头按原顺序全给，不筛「噪音头」",
      hdrs == ["Host", "tenant-id", "Authorization", "User-Agent"], hdrs)
check("状态行带 reason", "HTTP/1.1 404 Not Found" in raw)
check("响应体原样收尾", raw.endswith('{"code":404}'))

n5, _ = pk.normalize({
    "project_id": PROJ, "linked_type": "interface", "linked_id": iid,
    "request": {"method": "GET", "url": "/admin-api/x",
                "query": {"userId": "366", "monthTime": "2025-11-01"},
                "headers": {"tenant-id": "163"}},
    "response": {"status": 200, "headers": {"c": "d"}, "body": "ok"}})
raw5 = pk.raw_text(n5)
check("path + JSON query 还原成 query string",
      raw5.startswith("GET /admin-api/x?userId=366&monthTime=2025-11-01 HTTP/1.1"),
      raw5.splitlines()[0])
check("没有 host 就不臆造 Host 头", "\nHost:" not in raw5)

n6, _ = pk.normalize({
    "project_id": PROJ, "linked_type": "interface", "linked_id": iid,
    "request": {"method": "POST", "url": "https://a.example.com/p",
                "headers": {"Host": "b.example.com"}, "body": '{"k":1}'},
    "response": {"status": 201, "headers": {}, "body": ""}})
raw6 = pk.raw_text(n6)
check("头里已有 Host 时用头的值、不重复加", raw6.count("Host:") == 1, raw6.splitlines()[:2])
check("请求体保留在请求头之后",
      raw6.split("\n\n")[1] == '{"k":1}', raw6.split("\n\n")[1][:20])

r = client.get(f"/api/packets/{SMALL_PID}/raw", headers=H)
check("API raw 返回 200", r.status_code == 200, r.status_code)
check("API raw 是 text/plain", r.headers.get("Content-Type", "").startswith("text/plain"),
      r.headers.get("Content-Type"))
api_raw = r.get_data(as_text=True)
check("API raw 有请求行", api_raw.startswith("GET /_pkt_test/full?a=1 HTTP/1.1"),
      api_raw.splitlines()[0])
check("API raw 有请求头", "tenant-id: 163" in api_raw)
check("API raw 有响应段", "HTTP/1.1 200 OK" in api_raw and '{"code":0' in api_raw)

r = client.get("/api/packets/999999/raw", headers=H)
check("不存在的包 → 404", r.status_code == 404, r.status_code)

anon = platform.app.test_client()
check("网页原文：未登录 302", anon.get(f"/packets/{SMALL_PID}/raw").status_code == 302)
r = client.get(f"/packets/{SMALL_PID}/raw")
web_raw = r.get_data(as_text=True)
check("网页原文 200 + 纯文本", r.status_code == 200
      and r.headers.get("Content-Type", "").startswith("text/plain"))
check("网页原文与 API 输出一致", web_raw == api_raw, f"{len(web_raw)} vs {len(api_raw)}")
r = client.get(f"/packets/{SMALL_PID}/raw?download=1")
check("下载带 .http 文件名",
      f"packet-{SMALL_PID}.http" in r.headers.get("Content-Disposition", ""),
      r.headers.get("Content-Disposition"))

r = client.get(f"/api/packets/{body['id']}/raw", headers=H)
big_raw = r.get_data(as_text=True)
check("大响应 raw 是全文，不截断", big in big_raw, f"{len(big_raw)} vs {len(big)}")
check("大响应 raw 结尾完整", big_raw.rstrip().endswith("]}"))

html_raw = client.get(f"/interfaces/{iid}").get_data(as_text=True)
check("页面有「原始报文页」入口", f"/packets/{SMALL_PID}/raw" in html_raw)
# 「只下响应体」入口已按"去花里胡哨"从页面移除（下载 .http 已含响应体），
# 端点本身保留：这里直接打端点验证功能仍在。
# 注意：send_from_directory 会持有落盘文件句柄，Windows 上不显式关闭响应，
# 后面"删包清理文件"的 os.remove 会因句柄未释放而静默失败。
r_dl = client.get(f"/packets/{BIG_PID}/download")
dl_data = r_dl.get_data(as_text=True)
r_dl.close()
check("响应体下载端点仍可用（附件）",
      r_dl.status_code == 200 and len(dl_data) == len(big),
      f"HTTP {r_dl.status_code} / {len(dl_data)} vs {len(big)}")

print("\n== 12. 存量保护：161 条一条都不许变 ==")
after = {(r["id"], r["verify_status"], r["verified_at"])
         for r in _sql("SELECT id, verify_status, verified_at FROM interfaces")}
unchanged = {x for x in after if x in BEFORE}
check("原有接口状态/时间全未改动", unchanged == BEFORE,
      f"{len(BEFORE)} → 命中 {len(unchanged)}")

old_id = sorted(i for i, _, _ in BEFORE)[0]
old_status = _sql("SELECT verify_status FROM interfaces WHERE id=?", (old_id,))[0][0]
r = client.put(f"/api/interfaces/{old_id}", json={"evidence": "补一句摘要"}, headers=H)
check("对存量接口只补 evidence → 状态不降级",
      r.get_json()["verify_status"] == old_status, f"{old_status} -> {r.get_json()['verify_status']}")

r = client.put(f"/api/interfaces/{old_id}", json={"name": "改个名字试试"}, headers=H)
check("改契约字段 → changed", r.get_json()["verify_status"] == "changed", r.get_json())

r = client.put(f"/api/interfaces/{iid2}", json={
    "packet": {"request": {"method": "GET", "url": "/_pkt_test/summary",
                           "headers": {"a": "b"}},
               "response": {"status": 200, "headers": {"c": "d"},
                            "body": '{"code":0}'}}}, headers=H)
check("PUT 带完整包 → verified", r.get_json()["verify_status"] == "verified", r.get_json())
check("PUT 带包时把包入库",
      _sql("SELECT count(*) FROM packets WHERE linked_type='interface' AND linked_id=?",
           (iid2,))[0][0] == 2,
      _sql("SELECT count(*) FROM packets WHERE linked_type='interface' AND linked_id=?",
           (iid2,))[0][0])

print("\n== 13. 删包清理文件 ==")
r = client.delete(f"/api/packets/{body['id']}", headers=H)
check("删除返回 200", r.status_code == 200, r.status_code)
check("库里记录已删", not _sql("SELECT 1 FROM packets WHERE id=?", (body["id"],)))
check("落盘文件已清理", not os.path.exists(path))

print("\n" + "=" * 60)
if fails:
    print(f"失败 {len(fails)} 项：")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("全部通过")
