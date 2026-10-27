"""前端契约测试：服务端渲染出来的 HTML 与页面内联 JS 是否对得上。

项目没有打包器也没有前端框架，JS 全写在模板里、靠 id / class / data-* 取 DOM。
这类代码没有编译期检查，改模板时最容易出现"服务端删了某个元素，JS 还在找它"：
页面不报错，只是点了没反应。本脚本把这些隐含约定变成断言。

检查项：
  1) 页面上内联 JS 里 getElementById("x") 的 id，必须真的出现在同一页的 HTML 里；
  2) 同一页不能有重复 id（getElementById 只返回第一个，会静默取错元素）；
  3) data-copy / data-copy-url / /packets/<id>/raw 这类"点了才发请求"的入口真的可用；
  4) 表单 action 必须是已注册路由，method 要对得上（否则 405/404）；
  5) 注入 JS 的 JSON（接口树 ITFS 等）能解析，且字段齐全——少一个字段就是前端 TypeError；
  6) 批量操作依赖的 form="bulk-form" + input.ids 数量与卡片数一致；
  7) 驳回必填原因依赖 form.elements.comment，页面上必须有这个控件；
  8) 分页链接必须保留当前筛选条件（否则翻页就把筛选丢了）。

用法（在 ai-test-platform 目录下）：
    python tests/verify_ui_contract.py
"""
import json
import os
import re
import shutil
import sqlite3
import sys
from urllib.parse import urljoin, urlsplit

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_verify_ui_contract.db")
TMP_UP = os.path.join(BASE, "data", "_verify_ui_contract_uploads")
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

client = platform.app.test_client()
with client.session_transaction() as sess:
    sess["user"] = "admin"

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


def sql_count(query, args=()):
    return sql_one(query, args) or 0


PID = sql_one("SELECT id FROM projects ORDER BY id LIMIT 1")
IID = sql_one("SELECT id FROM interfaces WHERE project_id=? ORDER BY id LIMIT 1", (PID,))
# 驳回态的 Bug 不渲染审核输入框（设计如此），挑一条还能审的来看表单契约
BID = sql_one("SELECT id FROM bugs WHERE review_status != 'rejected' ORDER BY id LIMIT 1")
CID = sql_one("SELECT id FROM cases ORDER BY id LIMIT 1")

# 库里没有数据包时自建一条：点开才发请求的入口（原始报文/下载）只有真挂上
# 报文才会渲染，否则这一整块永远是 SKIP，等于没测。
TOKEN = open(os.path.join(BASE, "data", "api-token.txt"), encoding="utf-8").read().strip()
API = {"X-API-Token": TOKEN}
probe = client.post("/api/interfaces", headers=API, json={
    "project_id": PID, "module": "UI契约自测", "name": "契约测试用接口",
    "method": "GET", "path": "/ui-selftest/probe", "resp_example": '{"ok":true}'})
PROBE_IID = (probe.get_json() or {}).get("id") if probe.status_code == 201 else None
PROBE_PKID = None
if PROBE_IID:
    pk = client.post("/api/packets", headers=API, json={
        "project_id": PID, "linked_type": "interface", "linked_id": PROBE_IID,
        "label": "UI 契约自测包",
        "request": {"method": "GET", "url": "/ui-selftest/probe",
                    "headers": {"X-Probe": "1"}, "body": ""},
        "response": {"status": 200, "headers": {"Content-Type": "application/json"},
                     "body": '{"ok":true}'}})
    PROBE_PKID = (pk.get_json() or {}).get("id") if pk.status_code == 201 else None

PAGES = {
    "首页": "/",
    "文档tab": f"/projects/{PID}?tab=docs",
    "接口列表": f"/projects/{PID}?tab=interfaces&view=list",
    "接口树": f"/projects/{PID}?tab=interfaces&view=tree",
    "用例tab": f"/projects/{PID}?tab=cases",
    "Bug tab": f"/projects/{PID}?tab=bugs",
    "运行tab": f"/projects/{PID}?tab=runs",
    "项目设置": f"/projects/{PID}?tab=settings",
    "审核队列": "/review",
    "账号页": "/settings",
}
if CID:
    PAGES["用例详情"] = f"/cases/{CID}"
if IID:
    PAGES["接口详情"] = f"/interfaces/{IID}"
if BID:
    PAGES["Bug 详情"] = f"/bugs/{BID}"
if PROBE_IID:
    PAGES["自测接口详情"] = f"/interfaces/{PROBE_IID}"

HTML = {}
for label, path in PAGES.items():
    r = client.get(path)
    HTML[label] = r.get_data(as_text=True) if r.status_code == 200 else ""
    if r.status_code != 200:
        print(f"FAIL  {label} 打不开（HTTP {r.status_code}），后续检查跳过")
        fails.append(f"{label} 打不开")

ID_RE = re.compile(r'\bid="([^"]+)"')
JS_BLOCK = re.compile(r"<script[^>]*>(.*?)</script>", re.S)
GET_BY_ID = re.compile(r'getElementById\(\s*["\']([^"\']+)["\']\s*\)')


def ids_of(html):
    return [m.group(1) for m in ID_RE.finditer(html)]


print("== 1. JS 取的 id 必须在本页存在 ==")
bad = []
for label, html in HTML.items():
    if not html:
        continue
    present = set(ids_of(html))
    js = "\n".join(JS_BLOCK.findall(html))
    wanted = set(GET_BY_ID.findall(js))
    # 模板里 id 是服务端拼的（如 rv-{{ bug.id }}），静态正则取不到占位符里的变量，
    # 这里只比对"取到的整串"与页面上的 id 字符串，拼错才会落到 missing。
    missing = sorted(w for w in wanted if w not in present)
    if missing:
        bad.append(f"{label}: {missing}")
check(f"{len(HTML)} 个页面无悬空 getElementById", not bad, "；".join(bad))

print("\n== 2. 同一页不能有重复 id ==")
bad = []
for label, html in HTML.items():
    if not html:
        continue
    seen, dup = set(), []
    for i in ids_of(html):
        if i in seen and i not in dup:
            dup.append(i)
        seen.add(i)
    if dup:
        bad.append(f"{label}: {dup}")
check(f"{len(HTML)} 个页面 id 唯一", not bad, "；".join(bad))

print("\n== 3. 点开才发请求的入口（data-copy / 原始报文）==")
bad = []
copy_values = []
for label, html in HTML.items():
    if not html:
        continue
    for val in re.findall(r'data-copy="([^"]*)"', html):
        copy_values.append(val)
        if not val.strip():
            bad.append(f"{label} 空 data-copy")
check("data-copy 的值都不为空", not bad, "；".join(bad) if bad else f"{len(copy_values)} 处")

dead = []
copy_urls = set()
for label, html in HTML.items():
    copy_urls |= set(re.findall(r'data-copy-url="([^"]+)"', html))
if copy_urls:
    for url in sorted(copy_urls)[:3]:
        r = client.get(url)
        if r.status_code != 200:
            dead.append(f"{url} → {r.status_code}")
    check(f"{min(len(copy_urls), 3)} 个 data-copy-url 可取到原文", not dead,
          "；".join(dead) if dead else f"共 {len(copy_urls)} 个")
else:
    skip("data-copy-url", "当前没有页面使用这个属性")

raw_links = set()
for html in HTML.values():
    raw_links |= set(re.findall(r'href="(/packets/\d+/(?:raw|download)[^"]*)"', html))
dead = []
for url in sorted(raw_links)[:3]:
    r = client.get(url)
    if r.status_code != 200:
        dead.append(f"{url} → {r.status_code}")
if raw_links:
    check("数据包原始报文/下载链接可访问", not dead, "；".join(dead) if dead else f"{len(raw_links)} 个")
else:
    skip("数据包链接", "库里页面没有挂数据包")

print("\n== 4. 表单 action 必须是已注册路由 ==")
adapter = platform.app.url_map.bind("localhost")


def form_entries(html):
    for m in re.finditer(r"<form([^>]*)>", html):
        attrs = m.group(1)
        action = re.search(r'action="([^"]*)"', attrs)
        method = re.search(r'method="([^"]*)"', attrs)
        yield (action.group(1) if action else "",
               (method.group(1) if method else "get").lower())


bad, total = [], 0
for label, html in HTML.items():
    if not html:
        continue
    for action, method in form_entries(html):
        if not action:                       # 无 action = 提交当前 URL
            continue
        total += 1
        parts = urlsplit(action)
        try:
            adapter.match(parts.path, method=method.upper())
        except Exception as exc:             # NotFound / MethodNotAllowed
            bad.append(f"{label} {method} {parts.path} ({type(exc).__name__})")
check(f"{total} 个表单 action 都能路由", not bad, "；".join(bad))

print("\n== 5. 注入 JS 的数据结构 ==")
tree_html = HTML.get("接口树", "")
m = re.search(r"const ITFS = (\[.*?\]);\n", tree_html, re.S)
if m:
    try:
        itfs = json.loads(m.group(1))
        parsed = True
    except ValueError as exc:
        itfs, parsed = [], False
        check("ITFS 是合法 JSON", False, str(exc)[:60])
    if parsed:
        n_db = sql_count("SELECT COUNT(*) FROM interfaces WHERE project_id=?", (PID,))
        check("ITFS 可解析且条数与库一致", len(itfs) == n_db, f"{len(itfs)} / 库内 {n_db}")
        # 前端 redraw() 用这三个字段做搜索，renderTree 用 id/path/method/verify_status
        need = {"id", "path", "name", "method", "module", "verify_status", "host_used"}
        missing = [i.get("id") for i in itfs if not need <= set(i)]
        check("ITFS 每条都带前端要用的字段", not missing,
              f"缺字段的接口 {missing[:5]}" if missing else f"{len(itfs)} 条")
        bad_vals = [i["id"] for i in itfs
                    if not isinstance(i.get("path"), str) or i.get("method") not in
                    ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")]
        check("ITFS 的 path/method 是渲染树能用的值", not bad_vals, str(bad_vals[:5]))
        # 树的 JS 用中文/斜杠拼节点，路径里不能有未转义的双引号（JSON 已解析，此项用原串兜底）
        check("ITFS 原串不含 NaN/undefined",
              "NaN" not in m.group(1) and "undefined" not in m.group(1))
    for var, pat in (("PROJECT_ID", r"const PROJECT_ID = (\d+);"),
                     ("MULTI_HOST", r"const MULTI_HOST = (true|false);"),
                     ("ENV_ID", r"const ENV_ID = (null|\d+);")):
        check(f"{var} 注入的是合法字面量", re.search(pat, tree_html) is not None)
else:
    skip("接口树数据", "树视图页没有 ITFS")

print("\n== 6. 批量操作控件的关联 ==")
for label in ("Bug tab", "审核队列"):
    html = HTML.get(label, "")
    if not html:
        continue
    cards = len(re.findall(r'class="bug-card', html))
    boxes = len(re.findall(r'class="cb-bug"', html))
    check(f"{label}：每张卡片一个勾选框", cards == boxes, f"卡片 {cards} / 勾选框 {boxes}")
    check(f"{label}：批量表单 id=bulk-form 存在", 'id="bulk-form"' in html)
    check(f"{label}：勾选框用 form 属性挂到批量表单",
          boxes == 0 or len(re.findall(r'form="bulk-form"', html)) >= boxes,
          f"{len(re.findall(r'form=.bulk-form.', html))} 处关联")
    check(f"{label}：每张卡片带 data-evi（批量提示无证据用）",
          cards == 0 or len(re.findall(r'data-evi="[01]"', html)) >= cards)
    for cls in ("bulk-count", "bulk-ops", "batch-comment"):
        check(f"{label}：{cls} 存在", cls in html)

print("\n== 7. 驳回必填原因依赖的控件 ==")
html = HTML.get("Bug 详情", "")
if html:
    m = re.search(r'<form[^>]*id="(rv-\d+)"', html)
    check("Bug 详情有单条审核表单 id=rv-<id>", m is not None)
    if m:
        check("审核表单挂着 name=comment 的输入控件（wbReject 靠它拦截空原因）",
              'name="comment"' in html and f'form="{m.group(1)}"' in html)
        check("审核表单挂着驳回分类选择", 'name="reject_category"' in html)
else:
    skip("驳回控件", "没有 Bug")

print("\n== 8. 分页链接保留筛选条件 ==")
CASES_TOTAL = sql_count("SELECT COUNT(*) FROM cases WHERE project_id=?", (PID,))
PAGE_SIZE = 50                        # lists.py：接口/用例/运行 50 条/页，Bug 分栏 20 条/页
if CASES_TOTAL > PAGE_SIZE:
    links = re.findall(r'href="(\?[^"]*page=\d+[^"]*)"', HTML.get("用例tab", ""))
    check("用例分页链接保留 tab", bool(links) and all("tab=cases" in ln for ln in links),
          f"{len(links)} 个链接：{links[:2]}")
    r = client.get(f"/projects/{PID}?tab=cases&page=2")
    check("用例第 2 页能打开", r.status_code == 200
          and "Traceback" not in r.get_data(as_text=True), r.status_code)
    # 筛选条件必须跟着翻页走：否则翻到第 2 页会悄悄回到全量
    filtered = sql_one("SELECT COUNT(*) FROM cases WHERE project_id=? AND priority='P0'", (PID,))
    if filtered and PAGE_SIZE < filtered:
        links = re.findall(r'href="(\?[^"]*page=\d+[^"]*)"',
                           client.get(f"/projects/{PID}?tab=cases&priority=P0")
                           .get_data(as_text=True))
        check("用例分页链接保留优先级筛选",
              bool(links) and all("priority=P0" in ln for ln in links), f"{links[:2]}")
    else:
        skip("用例筛选翻页", f"P0 只有 {filtered} 条")
else:
    skip("用例分页", f"用例只有 {CASES_TOTAL} 条，不足一页")

ITF_TOTAL = sql_count("SELECT COUNT(*) FROM interfaces WHERE project_id=?", (PID,))
if ITF_TOTAL > PAGE_SIZE:
    html = client.get(f"/projects/{PID}?tab=interfaces&method=GET").get_data(as_text=True)
    links = re.findall(r'href="(\?[^"]*page=\d+[^"]*)"', html)
    if links:
        check("接口分页链接保留方法筛选",
              all("method=GET" in ln for ln in links), f"{links[:2]}")
    else:
        skip("接口分页", "该筛选下只有一页")
else:
    skip("接口分页", f"接口只有 {ITF_TOTAL} 条")

print("\n== 9. 多选模块面板 ==")
html = HTML.get("用例tab", "")
panels = re.findall(r'<details class="ms">(.*?)</details>', html, re.S)
if panels:
    for body in panels:
        names = set(re.findall(r'name="(\w+)"', body))
        check("模块复选框统一用同一个 name（提交成重复键）", len(names) == 1, str(names))
        nums = re.findall(r'data-n="(\d+)"', body)
        check("每个模块带接口条数 data-n", len(nums) > 0, f"{len(nums)} 个")
        total = re.search(r'class="ms-hint" data-total="(\d+)"', body)
        check("面板底部有总数 data-total", total is not None,
              total.group(1) if total else "")
        check("面板有清空/应用按钮",
              'class="ms-clear' in body and "应用" in body)
else:
    skip("模块多选面板", "该页没有模块可筛")

print("\n== 10. 站内链接都能路由（抽样：详情页与列表页的表单外链）==")
dead, checked = [], 0
for label in ("文档tab", "接口列表", "用例tab", "运行tab"):
    html = HTML.get(label, "")
    for href in set(re.findall(r'href="(/[^"#]*)"', html)):
        if href.startswith(("/files/", "/static/", "/packets/")):
            continue
        checked += 1
        if checked > 40:
            break
        try:
            adapter.match(urlsplit(href).path, method="GET")
        except Exception:
            dead.append(f"{label} → {href}")
check(f"{min(checked, 40)} 个站内链接都能路由", not dead, "；".join(dead[:5]))

print("\n== 11. 页面不泄漏内部实现 ==")
bad = []
for label, html in HTML.items():
    if not html:
        continue
    for token in ("Traceback", "jinja2", "UndefinedError", "sqlite3.OperationalError",
                  "__pycache__"):
        if token in html:
            bad.append(f"{label}: {token}")
check("页面不含异常堆栈与内部路径", not bad, "；".join(bad))

print("\n" + ("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}"))
shutil.rmtree(TMP_UP, ignore_errors=True)
os.remove(TEST_DB)
sys.exit(1 if fails else 0)
