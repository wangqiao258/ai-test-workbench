"""页面渲染巡检：所有网页路由 × 主要参数组合，在数据库副本上跑。

覆盖的是"服务端能不能把每个页面渲染完整"，不校验业务规则细节
（规则在 smoke_api / verify_bug_views / verify_settings 等脚本里）。

拦的是这类真实故障：
  1) 改了 list 函数返回的键名、模板还在用旧键 —— 页面 500 或整块空白；
  2) 新加的 tab / view / 筛选参数没进白名单 —— 手改 URL 得到空白页；
  3) 详情页拿到不存在的 id 会 500 而不是 404；
  4) 跨项目拿 panel.html —— 越权读到别的项目的契约；
  5) 未登录能直接打开页面（login_required 漏挂）；
  6) 页面里泄漏 jinja 异常 / None / Undefined 这类内部痕迹。

用法（在 ai-test-platform 目录下）：
    python tests/verify_pages.py
"""
import os
import re
import shutil
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_verify_pages.db")
TMP_UP = os.path.join(BASE, "data", "_verify_pages_uploads")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)
for extra in ("-wal", "-shm"):
    p = TEST_DB + extra
    if os.path.exists(p):
        os.remove(p)
shutil.rmtree(TMP_UP, ignore_errors=True)
os.makedirs(TMP_UP, exist_ok=True)
with open(os.path.join(TMP_UP, "probe.png"), "wb") as f:
    f.write(b"\x89PNG\r\n\x1a\n fake")

import db  # noqa: E402
db.DB_PATH = TEST_DB
db.UPLOAD_DIR = TMP_UP

import app as platform  # noqa: E402  导入即 bootstrap + 迁移（作用于副本）
platform.UPLOAD_DIR = TMP_UP          # app.py 里 from db import UPLOAD_DIR 是模块级变量

client = platform.app.test_client()
fails, skips = [], []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail else ''}")
    if not cond:
        fails.append(name)


def skip(name, why):
    print(f"SKIP  {name}  {why}")
    skips.append(name)


def sql_one(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    try:
        row = conn.execute(query, args).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def login(username="admin"):
    with client.session_transaction() as sess:
        sess["user"] = username


def get_page(path, expect=200):
    """GET 一页并做通用体检，返回 (是否通过, html/响应)。"""
    r = client.get(path)
    return r


BAD_MARKS = ("Traceback (most recent call last)", "jinja2.exceptions", "UndefinedError",
             "werkzeug.routing", "sqlite3.", "<title>500")


def page_ok(path, label, need=("<!DOCTYPE html>", "</html>"), forbid=BAD_MARKS):
    r = get_page(path)
    html = r.get_data(as_text=True)
    problems = []
    if r.status_code != 200:
        problems.append(f"HTTP {r.status_code}")
    for token in need:
        if token not in html:
            problems.append(f"缺 {token!r}")
    for token in forbid:
        if token in html:
            problems.append(f"泄漏 {token!r}")
    # Jinja 把不存在的变量渲染成空串，但 dict 字段缺失时常漏出字面量 None
    if re.search(r">\s*None\s*<", html):
        problems.append("泄漏 None")
    check(label, not problems, "；".join(problems) if problems else path)
    return r, html


print("== 1. 登录流程 ==")
fresh = platform.app.test_client()
r = fresh.get("/login")
check("未登录可打开登录页", r.status_code == 200 and 'name="username"' in r.get_data(as_text=True))
r = fresh.post("/login", data={"username": "admin", "password": "admin123"})
check("正确口令登录 302 到首页", r.status_code == 302 and r.headers["Location"].endswith("/"),
      f"{r.status_code} {r.headers.get('Location')}")
r = fresh.post("/login", data={"username": "admin", "password": "wrong"})
check("错误口令留在登录页并提示",
      r.status_code == 200 and "用户名或密码错误" in r.get_data(as_text=True))
r = fresh.post("/login?next=https://evil.com/x", data={"username": "admin", "password": "admin123"})
check("登录 next 是外链 → 回首页（开放重定向）",
      r.status_code == 302 and r.headers["Location"].endswith("/"), r.headers.get("Location"))
r = fresh.post("/login?next=/review", data={"username": "admin", "password": "admin123"})
check("登录 next 是站内路径 → 跳过去", r.status_code == 302 and r.headers["Location"].endswith("/review"),
      r.headers.get("Location"))
# 锁定用不存在的账号试，别把 admin 锁在门外影响后续用例。
# 第 5 次失败只是"记满"，提示仍是他自己的错误；第 6 次才进锁定期。
for i in range(6):
    r = fresh.post("/login", data={"username": "nobody-probe", "password": "x"})
locked = "失败次数过多" in r.get_data(as_text=True)
check("连续错 5 次后触发登录限速", locked, f"第 6 次 {r.status_code}")

print("\n== 2. 未登录访问受保护页面 ==")
anon = platform.app.test_client()
PROTECTED = ["/", "/settings", "/review", "/projects/1?tab=docs",
             "/projects/1?tab=interfaces&view=tree", "/projects/1?tab=cases",
             "/projects/1?tab=bugs", "/projects/1?tab=runs", "/projects/1?tab=settings"]
bad = []
for p in PROTECTED:
    r = anon.get(p)
    loc = r.headers.get("Location", "")
    if not (r.status_code == 302 and "/login" in loc):
        bad.append(f"{p} → {r.status_code} {loc}")
check(f"{len(PROTECTED)} 个受保护页面未登录全部跳登录", not bad, "；".join(bad))

login()
r = client.get("/logout")
check("登出清 session 并回登录页",
      r.status_code == 302 and r.headers["Location"].endswith("/login"))
r = client.get("/")
check("登出后首页跳登录", r.status_code == 302 and "/login" in r.headers.get("Location", ""))
login()

print("\n== 3. 顶层页面 ==")
page_ok("/", "工作台首页")
page_ok("/settings", "账号页")
page_ok("/review", "Bug 待办页")
page_ok("/login", "登录页（已登录也应可渲染）")

print("\n== 4. 项目页六个 tab × 参数组合 ==")
PID = sql_one("SELECT id FROM projects ORDER BY id LIMIT 1")
if not PID:
    skip("项目页巡检", "库里没有项目")
else:
    COMBOS = [
        ("", "默认 tab"),
        ("?tab=docs", "文档"),
        ("?tab=docs&dtype=plan", "文档-类型筛选"),
        ("?tab=docs&q=zzz_nomatch", "文档-关键字无结果"),
        ("?tab=interfaces", "接口-列表"),
        ("?tab=interfaces&view=list&method=GET", "接口-按方法"),
        ("?tab=interfaces&view=tree", "接口-目录树"),
        ("?tab=interfaces&view=bogus", "接口-非法视图回落"),
        ("?tab=interfaces&view=tree&env=999999", "接口-不存在的环境"),
        ("?tab=interfaces&module=不存在的模块", "接口-空模块"),
        ("?tab=interfaces&page=999", "接口-页码越界"),
        ("?tab=cases", "用例"),
        ("?tab=cases&priority=P0", "用例-优先级"),
        ("?tab=cases&result=pass", "用例-执行结果"),
        ("?tab=cases&anchor=doc", "用例-锚点"),
        ("?tab=cases&dim=异常", "用例-维度"),
        ("?tab=cases&page=999", "用例-页码越界"),
        ("?tab=bugs", "Bug-默认视图"),
        ("?tab=bugs&progress=all", "Bug-全部"),
        ("?tab=bugs&progress=bogus", "Bug-非法进度回落"),
        ("?tab=bugs&sel=999999", "Bug-选了不存在的条目"),
        ("?tab=bugs&page=999", "Bug-页码越界"),
        ("?tab=runs", "运行-默认回归"),
        ("?tab=runs&kind=all", "运行-全部类型"),
        ("?tab=runs&kind=diagnostic", "运行-诊断"),
        ("?tab=runs&status=done", "运行-按状态"),
        ("?tab=runs&kind=bogus", "运行-非法类型回落"),
        ("?tab=settings", "项目设置"),
        ("?tab=settings&edit=999999", "项目设置-编辑不存在的账号"),
        ("?tab=nope", "非法 tab 回落文档"),
    ]
    bad = []
    for qs, label in COMBOS:
        r = client.get(f"/projects/{PID}{qs}")
        html = r.get_data(as_text=True)
        if r.status_code != 200:
            bad.append(f"{label} HTTP {r.status_code}")
        elif "</html>" not in html or 'class="tabs"' not in html:
            bad.append(f"{label} 页面不完整")
        elif any(m in html for m in BAD_MARKS) or re.search(r">\s*None\s*<", html):
            bad.append(f"{label} 有内部痕迹")
    check(f"{len(COMBOS)} 种项目页参数组合都能渲染", not bad, "；".join(bad))

    # 白名单：非法 view 必须回落到列表（含 itf-search 的树视图不能出现）
    html = client.get(f"/projects/{PID}?tab=interfaces&view=bogus").get_data(as_text=True)
    check("view=bogus 回落到列表视图", 'id="itf-tree"' not in html and "筛选" in html)
    html = client.get(f"/projects/{PID}?tab=interfaces&view=tree").get_data(as_text=True)
    check("view=tree 渲染目录树容器",
          'id="itf-tree"' in html and 'id="itf-detail"' in html and 'id="itf-search"' in html)
    html = client.get(f"/projects/{PID}?tab=nope").get_data(as_text=True)
    check("非法 tab 回落到文档", re.search(r'href="\?tab=docs[^"]*"\s+class="active"', html) is not None)

    # 旧 tab 兼容：bookmark / README 里的 ?tab=apidoc 必须 302 到树视图
    r = client.get(f"/projects/{PID}?tab=apidoc")
    loc = r.headers.get("Location", "")
    check("旧链接 tab=apidoc 302 到接口树", r.status_code == 302
          and "tab=interfaces" in loc and "view=tree" in loc, loc)

    # 每个 tab 的导航高亮只能有一个
    for tab in ("docs", "interfaces", "cases", "bugs", "runs", "settings"):
        html = client.get(f"/projects/{PID}?tab={tab}").get_data(as_text=True)
        nav = re.findall(r'href="\?(?:tab=[a-z]+[^"]*)"\s+class="active"', html)
        check(f"tab={tab} 只有一条导航高亮", len(nav) == 1, f"{len(nav)} 条：{nav}")

print("\n== 5. 详情页 ==")
seed = {
    "case": sql_one("SELECT id FROM cases ORDER BY id LIMIT 1"),
    "run": sql_one("SELECT id FROM runs ORDER BY id LIMIT 1"),
    "bug": sql_one("SELECT id FROM bugs ORDER BY id LIMIT 1"),
    "doc": sql_one("SELECT id FROM docs ORDER BY id LIMIT 1"),
    "itf": sql_one("SELECT id FROM interfaces ORDER BY id LIMIT 1"),
    "packet": sql_one("SELECT id FROM packets ORDER BY id LIMIT 1"),
}
for key, label, need in (
        ("case", "用例详情", ("执行历史",)),
        ("run", "运行详情", ("已回填",)),
        ("bug", "Bug 详情", ("复现步骤",)),
        ("doc", "文档详情", ("md-body",)),
        ("itf", "接口详情", ("数据包证据",)),
):
    if not seed[key]:
        skip(f"{label}页", f"库里没有 {key}")
        continue
    page_ok(f"/{'cases' if key == 'case' else 'runs' if key == 'run' else 'bugs' if key == 'bug' else 'docs' if key == 'doc' else 'interfaces'}/{seed[key]}",
            label, need=need)

if seed["packet"]:
    r = client.get(f"/packets/{seed['packet']}/raw")
    check("数据包原始报文页是纯文本", r.status_code == 200
          and r.headers["Content-Type"].startswith("text/plain"), r.headers.get("Content-Type"))
    r = client.get(f"/packets/{seed['packet']}/download")
    check("数据包下载可用", r.status_code == 200
          and "attachment" in r.headers.get("Content-Disposition", ""),
          f"{r.status_code} {r.headers.get('Content-Disposition')}")
else:
    skip("数据包下载", "库里没有 packets")

print("\n== 6. 接口契约右栏（目录树 fetch 的片段）==")
IID = seed["itf"]
if not IID or not PID:
    skip("panel.html", "没有接口或项目")
else:
    pid_of_itf = sql_one("SELECT project_id FROM interfaces WHERE id=?", (IID,))
    r = client.get(f"/projects/{pid_of_itf}/interfaces/{IID}/panel.html")
    html = r.get_data(as_text=True)
    check("panel.html 返回片段且不套 base 模板",
          r.status_code == 200 and "<!DOCTYPE html>" not in html and "打开完整详情" in html,
          str(r.status_code))
    check("panel.html 与详情页同源渲染（含完整地址）", "完整地址" in html)
    other = sql_one("SELECT id FROM projects WHERE id != ? ORDER BY id LIMIT 1", (pid_of_itf,))
    if other:
        r = client.get(f"/projects/{other}/interfaces/{IID}/panel.html")
        check("panel.html 跨项目读不到（404 不是 200）", r.status_code == 404, r.status_code)
    else:
        skip("panel.html 越权", "只有一个项目")

r = client.get(f"/projects/{PID}/openapi.json")
check("网页端导出 openapi.json 是 JSON", r.status_code == 200
      and r.is_json and "openapi" in r.get_json(), str(r.status_code))

print("\n== 7. 不存在的 id 应该是 404 而不是 500 ==")
for path, label in (("/projects/999999", "项目"), ("/cases/999999", "用例"),
                    ("/runs/999999", "运行"), ("/bugs/999999", "Bug"),
                    ("/docs/999999", "文档"), ("/interfaces/999999", "接口"),
                    ("/packets/999999/raw", "数据包原文"),
                    ("/packets/999999/download", "数据包下载")):
    r = client.get(path)
    html = r.get_data(as_text=True)
    check(f"{label} 不存在 → 404", r.status_code == 404
          and "Traceback" not in html, r.status_code)

print("\n== 8. 静态文件与附件 ==")
r = client.get("/files/probe.png")
check("/files/ 能取到上传目录里的文件", r.status_code == 200, r.status_code)
r = client.get("/files/..%2Fapp.db")
check("/files/ 不能穿越到数据目录", r.status_code >= 400, r.status_code)
css = client.get("/static/style.css").get_data(as_text=True)
check("样式表可访问且带版本号",
      client.get("/static/style.css").status_code == 200 and len(css) > 500)
html = client.get("/").get_data(as_text=True)
check("引用样式表时带 ?v= 缓存版本", re.search(r"style\.css\?v=\d+", html) is not None)

print("\n== 9. 审核队列的跳转兼容 ==")
if seed["bug"]:
    r = client.get(f"/review/bug/{seed['bug']}")
    check("旧详情页 /review/bug/<id> 302 到队列并带 sel",
          r.status_code == 302 and "sel=" in r.headers.get("Location", ""),
          r.headers.get("Location"))
    r = client.get("/review/interface/1")
    check("非 bug 类型旧详情页 404", r.status_code == 404, r.status_code)
else:
    skip("审核队列跳转", "库里没有 bug")

print("\n" + ("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}"))
shutil.rmtree(TMP_UP, ignore_errors=True)
os.remove(TEST_DB)
sys.exit(1 if fails else 0)
