"""模块多选：网页筛选 + API 多值读取的校验（数据库副本，不污染真实数据）。

起因（2026-10-22 用户）："AI 可以一次根据多个模块接口以及关联的测试用例分析，生成新的测试用例"。
改前实测：?module=A&module=B 只用了第一个值——网页筛出 14 条（应 28），
/api/coverage 返回 {"module": "A", "interfaces": 14}，第二个模块被静默丢掉、无任何报错。
对 AI 来说这是最危险的错法：它以为拿全了。

覆盖三层：
1. core：build() 的多值 SQL、词表过滤、去重、qs_with 保留重复键
2. 网页：多选面板、结果行文案、分页/详情链接、分组收窄的防丢处理
3. API：interfaces / cases / coverage 的多值与 group 参数，以及单值兼容

用法（在 ai-test-platform 目录下）：
    python tests/verify_multi_select.py
"""
import os
import re
import shutil
import sqlite3
import sys
from urllib.parse import quote

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_verify_multi.db")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)

import db  # noqa: E402
db.DB_PATH = TEST_DB
import app as platform  # noqa: E402
from core.filters import Field, build, qs_with  # noqa: E402
from core import lists  # noqa: E402
from werkzeug.datastructures import MultiDict  # noqa: E402

client = platform.app.test_client()
with client.session_transaction() as sess:
    sess["user"] = "admin"

TOKEN = open(os.path.join(BASE, "data", "api-token.txt"), encoding="utf-8").read().strip()
H = {"X-API-Token": TOKEN}

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail else ''}")
    if not cond:
        fails.append(name)


def get(path):
    return client.get(path).get_data(as_text=True)


def api(path):
    r = client.get(path, headers=H)
    try:
        return r.status_code, r.get_json()
    except Exception:
        return r.status_code, None


def scalar(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    try:
        return conn.execute(query, args).fetchone()[0]
    finally:
        conn.close()


def filtered_in(html):
    m = re.search(r"筛出 <b>(\d+)</b>", html)
    return int(m.group(1)) if m else None


Q = quote
A, B = "侧边栏-客户", "侧边栏-素材"

# ---------- 1. build()：多值 SQL ----------
print("\n== 1. build()：多值参数变成 IN ==")
spec = (Field("module", "eq", col="module", vocab=("A", "B", "C"), label="模块", multi=True),)

f = build(spec, MultiDict([("module", "A")]))
check("单值仍用 =（不退化成一元 IN）", f["where"] == ["module=?"], f["where"])
check("单值参数", f["params"] == ["A"])
check("单值 state 是 tuple", f["state"]["module"] == ("A",), f["state"]["module"])
check("单选不写「N 个」", f["active"] == ["模块"], f["active"])

f = build(spec, MultiDict([("module", "A"), ("module", "B")]))
check("两个值用 IN (?,?)", f["where"] == ["module IN (?,?)"], f["where"])
check("参数顺序跟着 URL", f["params"] == ["A", "B"], f["params"])
check("多选标签写个数", f["active"] == ["模块（2 个）"], f["active"])

f = build(spec, MultiDict([("module", "A"), ("module", "A")]))
check("重复值去重后回到单值", f["where"] == ["module=?"] and f["params"] == ["A"], f["where"])

f = build(spec, MultiDict([("module", "")]))
check("空值等于没传", f["where"] == [] and f["state"]["module"] == ())
f = build(spec, MultiDict())
check("不传等于没传", f["where"] == [])

f = build(spec, MultiDict([("module", "A"), ("module", "乱写"), ("module", "C")]))
check("词表外的值挑掉，合法值留下", f["params"] == ["A", "C"], f["params"])
f = build(spec, MultiDict([("module", "乱写1"), ("module", "乱写2")]))
check("全都不在词表里等于没传", f["where"] == [], f["where"])

f = build(spec, {"module": "B"})
check("普通 dict（无 getlist）也能用", f["params"] == ["B"], f["params"])

try:
    Field("x", "map", mapping=(("a", "1=1", ()),), multi=True)
    bad = False
except ValueError:
    bad = True
check("multi 配 map 会直接报错（不支持就别装作支持）", bad)

# ---------- 2. qs_with：多值不能丢 ----------
print("\n== 2. qs_with：多值原样保留 ==")
md = MultiDict([("tab", "interfaces"), ("page", "2"),
                ("module", "A"), ("module", "B")])
q = qs_with(md, page="")
check("翻页时两个 module 都在", q.count("module=") == 2, q)
check("页码被删掉", "page=" not in q, q)
q = qs_with(md, module="A")
check("覆盖成单值只剩一个 module", q.count("module=") == 1, q)
q = qs_with(md, module=[A, B])
check("覆盖成 list 会展开成两个", q.count("module=") == 2, q)

# ---------- 3. 网页：接口页多选 ----------
print("\n== 3. 接口页：多选筛选 ==")
n_a = scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=1 AND module=?", (A,))
n_b = scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=1 AND module=?", (B,))
n_ab = scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=1 AND module IN (?,?)", (A, B))

html = get(f"/projects/1?tab=interfaces&env=1&module={Q(A)}&module={Q(B)}")
check("两个模块是并集", filtered_in(html) == n_ab, f"{filtered_in(html)} vs {n_a}+{n_b}")
check("结果行标出选了几个", "按 模块（2 个）" in html)
check("面板里两个都勾上",
      bool(re.search(r'value="侧边栏-客户"[^>]*checked', html))
      and bool(re.search(r'value="侧边栏-素材"[^>]*checked', html)))
check("summary 显示「已选 2 个」", "已选 2 个" in html)
check("面板底部算出接口数", f"2 个模块 · {n_ab} 条接口" in html)

html = get(f"/projects/1?tab=interfaces&env=1&module={Q(A)}")
check("单个模块仍然精确", filtered_in(html) == n_a, filtered_in(html))
check("单个时 summary 直接写模块名", f"<span class=\"ms-val\">{A}</span>" in html)

html = get("/projects/1?tab=interfaces&env=1")
check("不选时 summary 是「全部模块」", "全部模块" in html)
check("面板里有全部 22 个 checkbox",
      html.count('name="module" value=') == scalar("SELECT COUNT(DISTINCT module) FROM interfaces WHERE project_id=1"))

# 分页与详情链接（接口页 50 条/页，凑够 5 个模块 = 56 条才有第二页）
five_mods = ["侧边栏-客户", "侧边栏-素材", "侧边栏-视频", "侧边栏-学习", "侧边栏-基础"]
url5 = "&".join(f"module={Q(m)}" for m in five_mods)
html = get(f"/projects/1?tab=interfaces&env=1&{url5}")
pager_html = html[html.find('class="pager"'):] if 'class="pager"' in html else ""
check("56 条时出现第二页", "page=2" in pager_html, pager_html[:60])
check("分页链接保留全部 5 个模块",
      all(Q(m) in pager_html for m in five_mods), pager_html[:160])

html = get(f"/projects/1?tab=interfaces&env=1&module={Q(A)}&module={Q(B)}")
href = re.search(r'href="\?([^"]*)" title="只看 ', html)
check("点模块名把多选压成单值（只看这一个）",
      href and href.group(1).count("module=") == 1, href.group(1) if href else None)
check("点模块名保留其它条件", href and "env=1" in href.group(1) and "tab=interfaces" in href.group(1))

iid = scalar("SELECT id FROM interfaces WHERE project_id=1 AND module=?", (A,))
back = Q(f"tab=interfaces&env=1&module={A}&module={B}")
html = get(f"/interfaces/{iid}?back={back}")
check("详情页 back 带回两个模块",
      html.count(f"module={Q(A)}") >= 1 and html.count(f"module={Q(B)}") >= 1)

# ---------- 4. 网页：分组与多选的关系 ----------
print("\n== 4. 分组 + 多选：收窄与防丢 ==")
html = get(f"/projects/1?tab=interfaces&env=1&group={Q('侧边栏')}&module={Q(A)}&module={Q(B)}")
panel = set(re.findall(r'name="module" value="([^"]+)"', html))
check("分组已选且模块都在该组 → 面板收窄",
      panel and all(p.startswith("侧边栏-") for p in panel), len(panel))
check("分组 + 多选是交集", filtered_in(html) == n_ab, filtered_in(html))

html = get(f"/projects/1?tab=interfaces&env=1&group={Q('家长端')}&module={Q(A)}")
panel = set(re.findall(r'name="module" value="([^"]+)"', html))
check("已选模块跨组时退回全量面板（否则提交会把它静默丢掉）",
      A in panel and any(p.startswith("家长端-") for p in panel), len(panel))
check("跨组矛盾组合是 0 条而不是 500", filtered_in(html) == 0, filtered_in(html))

# ---------- 5. 网页：用例页与 Bug 页 ----------
print("\n== 5. 用例页多选，Bug 页保持单选 ==")
n_ca = scalar("SELECT COUNT(*) FROM cases WHERE project_id=1 AND module IN (?,?)", (A, B))
html = get(f"/projects/1?tab=cases&env=1&module={Q(A)}&module={Q(B)}")
check("用例页多选并集", filtered_in(html) == n_ca, filtered_in(html))
check("用例页也有多选面板", 'class="ms"' in html)

html = get("/projects/1?tab=bugs&env=1")
check("Bug 页没有多选面板", 'class="ms"' not in html)
check("Bug 页模块仍是单选 select", 'name="module"' in html and "checkbox" not in html.split('name="module"')[0][-200:])

# ---------- 6. API：多值 ----------
print("\n== 6. API：interfaces / cases ==")
code, data = api(f"/api/interfaces?project_id=1&module={Q(A)}&module={Q(B)}&fields=meta")
check("接口多值返回并集", code == 200 and len(data) == n_ab, len(data) if data else code)
code, data = api(f"/api/interfaces?project_id=1&module={Q(A)}&fields=meta")
check("接口单值仍然兼容", len(data) == n_a, len(data))
code, data = api("/api/interfaces?project_id=1&fields=meta")
check("不传 module 返回全量", len(data) == scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=1"), len(data))
code, data = api(f"/api/interfaces?project_id=1&module=&fields=meta")
check("空 module 不筛", len(data) == scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=1"), len(data))

code, data = api(f"/api/cases?project_id=1&module={Q(A)}&module={Q(B)}&fields=summary")
check("用例多值返回并集", len(data) == n_ca, len(data))
code, data = api(f"/api/cases?project_id=1&module={Q(A)}&fields=summary")
check("用例单值仍然兼容",
      len(data) == scalar("SELECT COUNT(*) FROM cases WHERE project_id=1 AND module=?", (A,)), len(data))

# ---------- 7. API：coverage 的多模块与分组 ----------
print("\n== 7. API：coverage 多模块 / 分组 ==")
n_side = scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=1 AND module LIKE '侧边栏-%'")
code, d = api(f"/api/coverage?project_id=1&module={Q(A)}&module={Q(B)}")
check("coverage 多模块接口数", d["totals"]["interfaces"] == n_ab, d["totals"]["interfaces"])
check("coverage 回显 modules 列表", d["modules"] == [A, B], d["modules"])
check("coverage 多模块时 module 兼容字段为空", d["module"] is None, d["module"])
check("多模块的用例数 = 两模块之和",
      d["totals"]["cases"] == scalar(
          "SELECT COUNT(*) FROM cases WHERE project_id=1 AND module IN (?,?)", (A, B)),
      d["totals"]["cases"])

code, d = api(f"/api/coverage?project_id=1&group={Q('侧边栏')}")
check("coverage 按分组取整块", d["totals"]["interfaces"] == n_side, d["totals"]["interfaces"])
check("coverage 回显 group", d["group"] == "侧边栏", d["group"])
check("分组取的接口全是该组",
      all(i["module"].startswith("侧边栏-") for i in d["interfaces"]))
check("分组取的用例数对得上",
      d["totals"]["cases"] == scalar(
          "SELECT COUNT(*) FROM cases WHERE project_id=1 AND module LIKE '侧边栏-%'"),
      d["totals"]["cases"])

code, d = api("/api/coverage?project_id=1")
check("coverage 不传范围 = 全项目",
      d["totals"]["interfaces"] == scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=1"),
      d["totals"]["interfaces"])
check("project_id 仍必填", api("/api/coverage")[0] == 400)

code, d = api(f"/api/coverage?project_id=1&module={Q(A)}&group={Q('家长端')}")
check("module 与 group 同时传时 module 优先", d["totals"]["interfaces"] == n_a, d["totals"]["interfaces"])

code, d = api(f"/api/coverage?project_id=1&group={Q('家长端')}&only_missing=1")
check("only_missing 与 group 叠加不报错", code == 200 and isinstance(d["interfaces"], list), code)

# ---------- 8. 边界 ----------
print("\n== 8. 边界 ==")
html = get(f"/projects/1?tab=interfaces&env=1&module={Q(A)}&module={Q(A)}")
check("同名模块传两次仍是那一份", filtered_in(html) == n_a, filtered_in(html))
html = get(f"/projects/1?tab=interfaces&env=1&module={Q(A)}&module={Q('不存在的模块')}")
check("混入不存在的模块时安静忽略它", filtered_in(html) == n_a, filtered_in(html))
five = "&".join(f"module={Q(m)}" for m in
                ["侧边栏-客户", "侧边栏-素材", "侧边栏-视频", "侧边栏-学习", "侧边栏-基础"])
html = get(f"/projects/1?tab=interfaces&env=1&{five}")
check("5 个模块的 URL 正常工作",
      filtered_in(html) == scalar(
          "SELECT COUNT(*) FROM interfaces WHERE project_id=1 AND module IN "
          "('侧边栏-客户','侧边栏-素材','侧边栏-视频','侧边栏-学习','侧边栏-基础')"),
      filtered_in(html))

print("\n" + ("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}"))
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
sys.exit(1 if fails else 0)
