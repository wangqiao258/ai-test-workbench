"""验证数据包证据改为原生报文展示（2026-10-26，去花里胡哨）。

合成三种包：正常包 / 响应体超 20000 字符的截断包 / 不完整包，
在接口详情页渲染，核对：
- 渲染的就是 core/packets.raw_text 的原文（与 /packets/<id>/raw 同一份；
  模板走 Jinja 自动转义，比对时按 markupsafe.escape 后的文本——浏览器显示
  与剪贴板复制都是原文，转义是防包体里夹带 HTML/XSS 的正确行为）
- 没有双栏/头表格/details 折叠的残留
- 元信息行、截断提示与下载入口、不完整警告都在
"""
import html
import json
import os
import re
import shutil
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_pktview.db")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)

import db  # noqa: E402
db.DB_PATH = TEST_DB
db.init_db()
import app as platform  # noqa: E402
from core.packets import raw_text  # noqa: E402
from markupsafe import escape  # noqa: E402
from werkzeug.security import check_password_hash, generate_password_hash  # noqa: E402

conn = db.get_db()
fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not cond:
        fails.append(name)


iid = conn.execute("SELECT id FROM interfaces WHERE project_id=1 ORDER BY id LIMIT 1").fetchone()[0]


def add_packet(req_headers, resp_headers, body, completeness="full", missing=""):
    conn.execute(
        "INSERT INTO packets (project_id, linked_type, linked_id, label, req_method, "
        "req_url, req_query, req_headers, req_body, resp_status, resp_headers, resp_body, "
        "resp_chars, resp_bytes, sha256, completeness, missing, created_by, captured_at, "
        "created_at) VALUES (1,'interface',?,'自测包','POST','/admin-api/system/auth/login',"
        "'',?,?,200,?,? ,?,?,?, ?, ?, 'smoke', '2026-10-26 12:00:00', '2026-10-26 12:00:00')",
        (iid, json.dumps(req_headers, ensure_ascii=False), '{"username":"u"}',
         json.dumps(resp_headers, ensure_ascii=False), body, len(body),
         len(body.encode()), "sha" + str(abs(hash(body)))[:8], completeness, missing))
    return conn.execute("SELECT MAX(id) FROM packets").fetchone()[0]


ok_id = add_packet({"tenant-id": "163", "Content-Type": "application/json"},
                   {"Content-Type": "application/json"},
                   '{"code":0,"data":{"accessToken":"tk"}}')
big_body = '{"code":0,"data":{"list":[' + ",".join(f'{{"id":{i}}}' for i in range(4000)) + ']}}'
big_id = add_packet({}, {"Content-Type": "application/json"}, big_body)
partial_id = add_packet({}, {}, "", completeness="partial", missing="响应体、请求头、响应头")
conn.commit()

expect_ok = raw_text({
    "req_method": "POST", "req_url": "/admin-api/system/auth/login",
    "req_headers": json.dumps({"tenant-id": "163", "Content-Type": "application/json"}),
    "req_body": '{"username":"u"}', "resp_status": 200,
    "resp_headers": json.dumps({"Content-Type": "application/json"}),
    "resp_body": '{"code":0,"data":{"accessToken":"tk"}}'})
expect_partial = raw_text({
    "req_method": "POST", "req_url": "/admin-api/system/auth/login",
    "req_headers": "{}", "req_body": '{"username":"u"}', "resp_status": 200,
    "resp_headers": "{}", "resp_body": ""})
conn.close()

client = platform.app.test_client()
raw_pw = sqlite3.connect(TEST_DB)
pw = raw_pw.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
raw_pw.close()
if not check_password_hash(pw, "admin123"):
    c = db.get_db()
    c.execute("UPDATE users SET password_hash=? WHERE username='admin'",
              (generate_password_hash("admin123"),))
    c.commit()
    c.close()
client.post("/login", data={"username": "admin", "password": "admin123"})

html = client.get(f"/interfaces/{iid}").get_data(as_text=True)
print("接口详情页长度:", len(html))

check("渲染原生请求行", "POST /admin-api/system/auth/login HTTP/1.1" in html)
check("渲染请求头原文（按入库顺序）", "tenant-id: 163" in html)
check("渲染请求体原文", str(escape('{"username":"u"}')) in html)
check("渲染状态行", "HTTP/1.1 200 OK" in html)
check("渲染响应体原文", str(escape('{"code":0,"data":{"accessToken":"tk"}}')) in html)
check("没有双栏残留", "pkt-cols" not in html and "pkt-hdrs" not in html)
check("没有 details 折叠残留", "<details class=\"pkt\"" not in html)
check("元信息行含状态/字符/sha/完整", ">200</b>" in html and "sha256" in html and "完整" in html)
check("有原始报文页入口", f"/packets/{ok_id}/raw" in html)
check("不完整包有警告", "此包不完整" in html and "不会把接口置为" in html)
check("截断包有提示", "预览只显示前" in html and "下载完整原文" in html)

# 原文一致性：完整包的渲染文本 == raw_text 输出（按 Jinja 转义后比对）
check("完整包原文与 raw_text 逐字一致", str(escape(expect_ok)) in html,
      f"期望 {len(expect_ok)} 字符")
# 列表按 id 倒序，第一个 pre 应是不完整包（最后插入的）
first_pre = re.search(r'<pre class="pkt-raw">(.*?)</pre>', html, re.S)
check("首个 pre 是不完整包的原文", first_pre
      and first_pre.group(1) == str(escape(expect_partial)),
      f"页面 {len(first_pre.group(1)) if first_pre else 0} / 期望 {len(expect_partial)}")

# /packets/<id>/raw 页面本身不变（仍全量不截断）
raw_page = client.get(f"/packets/{big_id}/raw").get_data(as_text=True)
check("raw 页仍全量（大包不截断）", len(big_body) > 20000 and big_body[:100] in raw_page
      and len(raw_page) > 20000, f"raw 页 {len(raw_page)} 字符")

# Bug 详情页同样走原生展示
bid = conn_bug = None
c2 = db.get_db()
bug = c2.execute("SELECT id FROM bugs WHERE project_id=1 ORDER BY id LIMIT 1").fetchone()
if bug:
    c2.execute(
        "INSERT INTO packets (project_id, linked_type, linked_id, label, req_method, "
        "req_url, req_headers, req_body, resp_status, resp_headers, resp_body, "
        "resp_chars, resp_bytes, sha256, completeness, created_by, captured_at, created_at) "
        "VALUES (1,'bug',?,'bug 包','GET','/admin-api/x','',\"\",200,'','ok-body',7,7,"
        "'shabug','full','smoke','2026-10-26 12:00:00','2026-10-26 12:00:00')",
        (bug["id"],))
    c2.commit()
    bid = bug["id"]
c2.close()
if bid:
    bhtml = client.get(f"/bugs/{bid}").get_data(as_text=True)
    check("Bug 详情页也是原生报文", "GET /admin-api/x HTTP/1.1" in bhtml
          and "ok-body" in bhtml)

os.remove(TEST_DB)
print()
if fails:
    print(f"失败 {len(fails)} 项：" + "；".join(fails))
    sys.exit(1)
print("全部通过")
