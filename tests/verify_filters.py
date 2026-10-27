"""列表页筛选、分页与详情页的页面级校验：在数据库副本上跑，不污染真实数据。

覆盖 2026-10-22 的改造：
1) 接口/用例/Bug/文档四个列表都能筛，词表外的参数不生效
2) 列表分页（接口 50/页），页码越界钳到末页
3) 列表只留索引，全文进 /cases/<id>、/bugs/<id>
4) back 参数只认白名单键，挡住外部跳转
5) 接口树不再带 evidence，详情面板单独按需取

用法（在 ai-test-platform 目录下）：
    python tests/verify_filters.py
"""
import json
import os
import re
import shutil
import sqlite3
import sys
from urllib.parse import quote

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_verify_filters.db")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)

import db  # noqa: E402
db.DB_PATH = TEST_DB
import app as platform  # noqa: E402  导入即触发 bootstrap（作用于副本）

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


def rows(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    try:
        return conn.execute(query, args).fetchall()
    finally:
        conn.close()


def n_rows(html):
    """表格里的接口行数（筛选条里没有 method 徽标）。"""
    return html.count('<span class="badge method-')


def total_in(html):
    """结果行里的"共 N 条"。"""
    m = re.search(r"共 <b>(\d+)</b>", html)
    return int(m.group(1)) if m else None


def filtered_in(html):
    """结果行里的"筛出 N 条"。"""
    m = re.search(r"筛出 <b>(\d+)</b>", html)
    return int(m.group(1)) if m else None


def frag_of(text, size=24):
    """取一段"在详情页里必然连续出现"的片段：按行取，跳过箭头行与特殊字符。

    跨行取会踩坑：日志文本里 "…无效） -> PUT" 在详情页被 HTML 标签隔开，
    片段自然拼不起来。所以只在单行内滑动窗口。
    """
    for line in (text or "").splitlines():
        line = " ".join(line.split())
        line = re.sub(r"^\s*\d+\.\s*", "", line)
        # 列表文本里的"预期: xxx"到详情页变成"预期：xxx"（全角冒号），前缀要剥掉
        line = re.sub(r"^(预期|实际|步骤|前置|备注)[:：]\s*", "", line)
        if "->" in line:
            continue
        for i in range(0, max(1, len(line) - size) + 1):
            cand = line[i:i + size]
            if len(cand) == size and not any(c in cand for c in "<>&"):
                return cand
    return ""


print("== 1. 接口列表：分页 ==")
html = get("/projects/1?tab=interfaces")
expect_total = scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=1")
# 页数与末页行数按库内条数算：写死"4 页 / 11 行"只在 161 条的本地副本上成立，
# 服务端 244 条时会变成假红（2026-10-27 部署时踩到）。
pages = max(1, (expect_total + 49) // 50)
last_rows = expect_total - (pages - 1) * 50
check("首屏 50 行", n_rows(html) == 50, n_rows(html))
check("总数与 SQL 一致", total_in(html) == expect_total, total_in(html))
check("分页控件显示页数", f"第 1 / {pages} 页" in html, f"{pages} 页 / {expect_total} 条")
html2 = get("/projects/1?tab=interfaces&page=2")
check("第 2 页也是 50 行", n_rows(html2) == 50, n_rows(html2))
check("第 2 页内容与第 1 页不同", html != html2)
html_last = get("/projects/1?tab=interfaces&page=99")
check("越界页码钳到末页", f"第 {pages} / {pages} 页" in html_last and n_rows(html_last) == last_rows,
      f"{n_rows(html_last)} 行（应为 {last_rows}）")
check("分页链接保留筛选参数",
      "module=%E8%AE%A4%E8%AF%81" in get("/projects/1?tab=interfaces&module=认证"),
      "")

print("\n== 2. 接口列表：筛选 ==")
mod = scalar("SELECT module FROM interfaces WHERE project_id=1 GROUP BY module "
             "ORDER BY COUNT(*) DESC LIMIT 1")
expect = scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=1 AND module=?", (mod,))
html = get(f"/projects/1?tab=interfaces&module={quote(mod)}")
check("按模块筛出的条数与 SQL 一致", filtered_in(html) == expect, f"{mod} {filtered_in(html)}")
check("页面标注已按模块筛选", "按 模块 筛出" in html)
check("同时给出全库总数", total_in(html) == expect_total, total_in(html))
check("提供清除筛选入口", "清除筛选" in html)

expect_post = scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=1 AND method='POST'")
html = get("/projects/1?tab=interfaces&method=POST")
check("按方法筛出的条数与 SQL 一致", filtered_in(html) == expect_post, filtered_in(html))

expect_kw = scalar("SELECT COUNT(*) FROM interfaces WHERE project_id=1 AND "
                   "(path LIKE '%login%' OR name LIKE '%login%' OR module LIKE '%login%')")
html = get("/projects/1?tab=interfaces&q=login")
check("关键字同时搜路径/名称/模块", filtered_in(html) == expect_kw, filtered_in(html))

html = get("/projects/1?tab=interfaces&module=根本没有这个模块")
check("词表外的模块被忽略，不会筛出空页", total_in(html) == expect_total)

print("\n== 3. 用例列表：筛选 ==")


def latest_counts():
    out = {}
    for r in rows("SELECT COALESCE((SELECT result FROM executions e "
                  "WHERE e.case_id=c.id ORDER BY e.id DESC LIMIT 1),'none') r, "
                  "COUNT(*) FROM cases c WHERE c.project_id=1 GROUP BY r"):
        out[r[0]] = r[1]
    return out


lc = latest_counts()
total_cases = scalar("SELECT COUNT(*) FROM cases WHERE project_id=1")
for key, label in [("fail", "未通过"), ("pass", "通过"), ("blocked", "阻塞"), ("none", "未执行")]:
    html = get(f"/projects/1?tab=cases&result={key}")
    check(f"执行结果={label} 条数与 SQL 一致", filtered_in(html) == lc.get(key, 0),
          f"{filtered_in(html)} vs {lc.get(key, 0)}")

p0 = scalar("SELECT COUNT(*) FROM cases WHERE project_id=1 AND priority='P0'")
check("优先级 P0 条数", filtered_in(get("/projects/1?tab=cases&priority=P0")) == p0, p0)

dim = scalar("SELECT COUNT(*) FROM cases WHERE project_id=1 AND dims LIKE '%越权%'")
check("覆盖维度筛选", filtered_in(get("/projects/1?tab=cases&dim=" + quote("越权"))) == dim, dim)

anchors = sum(filtered_in(get(f"/projects/1?tab=cases&anchor={k}")) for k
              in ("interface", "doc", "module"))
check("三种锚点互斥且合计等于总数", anchors == total_cases, f"{anchors} vs {total_cases}")

print("\n== 4. 列表不再内嵌全文 ==")
case_id, case_steps, case_json = rows(
    "SELECT id, steps, steps_json FROM cases WHERE project_id=1 AND "
    "LENGTH(steps) > 80 ORDER BY LENGTH(steps) DESC LIMIT 1")[0]
# 详情页用结构化步骤渲染，纯文本 steps 里的"1. "编号不会出现，所以优先取 action 原文
frag = ""
if case_json:
    try:
        doc = json.loads(case_json)
        if doc.get("steps"):
            frag = frag_of(doc["steps"][0]["action"])
    except ValueError:
        pass
frag = frag or frag_of(re.sub(r"^\s*\d+\.\s*", "", case_steps, flags=re.M))
list_html = get("/projects/1?tab=cases")
detail_html = get(f"/cases/{case_id}")
check("用例列表里没有步骤全文", frag and frag not in list_html, f"#{case_id}「{frag[:14]}…」")
check("用例详情页有步骤全文", frag and frag in detail_html, f"#{case_id}")

bug_id, bug_steps, bug_evi = rows("SELECT id, steps, evidence FROM bugs WHERE project_id=1 "
                                 "ORDER BY LENGTH(steps)+LENGTH(evidence) DESC LIMIT 1")[0]
bfrag = frag_of(bug_steps) or frag_of(bug_evi)
bug_list = get("/projects/1?tab=bugs")
bug_detail = get(f"/bugs/{bug_id}")
check("Bug 列表里没有复现步骤全文", bfrag and bfrag not in bug_list, f"#{bug_id}")
check("Bug 详情页有复现步骤全文", bfrag and bfrag in bug_detail)

print("\n== 5. 详情页返回：back 白名单 ==")
back = quote("tab=cases&module=认证&evil=http://x")
html = get(f"/cases/{case_id}?back={back}")
check("返回链接保留 tab", "tab=cases" in html)
check("返回链接保留模块筛选", "module=%E8%AE%A4%E8%AF%81" in html)
check("返回链接丢弃非白名单参数", "evil" not in html)
html = get(f"/bugs/{bug_id}")
check("无 back 时退回 Bug 列表", 'href="/projects/1?tab=bugs"' in html)

print("\n== 6. 接口目录树：不再背 evidence ==")
html = get("/projects/1?tab=interfaces&view=tree")
m = re.search(r"const ITFS = (.*?);\n", html, re.S)
check("树数据存在", bool(m))
tree_json = m.group(1) if m else ""
check("树数据不含 evidence", '"evidence"' not in tree_json)
check("树数据不含 resp_example", '"resp_example"' not in tree_json)
check("树数据不含 req_params", '"req_params"' not in tree_json)
check("树数据含全部 161 个节点", tree_json.count('"path"') == expect_total,
      tree_json.count('"path"'))
check("目录树首屏 < 80 KB", len(html.encode()) < 80 * 1024, f"{len(html.encode())/1024:.1f} KB")
check("页面上有搜索框", 'id="itf-search"' in html)
check("旧 tab=apidoc 链接 302 到目录树",
      client.get("/projects/1?tab=apidoc").status_code == 302
      and "/projects/1?tab=interfaces&view=tree" in
      client.get("/projects/1?tab=apidoc").headers.get("Location", ""))
check("旧 apidoc&view=swagger 也收口到目录树（页面已删）",
      "/projects/1?tab=interfaces&view=tree" in
      client.get("/projects/1?tab=apidoc&view=swagger").headers.get("Location", ""))
check("白名单外的 view 回列表（有筛选表单、无树容器）",
      'name="tab" value="interfaces"' in get("/projects/1?tab=interfaces&view=nope")
      and 'id="itf-tree"' not in get("/projects/1?tab=interfaces&view=nope"))
check("目录树视图不再出现 old tab 链接", "tab=apidoc" not in html)
# 停在文件夹上也要有信息：右栏换成该目录的汇总（条数/方法/可信度/未验证清单）
check("点文件夹有右栏汇总（脚本含 folderHtml/showFolder）",
      "function folderHtml(" in html and "function showFolder(" in html
      and "markFolder(head)" in html and "collectFiles(" in html)
check("右栏提示写明文件夹也有信息", "点文件夹看该目录的汇总" in html)
check("列表视图也有验证状态统计（原接口文档头部）",
      "已实测" in get("/projects/1?tab=interfaces"))
# Swagger 页面 2026-10-27 已删：日常只有两个视图，标准文档只走 openapi.json
list_html = get("/projects/1?tab=interfaces")
check("接口页只剩列表/目录树两个视图",
      "view=tree" in list_html and "view=swagger" not in list_html
      and "Swagger UI" not in list_html)
check("openapi.json 导出入口还在", "openapi.json" in list_html)

print("\n== 6b. 接口详情：基线 / 风险维度分开 ==")
iid_dim = rows("SELECT MIN(id) FROM interfaces WHERE project_id=1")[0][0]
html_dim = get(f"/interfaces/{iid_dim}")
check("把「正常」单列为基线", "基线（正常流）" in html_dim)
check("风险维度带 n/9 计数", "风险维度：" in html_dim and "/ 9" in html_dim)
check("旧的「覆盖维度」整块已拆掉", "覆盖维度：" not in html_dim)

print("\n== 7. 接口面板：鉴权与归属 ==")
anon = platform.app.test_client()
iid = rows("SELECT MIN(id) FROM interfaces WHERE project_id=1")[0][0]
r = anon.get(f"/projects/1/interfaces/{iid}/panel.html")
check("未登录取面板被拦", r.status_code in (302, 401), r.status_code)
r = client.get(f"/projects/1/interfaces/{iid}/panel.html")
body = r.get_data(as_text=True)
check("登录后返回契约片段", r.status_code == 200 and "请求参数" in body
      and "请求头" in body and "打开完整详情" in body, r.status_code)
# 断"证据区块没进片段"：短 evidence（如 "200 OK"）会撞上响应示例里的同名字符串，
# 按正文前缀断会假红。面板本就不渲染"数据包证据"这块（那是详情页的事）。
check("面板不渲染数据包证据区块", "数据包证据" not in body)
# 防漂移：右栏和详情页必须走同一份契约宏（表头/字段名/notes 渲染）
param_head = "<th>名称</th><th>类型</th><th>必填</th><th>说明</th><th>示例</th>"
check("右栏与详情页共用契约渲染",
      param_head in body and param_head in get(f"/interfaces/{iid}"))
r = client.get(f"/projects/999/interfaces/{iid}/panel.html")
check("项目与接口不匹配返回 404", r.status_code == 404, r.status_code)
r = client.get("/projects/1/interfaces/999999/panel.html")
check("接口不存在返回 404", r.status_code == 404, r.status_code)

print("\n== 8. 文档与 Bug 筛选 ==")
n_analysis = scalar("SELECT COUNT(*) FROM docs WHERE project_id=1 AND dtype='analysis'")
check("文档按类型筛选", filtered_in(get("/projects/1?tab=docs&dtype=analysis")) == n_analysis,
      n_analysis)
n_sec = scalar("SELECT COUNT(*) FROM bugs WHERE project_id=1 AND module='安全' "
               "AND review_status!='rejected' AND reported_at=''")
check("Bug 按模块筛选（叠加默认视图）",
      filtered_in(get("/projects/1?tab=bugs&module=" + quote("安全"))) == n_sec, n_sec)
html = get("/projects/1?tab=bugs&progress=all")
n_all = scalar("SELECT COUNT(*) FROM bugs WHERE project_id=1")
check("显示全部时条数等于全库", filtered_in(html) == n_all, filtered_in(html))
check("进度筛选下拉是 progress", 'name="progress"' in html and 'name="module"' in html)

print("\n== 9. 操作日志：筛选与分页 ==")
html = get("/settings")
n_audit = scalar("SELECT COUNT(*) FROM audit")
check("日志标题显示总数", f"操作日志（{n_audit} 条）" in html, n_audit)
shown = html.count("<td>ai:workbuddy</td>") + html.count("<td>user:admin</td>")
check("首屏只渲染 50 条", shown == 50, shown)
check("日志有筛选控件", 'name="actor"' in html and 'name="action"' in html)
n_login = scalar("SELECT COUNT(*) FROM audit WHERE action='login'")
check("按动作筛选", f"操作日志（{n_login} 条）" in get("/settings?action=login"), n_login)
n_ai = scalar("SELECT COUNT(*) FROM audit WHERE actor='ai:workbuddy'")
check("按操作者筛选", f"操作日志（{n_ai} 条）" in get("/settings?actor=ai:workbuddy"), n_ai)
html_p2 = get("/settings?apage=2")
check("日志第 2 页与第 1 页不同", html_p2 != html and "第 2 /" in html_p2)

print("\n== 10. 审核页：证据筛选 ==")
html = get("/review")
n_todo = scalar("SELECT COUNT(*) FROM bugs WHERE review_status='pending' "
                "OR (review_status='approved' AND reported_at='')")
check("队列条数 = 未结案数（与导航角标同口径）", f"Bug 待办（{n_todo}）" in html, n_todo)
# 筛选条整块包在 {% if bugs %} 里：队列空时页面只有空状态，不该期望控件存在
# （服务端待办为 0 时会误报，2026-10-27 部署时踩到）。
if n_todo:
    check("有证据筛选控件", 'id="f-bug-evi"' in html and "无证据" in html)
else:
    print("SKIP  待办队列为空，筛选条不渲染")
check("行上带 data-evi", html.count("data-evi=") >= n_todo * 2, html.count("data-evi="))
check("筛选状态写回地址", "history.replaceState" in html)

print("\n== 11. 不存在的详情返回 404 ==")
check("/cases/999999 返回 404", client.get("/cases/999999").status_code == 404)
check("/bugs/999999 返回 404", client.get("/bugs/999999").status_code == 404)

print("\n" + ("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}"))
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
sys.exit(1 if fails else 0)
