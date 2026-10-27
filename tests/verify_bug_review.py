"""审核入口的页面级校验：在数据库副本上跑，不污染真实数据。

覆盖 2026-10-22 的两轮改造：
1) 审核入口在分栏右栏（左栏卡片是纯链接，不放按钮）
2) 通过 / 驳回 / 改判三态，驳回必须填原因，改判保留历史意见
3) 审核与上报互不干扰：标记已上报不改 review_status，撤销也不改
4) back 只认白名单键，项目页与审核页各自回原处
5) 详情页操作条按四态给按钮（status 轴已废弃，不再有「关闭」）

用法（在 ai-test-platform 目录下）：
    python tests/verify_bug_review.py
"""
import os
import re
import shutil
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_verify_review.db")
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


def post(url, data):
    return client.post(url, data=data)


def sql(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    try:
        return conn.execute(query, args).fetchall()
    finally:
        conn.close()


def scalar(query, args=()):
    r = sql(query, args)
    return r[0][0] if r else None


def bug_row(bid):
    """返回 {review, reported, comment}，比位置索引好读。"""
    r = sql("SELECT review_status, reported_at, review_comment FROM bugs WHERE id=?", (bid,))
    if not r:
        return {"review": None, "reported": None, "comment": None}
    return {"review": r[0][0], "reported": r[0][1], "comment": r[0][2]}


# 服务端库可能一条待审都没有（全审完了），测试自带夹具，别依赖生产数据状态。
# 只在副本库里插，跑完随副本一起删。
_fix = sqlite3.connect(TEST_DB)
for _i in range(6):
    _fix.execute(
        "INSERT INTO bugs (project_id, title, module, severity, steps, evidence, "
        "review_status, reported_at, created_by, created_at, updated_at) "
        "VALUES (1, ?, '审核验证', 'normal', '打开页面点保存', '响应 500，截图见附件', "
        "'pending', '', 'fixture', '2026-10-27 00:00:00', '2026-10-27 00:00:00')",
        (f"审核夹具 {_i + 1}",))
_fix.commit()
_fix.close()

pending = [r[0] for r in sql(
    "SELECT id FROM bugs WHERE review_status='pending' ORDER BY id")]
rejected = [r[0] for r in sql(
    "SELECT id FROM bugs WHERE review_status='rejected' ORDER BY id")]
check("副本库里有足够的待审数据", len(pending) >= 4 and len(rejected) >= 1,
      f"pending={len(pending)} rejected={len(rejected)}")

print("== 1. 分栏的审核入口 ==")
html = get("/projects/1?tab=bugs")
check("分栏上方有口径说明", "平台不记「修没修」" in html and 'class="hint"' in html)
check("左栏卡片是纯链接（按钮不放列表）",
      'class="bug-card' in html and "mini danger" not in html)
check("默认选中第一条，右栏有操作条",
      'class="bug-card active"' in html and 'class="detail-actions"' in html)

# 右栏一次只渲染一条，所以按钮随选中项变化，不再"每行一个"
b_pending = pending[0]
html_p = get(f"/projects/1?tab=bugs&sel={b_pending}")
check("待审核 Bug 的右栏有「通过」", 'value="approve"' in html_p)
check("待审核 Bug 的右栏有「驳回」", 'value="reject"' in html_p)
check("待审核的右栏没有「标记已上报」（要先通过）", "标记已上报</button>" not in html_p)

print("\n== 1b. 审核输入是页面内表单，不是弹框 ==")
check("右栏有审核输入区", 'class="review-box"' in html_p)
check("驳回分类是下拉（不再是输入 1~6 的弹框）",
      '<select name="reject_category"' in html_p)
check("审核意见是多行输入框", '<textarea name="comment"' in html_p)
check("点驳回走就地校验，没有两个 prompt",
      "wbReject(this)" in html_p and "needComment" not in html_p
      and "wbAskRejectCategory" not in html_p)
check("已驳回的右栏不显示审核输入区（只有改判通过）",
      'class="review-box"' not in get(
          f"/projects/1?tab=bugs&progress=rejected&sel={rejected[0]}"))

rej_id = rejected[0]
html_rej = get(f"/projects/1?tab=bugs&progress=rejected&sel={rej_id}")
check("已驳回 Bug 的右栏给的是「改判通过」", html_rej.count("改判通过") == 1,
      html_rej.count("改判通过"))
# 页面底部批量条里也有 value="reject"，所以只取详情操作条那个表单来判断
detail_form = re.search(rf'action="/review/bug/{rej_id}"[\s\S]*?</form>', html_rej)
check("已驳回 Bug 的右栏不再显示「驳回」",
      detail_form and 'value="reject"' not in detail_form.group(0))

print("\n== 2. 直接审核 ==")
b_approve = pending[0]
before_audit = scalar("SELECT COUNT(*) FROM audit WHERE action='review_approve'")
r = post(f"/review/bug/{b_approve}",
         {"action": "approve", "comment": "", "back": "tab=bugs&progress=pending"})
check("通过后 302 回项目页", r.status_code == 302
      and r.headers["Location"].endswith("/projects/1?tab=bugs&progress=pending"),
      r.headers.get("Location"))
check("审核状态变已通过", bug_row(b_approve)["review"] == "approved",
      bug_row(b_approve)["review"])
check("通过本身不写 reported_at（仍待上报）", bug_row(b_approve)["reported"] == "")
check("动作写了审计日志",
      scalar("SELECT COUNT(*) FROM audit WHERE action='review_approve'") == before_audit + 1)

b_reject = pending[1]
r = post(f"/review/bug/{b_reject}",
         {"action": "reject", "comment": "", "back": "tab=bugs"})
check("驳回不填原因被拦，状态不变", bug_row(b_reject)["review"] == "pending",
      bug_row(b_reject)["review"])
check("被拦时也回到原筛选（不是审核页）", r.headers["Location"].endswith("/projects/1?tab=bugs"),
      r.headers.get("Location"))

post(f"/review/bug/{b_reject}",
     {"action": "reject", "comment": "无法复现，属误报", "back": "tab=bugs"})
check("填了原因就驳回成功", bug_row(b_reject)["review"] == "rejected",
      bug_row(b_reject)["review"])
check("驳回原因落库", bug_row(b_reject)["comment"] == "无法复现，属误报",
      bug_row(b_reject)["comment"])

print("\n== 3. 改判保留历史 ==")
b_old = rejected[0]
old_comment = bug_row(b_old)["comment"]
post(f"/review/bug/{b_old}", {"action": "approve", "comment": "", "back": "tab=bugs"})
check("已驳回可以改判通过", bug_row(b_old)["review"] == "approved", bug_row(b_old)["review"])
check("改判通过不会抹掉原驳回意见", bug_row(b_old)["comment"] == old_comment,
      bug_row(b_old)["comment"])

post(f"/review/bug/{b_old}", {"action": "reject", "comment": "复测后确认是误报",
                              "back": "tab=bugs"})
check("已通过可以改判驳回", bug_row(b_old)["review"] == "rejected", bug_row(b_old)["review"])
check("改判驳回会写入新意见", bug_row(b_old)["comment"] == "复测后确认是误报",
      bug_row(b_old)["comment"])

print("\n== 4. 审核与上报互不干扰 ==")
b_flow = pending[2]
post(f"/review/bug/{b_flow}", {"action": "approve", "comment": "", "back": "tab=bugs"})
check("通过后是待上报（reported_at 仍空）",
      bug_row(b_flow)["review"] == "approved" and bug_row(b_flow)["reported"] == "",
      bug_row(b_flow)["review"])
post(f"/bugs/{b_flow}/reported", {"value": "1", "back": "tab=bugs"})
check("标记上报不改审核状态",
      bug_row(b_flow)["review"] == "approved" and bug_row(b_flow)["reported"] != "")
post(f"/bugs/{b_flow}/reported", {"value": "0", "back": "tab=bugs"})
check("撤销上报不改审核状态",
      bug_row(b_flow)["review"] == "approved" and bug_row(b_flow)["reported"] == "")

print("\n== 5. back 白名单与来源分流 ==")
b_back = [i for i in pending if bug_row(i)["review"] == "pending"]
if b_back:
    r = post(f"/review/bug/{b_back[0]}",
             {"action": "approve", "comment": "", "back": "tab=bugs&evil=http://x&q=登录"})
    loc = r.headers.get("Location", "")
    check("保留白名单键", "tab=bugs" in loc and "q=" in loc, loc)
    check("丢弃非白名单键", "evil" not in loc, loc)
    check("中文参数被正确编码", "%E7%99%BB%E5%BD%95" in loc, loc)

    r = post(f"/review/bug/{b_back[0] if b_back else pending[3]}",
             {"action": "approve", "comment": "", "back": "fp=%E7%99%BB%E5%BD%95"})
    loc = r.headers.get("Location", "")
    check("不带 tab 的 back 回审核队列", loc.startswith("/review?"), loc)

print("\n== 6. 详情页操作条 ==")
did = [i for i in pending if bug_row(i)["review"] == "pending"]
if did:
    html = get(f"/bugs/{did[0]}")
    # 四态操作条：证据最长 17457 字符，按钮不该在页面底部
    check("详情页有常驻操作条", 'class="detail-actions"' in html)
    check("操作条含审核入口", 'value="approve"' in html and 'value="reject"' in html)
    check("操作条带 back", 'name="back"' in html)
    check("已没有状态下拉与关闭守卫",
          'name="status"' not in html and "guardClose" not in html)
    check("旧的「去审核页处理」已移除", "去审核页处理" not in html)

print("\n" + ("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}"))
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
sys.exit(1 if fails else 0)
