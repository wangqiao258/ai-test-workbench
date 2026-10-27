"""Bug 左右分栏的页面级校验：在数据库副本上跑，不污染真实数据。

覆盖 2026-10-22 的分栏改造：
1) 缺省选中当前页第一条，?sel=<id> 指定选中，选中卡片高亮
2) sel 指向别的项目 / 不存在 / 非数字时一律回退，不越权读别项目数据
3) 左栏只放纯链接卡片（按钮全在右栏操作条），每页 20 条
4) 翻页清空 sel；卡片链接保留当前筛选
5) 审核、改状态后 back 回到同一条（sel 已进 back 白名单）

用法（在 ai-test-platform 目录下）：
    python tests/verify_split.py
"""
import os
import re
import shutil
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_verify_split.db")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)

import db  # noqa: E402
db.DB_PATH = TEST_DB
import app as platform  # noqa: E402
from core.filters import clean_qs  # noqa: E402

client = platform.app.test_client()
with client.session_transaction() as sess:
    sess["user"] = "admin"

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail else ''}")
    if not cond:
        fails.append(name)


def get(url):
    return client.get(url).get_data(as_text=True)


def sql(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(query, args).fetchall()
    finally:
        conn.close()


def exec_sql(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    try:
        conn.execute(query, args)
        conn.commit()
    finally:
        conn.close()


# 卡片链接形如 href="?tab=bugs&amp;sel=39"：Jinja 把 & 转义成 &amp;，
# 所以正则限定在 href 属性内，避免误取 back 参数里的编码值
CARD_SEL = r'href="\?[^"]*sel=(\d+)"'
# 加了批量后卡片是 <div class="bug-card active"> 包着 <a class="bc-link" href="?...">，
# class 和 href 不再同一个标签，要跨标签匹配（非贪婪，只会取到本卡片内的那个链接）
ACTIVE_SEL = r'class="bug-card active"[\s\S]*?href="\?[^"]*sel=(\d+)"'


def ids_of(html):
    return [int(x) for x in re.findall(CARD_SEL, html)]


def active_of(html):
    m = re.search(ACTIVE_SEL, html)
    return int(m.group(1)) if m else None


print("== 1. 缺省选中与指定选中 ==")
html = get("/projects/1?tab=bugs")
ids = ids_of(html)
check("左栏每页 20 条", len(ids) == 20, f"{len(ids)} 条")
check("分页显示 2 页", "第 1 / 2 页" in html)
check("缺省选中当前页第一条", active_of(html) == ids[0], f"active={active_of(html)}")
check("右栏有详情操作条", 'class="detail-actions"' in html)
check("左栏卡片是纯链接（按钮不下沉到列表）",
      'class="bug-card' in html and "mini danger" not in html)

html_pick = get(f"/projects/1?tab=bugs&sel={ids[1]}")
check("?sel= 指定后选中该条", active_of(html_pick) == ids[1], f"active={active_of(html_pick)}")
check("右栏标题跟着换", f"#{ids[1]}" in html_pick)

print("\n== 2. sel 的边界与越权 ==")
check("sel 在 back 白名单内", clean_qs("tab=bugs&sel=5&evil=1") == "tab=bugs&sel=5")

html_missing = get("/projects/1?tab=bugs&sel=999999")
check("sel 不存在时回退第一条", active_of(html_missing) == ids[0])

html_bad = get("/projects/1?tab=bugs&sel=abc")
check("sel 非数字时回退第一条", active_of(html_bad) == ids[0])

# 造第二个项目 + 一条 Bug：验证 sel 不能把别的项目的数据读进本项目的右栏
exec_sql("INSERT INTO projects (name, description, created_at) VALUES (?,?,?)",
         ("越权测试项目", "verify_split 造", "2026-10-22 00:00:00"))
other_pid = sql("SELECT MAX(id) FROM projects")[0][0]
exec_sql("""INSERT INTO bugs (project_id, module, title, steps, severity,
                             review_status, reported_at, created_by, evidence, review_comment,
                             created_at, updated_at)
            SELECT ?, module, ?, steps, severity, review_status, reported_at, created_by,
                   evidence, review_comment, created_at, updated_at
            FROM bugs WHERE id=?""",
         (other_pid, "【别的项目】不该出现在项目一", ids[0]))
other_bid = sql("SELECT MAX(id) FROM bugs")[0][0]
html_cross = get(f"/projects/1?tab=bugs&sel={other_bid}")
check("sel 指向别的项目：右栏不渲染该条", "【别的项目】" not in html_cross)
check("sel 指向别的项目：回退到本项目第一条", active_of(html_cross) == ids[0])

print("\n== 3. 筛选与分页的配合 ==")
pending_html = get("/projects/1?tab=bugs&progress=pending")
card_hrefs = re.findall(r'href="\?([^"]*sel=\d+[^"]*)"', pending_html)
check("卡片链接保留当前筛选", bool(card_hrefs) and all("progress=pending" in h for h in card_hrefs),
      f"{len(card_hrefs)} 张卡片")

picked = get(f"/projects/1?tab=bugs&sel={ids[1]}")
page_hrefs = re.findall(r'href="\?([^"]*page=\d+[^"]*)"', picked)
check("翻页链接清空 sel", bool(page_hrefs) and all("sel=" not in h for h in page_hrefs),
      f"{len(page_hrefs)} 个分页链接")

page2_ids = ids_of(get("/projects/1?tab=bugs&page=2"))
# 期望值从库里算：Bug 条数会增长，写死 3 会在数据变化后变成假失败
total = sql("SELECT COUNT(*) FROM bugs WHERE project_id=1 "
            "AND review_status!='rejected' AND reported_at=''")[0][0]
want2 = min(20, max(0, total - 20))
check("第 2 页条数正确", len(page2_ids) == want2,
      f"{len(page2_ids)} 条 / 期望 {want2}（默认视图共 {total}）")
check("第 2 页与第 1 页不重叠", not (set(page2_ids) & set(ids)))

print("\n== 4. 操作后回到同一条 ==")
pend = sql("SELECT id FROM bugs WHERE project_id=1 AND review_status='pending' "
           "ORDER BY id LIMIT 1")[0][0]
r = client.post(f"/review/bug/{pend}",
                data={"action": "approve", "comment": "", "back": f"tab=bugs&sel={pend}"})
loc = r.headers.get("Location", "")
check("审核后 back 带回 sel", r.status_code == 302 and f"sel={pend}" in loc, loc)

# 通过之后进入"待上报"，这一步用来验回跳（status 轴已废弃，不再有改状态）
r2 = client.post(f"/bugs/{pend}/reported",
                 data={"value": "1", "back": f"tab=bugs&sel={pend}"})
loc2 = r2.headers.get("Location", "")
check("标记已上报后 back 带回 sel", r2.status_code == 302 and f"sel={pend}" in loc2, loc2)
check("reported_at 已写入", bool(sql("SELECT reported_at FROM bugs WHERE id=?", (pend,))[0][0]))

html_after = get(f"/projects/1?tab=bugs&progress=all&sel={pend}")
check("回跳后右栏仍是同一条", f"#{pend}" in html_after)

print("\n== 5. 独立详情页仍然可用 ==")
det = get(f"/bugs/{pend}")
check("详情页 200 且有操作条", 'class="detail-actions"' in det)
check("详情页有返回列表链接", "← 返回 Bug 列表" in det)
check("详情页标题正确", f"#{pend}" in det)

print("\n== 6. 项目页也能批量（与审核队列同一套）==")
html_b = get("/projects/1?tab=bugs")
check("项目页有批量空壳表单", 'id="bulk-form"' in html_b)
check("卡片的勾选框关联批量表单", html_b.count('form="bulk-form"') >= 20,
      html_b.count('form="bulk-form"'))
check("批量按钮初始禁用", html_b.count("disabled>批量") == 2)
# 卡片的勾选框是服务端渲染的，靠 change 委托刷新按钮状态；漏了它就只能全选才能批量
check("单勾也会刷新批量按钮（change 委托在位）",
      "classList.contains('cb-bug')" in html_b)

two = [r[0] for r in sql("SELECT id FROM bugs WHERE project_id=1 "
                        "AND review_status='pending' ORDER BY id DESC LIMIT 2")]
r = client.post("/review/batch",
                data={"kind": "bug", "action": "reject", "comment": "项目页批量验证",
                      "back": "tab=bugs&progress=pending", "ids": two})
loc = r.headers.get("Location", "")
check("项目页批量后回项目页原筛选",
      loc.startswith("/projects/1?tab=bugs&progress=pending"), loc)
check("两条都被驳回",
      all(sql("SELECT review_status FROM bugs WHERE id=?", (i,))[0][0] == "rejected"
          for i in two))

print()
print("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}")
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
sys.exit(1 if fails else 0)
