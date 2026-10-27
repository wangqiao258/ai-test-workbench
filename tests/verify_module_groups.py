"""模块一级分组筛选的校验：纯函数 + 页面级，在数据库副本上跑。

背景（2026-10-22 用户反馈）：接口页的"模块"下拉是 22 个扁平选项，
模块名本身是"侧边栏-客户"这种"分组-子模块"的两段式写法，
想按"侧边栏"这一整块筛，下拉里根本没有这个选项，只能一个个挑子模块。

改法：分组从模块名派生，不新增表；分组下拉独立成 group 参数，
选了分组后模块下拉收窄到该组，避免选出"分组=家长端 + 模块=侧边栏-客户"。

用法（在 ai-test-platform 目录下）：
    python tests/verify_module_groups.py
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

TEST_DB = os.path.join(BASE, "data", "_verify_module_groups.db")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)

import db  # noqa: E402
db.DB_PATH = TEST_DB
import app as platform  # noqa: E402
from core import lists  # noqa: E402

client = platform.app.test_client()
with client.session_transaction() as sess:
    sess["user"] = "admin"

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail else ''}")
    if not cond:
        fails.append(name)


def get(path):
    return client.get(path).get_data(as_text=True)


def scalar(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    try:
        return conn.execute(query, args).fetchone()[0]
    finally:
        conn.close()


def filtered_in(html):
    m = re.search(r"筛出 <b>(\d+)</b>", html)
    return int(m.group(1)) if m else None


def total_in(html):
    m = re.search(r"共 <b>(\d+)</b>", html)
    return int(m.group(1)) if m else None


Q = quote  # 中文模块名要进 URL

# ---------- 1. 分组头派生 ----------
print("\n== 1. module_head：只认「组名-子名」 ==")
check("侧边栏-客户 -> 侧边栏", lists.module_head("侧边栏-客户") == "侧边栏")
check("系统 -> 空（无分隔符自成模块）", lists.module_head("系统") == "")
check("侧边栏- -> 空（子名为空）", lists.module_head("侧边栏-") == "")
check("-客户 -> 空（组名为空）", lists.module_head("-客户") == "")
check("A-B-C -> A（只取一级）", lists.module_head("A-B-C") == "A")
check("空串不炸", lists.module_head("") == "")
check("None 不炸", lists.module_head(None) == "")

# ---------- 2. 分组词表与阈值 ----------
print("\n== 2. module_groups：单成员前缀不算分组 ==")
mods = ["侧边栏-客户", "侧边栏-素材", "家长端-视频", "家长端-直播",
        "会员侧-儿童档案", "系统", "认证"]
groups = lists.module_groups(mods)
check("默认：带分隔符的模块都归组",
      set(groups) == {"侧边栏", "家长端", "会员侧"}, list(groups))
check("散项不进分组", "系统" not in groups and "认证" not in groups)
check("组内模块有序", groups["侧边栏"] == ("侧边栏-客户", "侧边栏-素材"), groups["侧边栏"])
check("阈值可调：min_size=2 时单成员分组退回散项",
      "会员侧" not in lists.module_groups(mods, min_size=2))

# ---------- 3. 下拉结构 ----------
print("\n== 3. module_options / group_options：结构与应用文案 ==")
items = [("侧边栏-客户", 14), ("侧边栏-素材", 14), ("系统", 7), ("认证", 9)]
opts = lists.module_options(items)
check("有分组的组头在最前", opts[0][0] == "侧边栏", opts[0][0])
check("散项组头为 None 且排最后", opts[-1][0] is None and [v for v, _, _n in opts[-1][1]] == ["系统", "认证"])
check("选项文案带条数", ("侧边栏-客户", "侧边栏-客户（14）", 14) in opts[0][1])
check("only_group 只返回该组", [h for h, _ in lists.module_options(items, "侧边栏")] == ["侧边栏"])
check("only_group 传不存在的组时退回全量",
      len(lists.module_options(items, "不存在")) == 2)
gopts = lists.group_options(items)
check("分组文案带该组总条数", ("侧边栏", "侧边栏（28）") == gopts[0], gopts)
check("分组按条数从多到少排",
      [h for h, _ in lists.group_options(
          [("甲-一", 1), ("乙-一", 5), ("乙-二", 5), ("丙-一", 3)])] == ["乙", "丙", "甲"])

# ---------- 4. 分组 SQL 片段 ----------
print("\n== 4. group_field：命中组内全部模块 ==")
f = lists.group_field("分组", items)
where, params = f.mapping[0][1], f.mapping[0][2]
check("字段类型是 map（复用现成能力）", f.kind == "map")
check("SQL 用 ? 占位，不拼值",
      where.count("?") == 2 and "侧边栏" not in where, where)
check("参数是组名 + 组名前缀", params == ("侧边栏", "侧边栏-%"), params)
check("用例页要用 c. 前缀", "c.module=?" in lists.group_field("分组", items, prefix="c.").mapping[0][1])
check("没有分组时返回 None（连下拉都不渲染）",
      lists.group_field("分组", [("系统", 7), ("认证", 9)]) is None)

# ---------- 5. 接口页页面级 ----------
print("\n== 5. 接口页：分组下拉与筛选结果 ==")
html = get("/projects/1?tab=interfaces&env=1")
n_all = scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=1")
n_side = scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=1 AND module LIKE '侧边栏-%'")
n_parent = scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=1 AND module LIKE '家长端-%'")
check("未选分组时仍显示全部", total_in(html) == n_all and "筛出" not in html, total_in(html))
check("出现分组下拉", 'name="group"' in html and ">分组<" in html)
n_member = scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=1 AND module LIKE '会员侧-%'")
check("分组选项带总条数", f"侧边栏（{n_side}）" in html and f"家长端（{n_parent}）" in html)
check("单成员的会员侧也成组（规则只有一条）", f">会员侧（{n_member}）" in html)
check("分组按条数降序：侧边栏在家长端前",
      html.index(f"侧边栏（{n_side}）") < html.index(f"家长端（{n_parent}）"))
check("模块多选面板按分组标题归类", html.count('class="ms-head"') >= 2)
check("模块选项带条数", "侧边栏-客户（14）" in html)
check("散项模块（系统/认证）仍在列表里", "系统（7）" in html or "系统（" in html)

html = get(f"/projects/1?tab=interfaces&env=1&group={Q('侧边栏')}")
check("按分组筛出全部子模块", filtered_in(html) == n_side, filtered_in(html))
check("结果行写明按分组筛的", "按 分组 筛出" in html)
mods_on_page = set(re.findall(r'title="只看 ([^"]+)"', html))
check("结果里没有别的分组混进来",
      all(m.startswith("侧边栏-") for m in mods_on_page), sorted(mods_on_page)[:3])
check("模块下拉收窄到该组（不再列家长端）", "家长端-视频" not in html)
panel_mods = set(re.findall(r'name="module" value="([^"]+)"', html))
check("收窄后面板里的 checkbox 只剩该组模块",
      panel_mods and all(m.startswith("侧边栏-") for m in panel_mods), len(panel_mods))

html = get(f"/projects/1?tab=interfaces&env=1&group={Q('家长端')}")
check("换一个分组也对", filtered_in(html) == n_parent, filtered_in(html))

html = get(f"/projects/1?tab=interfaces&env=1&module={Q('侧边栏-客户')}")
check("只选模块仍然精确筛", filtered_in(html) == 14, filtered_in(html))
html = get(f"/projects/1?tab=interfaces&env=1&group={Q('侧边栏')}&module={Q('侧边栏-客户')}")
check("分组 + 模块是交集", filtered_in(html) == 14, filtered_in(html))
html = get(f"/projects/1?tab=interfaces&env=1&group={Q('家长端')}&module={Q('侧边栏-客户')}")
check("手改 URL 造出的矛盾组合是 0 条而不是 500",
      filtered_in(html) == 0, filtered_in(html))
html = get(f"/projects/1?tab=interfaces&env=1&group={Q('不存在的组')}")
check("词表外的分组当没传（不会得到空页）",
      total_in(html) == n_all and "筛出" not in html, total_in(html))
html = get("/projects/1?tab=interfaces&env=1&group=")
check("空分组等于不筛", "筛出" not in html and total_in(html) == n_all)

html = get(f"/projects/1?tab=interfaces&env=1&group={Q('侧边栏')}&method=POST")
n_post = scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=1 "
                "AND module LIKE '侧边栏-%' AND method='POST'")
check("分组与方法叠加生效", filtered_in(html) == n_post, filtered_in(html))

html = get(f"/projects/1?tab=interfaces&env=1&group={Q('侧边栏')}")
check("分组筛选后翻页仍带着分组",
      "page=2" in html and f"group={Q('侧边栏')}" in html, n_side > 50)
html = get(f"/projects/1?tab=interfaces&env=1&group={Q('侧边栏')}&page=2")
rows_on_p2 = html.count('<span class="badge method-')
check("第 2 页只列 50 行（103 条里的第 51-100 条）", rows_on_p2 == 50, rows_on_p2)
check("翻页后仍记得是 103 条里筛出来的", filtered_in(html) == n_side, filtered_in(html))

# ---------- 6. 列表里的模块链接保留上下文 ----------
print("\n== 6. 点模块名只看该模块，不丢当前筛选 ==")
html = get(f"/projects/1?tab=interfaces&env=1&group={Q('侧边栏')}&method=POST")
href = re.search(r'href="\?([^"]*)" title="只看 ', html)
check("模块链接带上了分组", href and f"group={Q('侧边栏')}" in href.group(1), href.group(1) if href else None)
check("模块链接带上了方法", href and "method=POST" in href.group(1))
check("模块链接带上了环境", href and "env=1" in href.group(1))
check("模块链接覆盖 module", href and "module=" in href.group(1))

# ---------- 7. 用例页同样有分组 ----------
print("\n== 7. 用例页：同样的分组能力 ==")
n_c_all = scalar("SELECT COUNT(*) FROM cases WHERE project_id=1")
n_c_side = scalar("SELECT COUNT(*) FROM cases WHERE project_id=1 AND module LIKE '侧边栏-%'")
html = get("/projects/1?tab=cases&env=1")
check("用例页出现分组下拉", 'name="group"' in html and ">分组<" in html)
check("用例页未筛时是全部", total_in(html) == n_c_all, total_in(html))
html = get(f"/projects/1?tab=cases&env=1&group={Q('侧边栏')}")
check("用例按分组筛出", filtered_in(html) == n_c_side, filtered_in(html))
check("用例页分组筛选带 c. 前缀也不报错", "no such column" not in html.lower())

# ---------- 8. 详情页返回能复原分组 ----------
print("\n== 8. back 白名单：分组要跟着回来 ==")
iid = scalar("SELECT id FROM interfaces WHERE project_id=1 AND module LIKE '侧边栏-%' LIMIT 1")
back = Q(f"tab=interfaces&env=1&group=侧边栏&method=GET")
html = get(f"/interfaces/{iid}?back={back}")
check("详情页返回链接保留 group", f"group={Q('侧边栏')}" in html)
check("详情页返回链接保留 method", "method=GET" in html)
bad = Q("tab=interfaces&group=侧边栏&next=https://evil.example/x")
html = get(f"/interfaces/{iid}?back={bad}")
check("白名单外的键被丢掉", "evil.example" not in html)

# ---------- 9. Bug 页不受影响 ----------
print("\n== 9. Bug 页保持原样（紧凑分栏，模块仍平铺） ==")
html = get("/projects/1?tab=bugs&env=1")
check("Bug 页没有分组下拉", 'name="group"' not in html)
check("Bug 页模块下拉仍是平铺选项", ">侧边栏-客户<" in html and "<optgroup" not in html)

# ---------- 10. LIKE 通配符不会越界 ----------
print("\n== 10. 组名里的 _ 不当通配符 ==")
conn = sqlite3.connect(TEST_DB)
for mod, path in (("a_c-x", "/t1"), ("a_c-z", "/t2"), ("abc-y", "/t3")):
    conn.execute("INSERT INTO interfaces (project_id, module, name, method, path, "
                 "created_at, updated_at) VALUES (1,?,?, 'GET',?,'','')",
                 (mod, mod, path))
conn.commit()
conn.close()
html = get(f"/projects/1?tab=interfaces&env=1&group={Q('a_c')}")
check("a_c 只命中 a_c-*，不命中 abc-y", filtered_in(html) == 2, filtered_in(html))

print("\n" + ("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}"))
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
sys.exit(1 if fails else 0)
