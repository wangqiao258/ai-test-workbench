"""Bug 两个视图的页面级校验：在数据库副本上跑，不污染真实数据。

覆盖 2026-10-22 的状态轴废弃改造：
1) 默认视图 = 未结案（待审核 + 待上报），五个进度口径与 SQL 一致
2) 收件箱 = 未结案（待审核 + 待上报），与导航栏角标同一口径
3) 上报流程：通过 → 待上报 → 标记已上报 → 离开默认视图；可撤销
4) 只有审核通过的才能标记上报
5) 驳回会清空 reported_at，避免出现"已驳回却已上报"

用法（在 ai-test-platform 目录下）：
    python tests/verify_bug_views.py
"""
import os
import re
import shutil
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_verify_views.db")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)

import db  # noqa: E402
db.DB_PATH = TEST_DB
import app as platform  # noqa: E402  导入即触发 bootstrap + 迁移（作用于副本）

client = platform.app.test_client()
with client.session_transaction() as sess:
    sess["user"] = "admin"

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail else ''}")
    if not cond:
        fails.append(name)


# 卡片链接形如 href="?tab=bugs&amp;sel=39"：Jinja 把 & 转义成 &amp;，
# 所以不能直接匹配 [?&]sel=，要限定在 href 属性内部，避免误取 back 参数里的编码值
CARD_SEL = r'href="\?[^"]*sel=(\d+)"'


def uniq(html, pattern=CARD_SEL):
    return {int(x) for x in re.findall(pattern, html)}


def sql(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    try:
        return {r[0] for r in conn.execute(query, args)}
    finally:
        conn.close()


def scalar(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    try:
        return conn.execute(query, args).fetchone()[0]
    finally:
        conn.close()


TODO = "(review_status='pending' OR (review_status='approved' AND reported_at=''))"

print("== 1. 项目页默认视图（未结案 = 待审核 + 待上报）==")
html = client.get("/projects/1?tab=bugs").get_data(as_text=True)
page_ids = uniq(html)
expect = sql(f"SELECT id FROM bugs WHERE project_id=1 AND {TODO}")
check("默认视图第 1 页 20 条（左栏分页 20/页）", len(page_ids) == 20, f"{len(page_ids)} 条")
check("第 1 页都属于默认视图集合", page_ids <= expect, f"期望集合 {len(expect)} 条")
page2_ids = uniq(client.get("/projects/1?tab=bugs&page=2").get_data(as_text=True))
check("第 2 页补齐剩余", page_ids | page2_ids == expect,
      f"两页合计 {len(page_ids | page2_ids)} 条")
check("默认视图不含已驳回",
      not (page_ids & sql("SELECT id FROM bugs WHERE project_id=1 AND review_status='rejected'")))
check("进度下拉默认选中 todo", 'value="todo" selected' in html)
check("手工录入 Bug 表单已移除", "手动录入 Bug" not in html)
check("页面上已没有状态下拉", 'name="b_status"' not in html)

print("\n== 2. 五个进度口径与 SQL 一致 ==")
for val, cond in (("pending", "review_status='pending'"),
                  ("toreport", "review_status='approved' AND reported_at=''"),
                  ("reported", "review_status='approved' AND reported_at!=''"),
                  ("rejected", "review_status='rejected'")):
    got = uniq(client.get(f"/projects/1?tab=bugs&progress={val}").get_data(as_text=True))
    want = sql(f"SELECT id FROM bugs WHERE project_id=1 AND {cond}")
    # 左栏 20 条/页：超过 20 条的只看第 1 页是否为期望集合的子集
    ok = (got == want) if len(want) <= 20 else (got <= want and len(got) == 20)
    check(f"进度 {val} 与 SQL 一致", ok, f"{len(got)}/{len(want)}")

# 逐页累计，直到某一页不再带来新 id 为止。
# 注意：页码越界时页面会回退到第 1 页（不返回空页），所以不能靠"空页"判断结束。
all_ids, _pg, _prev = set(), 1, -1
while _pg <= 50 and len(all_ids) != _prev:
    _prev = len(all_ids)
    all_ids |= uniq(client.get(f"/projects/1?tab=bugs&progress=all&page={_pg}").get_data(as_text=True))
    _pg += 1
check("全部（逐页累计）= 项目内全部 Bug",
      all_ids == sql("SELECT id FROM bugs WHERE project_id=1"),
      f"{len(all_ids)} 条 / 走过 {_pg - 1} 页")

print("\n== 3. 收件箱 = 未结案（待审核 + 待上报）==")
html = client.get("/review").get_data(as_text=True)
# 队列是分栏卡片，勾选框属性跨行，用 [\s\S]*? 跨行匹配同一标签内的 value
review_ids = uniq(html, r'class="cb-bug"[\s\S]*?value="(\d+)"')
check("队列条数与导航角标同口径（未结案）",
      review_ids == sql(f"SELECT id FROM bugs WHERE {TODO}"),
      f"{len(review_ids)} 条")
check("队列里没有已上报/已驳回",
      not (review_ids & sql("SELECT id FROM bugs WHERE review_status='rejected' "
                            "OR (review_status='approved' AND reported_at!='')")))
# 回归点：待上报的 Bug 曾只在项目页可见，角标有数、收件箱里找不到
tore = sql("SELECT id FROM bugs WHERE review_status='approved' AND reported_at=''")
check("待上报的 Bug 出现在收件箱里", tore <= review_ids, f"{len(tore)} 条")
check("待上报的卡片可被「进度」筛出",
      html.count('data-state="toreport"') == len(tore),
      f"{html.count('data-state=\"toreport\"')} / {len(tore)}")
# 拆分要真的是两半：少了 GROUP BY 时两半会塌成"全部算待审核"
n_p = scalar("SELECT COUNT(*) FROM bugs WHERE review_status='pending'")
n_t = scalar("SELECT COUNT(*) FROM bugs WHERE review_status='approved' AND reported_at=''")
flat = re.sub(r"\s+", " ", html)
check("标题拆分：待审核 / 待上报",
      f"待审核 <b>{n_p}</b> 条、待上报 <b>{n_t}</b> 条" in flat, f"{n_p} / {n_t}")
check("角标 tooltip 拆分与标题一致",
      f'title="待审核 {n_p} + 待上报 {n_t}"' in flat, f"{n_p} + {n_t}")

print("\n== 4. 上报流程：通过 → 待上报 → 已上报 ==")
b = scalar("SELECT MIN(id) FROM bugs WHERE review_status='pending'")
client.post(f"/review/bug/{b}", data={"action": "approve", "comment": "", "back": "tab=bugs"})
check("通过后进入待上报", scalar("SELECT review_status FROM bugs WHERE id=?", (b,)) == "approved"
      and scalar("SELECT reported_at FROM bugs WHERE id=?", (b,)) == "")
page_b = client.get(f"/projects/1?tab=bugs&sel={b}").get_data(as_text=True)
check("右栏给出「标记已上报」", "标记已上报" in page_b and "待上报" in page_b)
check("待上报仍留在默认视图集合里", b in sql(f"SELECT id FROM bugs WHERE project_id=1 AND {TODO}"))
check("待上报在收件箱里看得到（角标点进去不是空页）",
      b in uniq(client.get("/review").get_data(as_text=True),
                r'class="cb-bug"[\s\S]*?value="(\d+)"'))

client.post(f"/bugs/{b}/reported", data={"value": "1", "back": f"tab=bugs&sel={b}"})
check("标记上报后写入时间", bool(scalar("SELECT reported_at FROM bugs WHERE id=?", (b,))))
after = client.get(f"/projects/1?tab=bugs&sel={b}").get_data(as_text=True)
check("右栏变成「已上报」并可撤销", "已上报" in after and "撤销上报" in after)
check("已上报离开默认视图", b not in sql(f"SELECT id FROM bugs WHERE project_id=1 AND {TODO}"))
check("已上报也离开收件箱",
      b not in uniq(client.get("/review").get_data(as_text=True),
                    r'class="cb-bug"[\s\S]*?value="(\d+)"'))
check("已上报出现在 reported 视图",
      b in sql("SELECT id FROM bugs WHERE project_id=1 "
               "AND review_status='approved' AND reported_at!=''"))

client.post(f"/bugs/{b}/reported", data={"value": "0", "back": "tab=bugs"})
check("撤销上报后回到待上报",
      scalar("SELECT reported_at FROM bugs WHERE id=?", (b,)) == ""
      and scalar("SELECT review_status FROM bugs WHERE id=?", (b,)) == "approved")

print("\n== 5. 只有通过了的才能标上报 ==")
p2 = scalar("SELECT MIN(id) FROM bugs WHERE review_status='pending'")
r = client.post(f"/bugs/{p2}/reported", data={"value": "1"}, follow_redirects=True)
check("待审核的标记上报被拦",
      scalar("SELECT reported_at FROM bugs WHERE id=?", (p2,)) == ""
      and "只有审核通过" in r.get_data(as_text=True))

print("\n== 6. 驳回会清空上报标记 ==")
client.post(f"/bugs/{b}/reported", data={"value": "1", "back": "tab=bugs"})
client.post(f"/review/bug/{b}",
            data={"action": "reject", "comment": "测试驳回清空上报", "back": "tab=bugs"})
check("驳回后 reported_at 被清空",
      scalar("SELECT reported_at FROM bugs WHERE id=?", (b,)) == "")
check("驳回后 review_status=rejected",
      scalar("SELECT review_status FROM bugs WHERE id=?", (b,)) == "rejected")

rej_html = client.get("/projects/1?tab=bugs&progress=rejected").get_data(as_text=True)
check("右栏显示驳回意见",
      "审核意见" in client.get(f"/projects/1?tab=bugs&progress=rejected&sel={b}")
      .get_data(as_text=True) and "测试驳回清空上报" in
      client.get(f"/projects/1?tab=bugs&progress=rejected&sel={b}").get_data(as_text=True))

print("\n== 7. 手工改 URL 不能越权 ==")
check("词表外的 progress 当没传",
      len(uniq(client.get("/projects/1?tab=bugs&progress=xxx").get_data(as_text=True))) == 20)

print("\n" + ("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}"))
os.remove(TEST_DB)
sys.exit(1 if fails else 0)
