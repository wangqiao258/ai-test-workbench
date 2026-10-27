"""审核队列（/review）分栏化的页面级校验：在数据库副本上跑，不污染真实数据。

覆盖 2026-10-22 下午的改造：
1) /review 改左右分栏，右栏与项目页共用 _detail_bug.html（不再有第三套详情）
2) 缺省选中队列第一条、?sel=<id> 指定、sel 不存在时回退
3) 卡片右侧勾选框关联空壳批量表单，批量按钮初始禁用
4) back 分流：审核页发起回 /review 并保留筛选；项目页发起仍回项目页
5) /review/bug/<id> 已改为 302 到 /review?sel=<id>
6) 导航栏显示待办条数，收件箱 = 未结案（待审核 + 待上报），两处同口径

用法（在 ai-test-platform 目录下）：
    python tests/verify_review_split.py
"""
import os
import re
import shutil
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_verify_review_split.db")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)

import db  # noqa: E402
db.DB_PATH = TEST_DB
import app as platform  # noqa: E402

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


def scalar(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    try:
        return conn.execute(query, args).fetchone()[0]
    finally:
        conn.close()


CB_IDS = r'value="(\d+)" data-evi'
ACTIVE_SEL = r'class="bug-card active"[\s\S]*?href="\?[^"]*sel=(\d+)"'

# 收件箱 = 未结案（待审核 + 待上报），顺序与 core/lists.review_queue 一致：待审核优先
queue = [r[0] for r in sql(
    "SELECT id FROM bugs WHERE review_status IN ('pending','approved') "
    "AND COALESCE(reported_at,'')='' "
    "ORDER BY CASE review_status WHEN 'pending' THEN 0 ELSE 1 END, created_at")]

print("== 1. 分栏结构 ==")
html = get("/review")
check("左栏存在", 'class="split-left"' in html)
check("右栏存在", 'class="split-right"' in html)
check("右栏用的是统一详情组件（sticky 操作条）", 'class="detail-actions"' in html)
check("左栏卡片数 = 队列条数", html.count('class="bug-card') == len(queue), len(queue))
check("卡片上的勾选框数 = 队列条数",
      len(re.findall(CB_IDS, html)) == len(queue), len(re.findall(CB_IDS, html)))

print("\n== 2. 选中逻辑 ==")
ids = [int(x) for x in re.findall(CB_IDS, html)]
m = re.search(ACTIVE_SEL, html)
check("缺省选中队列第一条", m and int(m.group(1)) == ids[0], m.group(1) if m else None)

picked = get(f"/review?sel={ids[3]}")
m2 = re.search(ACTIVE_SEL, picked)
check("?sel= 指定后选中该条", m2 and int(m2.group(1)) == ids[3], m2.group(1) if m2 else None)
check("右栏跟着换", f"#{ids[3]}" in picked)

fallback = get("/review?sel=999999")
m3 = re.search(ACTIVE_SEL, fallback)
check("sel 不存在时回退第一条", m3 and int(m3.group(1)) == ids[0])

print("\n== 3. 批量表单与按钮 ==")
check("批量表单是空壳（不在卡片外层）", 'id="bulk-form"' in html)
check("勾选框通过 form 属性关联", html.count('form="bulk-form"') >= len(queue),
      html.count('form="bulk-form"'))
check("批量按钮初始禁用", html.count("disabled>批量") == 2, html.count("disabled>批量"))
check("单勾也会刷新批量按钮（change 委托在位）",
      "classList.contains('cb-bug')" in html)
check("全选控件存在", "toggleVisible(this, 'cb-bug')" in html)
check("筛选键仍在（前端口径不变）",
      'id="f-bug-project"' in html and 'id="f-bug-evi"' in html)

print("\n== 4. back 分流 ==")
b1 = queue[0]
r = client.post(f"/review/bug/{b1}",
                data={"action": "reject", "comment": "验证 back 分流", "back": "sel=8&fp=x"})
loc = r.headers.get("Location", "")
check("审核页发起的审核回 /review", loc.startswith("/review?"), loc)
check("保留队列筛选（fp）", "fp=x" in loc, loc)

b2 = queue[1]
r2 = client.post(f"/review/bug/{b2}",
                 data={"action": "reject", "comment": "验证项目页来源",
                       "back": "tab=bugs&sel=8"})
loc2 = r2.headers.get("Location", "")
check("项目页发起的仍回项目页", loc2.startswith("/projects/1?tab=bugs"), loc2)

b3 = queue[2]
# 上报只能对"已通过"的做：先通过，再标记已上报，验回跳
client.post(f"/review/bug/{b3}", data={"action": "approve", "comment": "", "back": "sel=8"})
r3 = client.post(f"/bugs/{b3}/reported", data={"value": "1", "back": "sel=8"})
loc3 = r3.headers.get("Location", "")
check("审核页标记已上报回 /review", loc3.startswith("/review?"), loc3)

r4 = client.post("/review/batch",
                 data={"kind": "bug", "action": "approve", "comment": "",
                       "back": "sel=8&fp=x", "ids": [queue[3], queue[4]]})
loc4 = r4.headers.get("Location", "")
check("批量后回 /review 并保留筛选",
      loc4.startswith("/review?") and "fp=x" in loc4, loc4)

print("\n== 5. 旧详情链接 ==")
r5 = client.get(f"/review/bug/{b1}", follow_redirects=False)
check("/review/bug/<id> 返回 302", r5.status_code == 302, r5.status_code)
check("跳转到 /review?sel=<id>", f"sel={b1}" in r5.headers.get("Location", ""),
      r5.headers.get("Location"))

print("\n== 6. 导航待办数 ==")
dash = get("/projects/1?tab=bugs")
nav_n = re.search(r'Bug 审核\s*<span class="tab-n"[^>]*>(\d+)</span>', dash)
# 导航栏是"待办数" = 待审核 + 待上报，不是只数 pending
expect_n = scalar("SELECT COUNT(*) FROM bugs WHERE review_status!='rejected' AND reported_at=''")
check("导航栏显示待审数", nav_n and int(nav_n.group(1)) == expect_n,
      f"{nav_n.group(1) if nav_n else None} vs {expect_n}")

print("\n== 7. 详情三处一致 ==")
h_rev = get(f"/review?sel={b1}")
h_proj = get(f"/projects/1?tab=bugs&sel={b1}")
h_ind = get(f"/bugs/{b1}")
check("审核页右栏有统一操作条", 'class="detail-actions"' in h_rev)
check("项目页右栏有统一操作条", 'class="detail-actions"' in h_proj)
check("独立详情页有统一操作条", 'class="detail-actions"' in h_ind)
check("审核页右栏能标记已上报（走统一操作条）", 'class="detail-actions"' in h_rev)
check("审核页右栏显示进度徽标",
      any(x in h_rev for x in ("待审核", "待上报", "已上报", "已驳回")))

print()
print("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}")
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
sys.exit(1 if fails else 0)
