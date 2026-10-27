"""列表页的数据查询（筛选 + 分页 + 排序）。

网页端四个列表面板、审核队列、操作日志都从这里取数，app.py 只负责路由和渲染。

两个刻意的取舍：
1. 列表页只 SELECT 索引列。原来 `SELECT *` 把 evidence 一起搬出来，
   161 条接口光首屏就 66 KB，其中 96% 在列表里根本用不到。
2. 用例的"最近一次执行"用窗口函数一次算完。原来是每个用例查一次
   executions——61 个用例就是 61 次往返，整页 70 次 SQL。
"""
import json

from .coverage import interface_coverage, is_ui_case, ui_module_coverage
from .filters import LIKE_ESC, Field, build, escape_like, paginate
from .runs import (RUN_KINDS, RUN_STATUSES, classify_cases, heartbeat_at,
                   is_stalled, regression_diff, run_progress, scope_where,
                   stall_cutoff)
from .validation import DIM_VOCAB, DOC_TYPES

# 列表页字段：不含 evidence / resp_example / 参数表，详情页或面板才取
ITF_LIST_COLS = ("id, project_id, module, name, method, path, host, notes, "
                 "verify_status, verified_at, created_by, created_at, updated_at")
# 目录树字段：只要渲染节点 + 前端拼地址用的，详情（含验证时间）点开再拉
ITF_TREE_COLS = "id, module, name, method, path, host, verify_status"

CASE_LIST_COLS = ("c.id, c.project_id, c.module, c.title, c.priority, c.dims, "
                  "c.interface_id, c.doc_id, c.created_by, c.created_at, c.updated_at")

# 批量操作的"无证据"警告要用；口径与 review_queue 的 has_evidence 一致：
# 文字证据、附件、或已挂完整数据包，任一成立即算有证据（2026-10-22 补 packets）
_BUG_EVI_SQL = ("(length(trim(evidence))>0 OR EXISTS("
                "SELECT 1 FROM attachments a WHERE a.linked_type='bug' "
                "AND a.linked_id=bugs.id) OR EXISTS("
                "SELECT 1 FROM packets pk WHERE pk.linked_type='bug' "
                "AND pk.linked_id=bugs.id)) AS has_evi")

BUG_LIST_COLS = ("id, project_id, module, title, severity, review_status, reported_at, "
                 "review_comment, created_by, created_at, updated_at, " + _BUG_EVI_SQL)

# 最近一次执行结果：tie 用 id 兜底，和 ORDER BY id DESC LIMIT 1 语义一致
LATEST_EXEC_CTE = """WITH latest AS (
    SELECT case_id, result, created_at, executed_by,
           ROW_NUMBER() OVER (PARTITION BY case_id ORDER BY id DESC) AS rn
    FROM executions
)"""


def _rows(cursor):
    return [dict(r) for r in cursor]


def _distinct(conn, sql, args=()):
    return tuple(r[0] for r in conn.execute(sql, args) if r[0] not in (None, ""))


def modules(conn, table, pid):
    """某项目在某张表里用到的模块（筛选下拉的选项来源）。table 只传内部常量。"""
    return _distinct(conn,
                     f"SELECT DISTINCT module FROM {table} WHERE project_id=? "
                     "ORDER BY module", (pid,))


def module_counts(conn, table, pid):
    """模块 + 条数。筛选项的文案要带规模，否则 161 条摊到 22 个模块只能靠猜。"""
    return [(r[0], r[1]) for r in conn.execute(
        f"SELECT module, COUNT(*) FROM {table} WHERE project_id=? "
        "GROUP BY module ORDER BY module", (pid,)) if r[0]]


# ---------- 模块分组 ----------
# 模块名的命名约定是"一级分组-子模块"（侧边栏-客户 / 家长端-视频）。
# 分组不做成第二张表：模块词表的唯一来源仍是 interfaces/cases/bugs 的 module 列，
# 层级从名字派生即可。否则 AI 每次写接口都要多填一个可能填错的外键。

MODULE_SEP = "-"


def module_head(name):
    """一级分组头：'侧边栏-客户' -> '侧边栏'。没有分隔符或分隔符两侧有空的返回 ''。"""
    head, sep, tail = (name or "").partition(MODULE_SEP)
    head, tail = head.strip(), tail.strip()
    return head if (sep and head and tail) else ""


def module_groups(modules, min_size=1):
    """派生一级分组：{组名: (子模块, ...)}，按组名排序。

    min_size=1 是默认：模块名里带分隔符就属于某个分组，规则只有一条，
    不会出现"为什么会员侧不算分组"的疑问。调大它可以让"单成员分组"
    退回成散项（本项目里 会员侧-儿童档案 只有一个子模块）。
    """
    buckets = {}
    for m in modules:
        head = module_head(m)
        if head:
            buckets.setdefault(head, []).append(m)
    return {h: tuple(sorted(ms)) for h, ms in sorted(buckets.items())
            if len(ms) >= min_size}


def _ordered_groups(items, min_size):
    """分组按条数从多到少排：中文名字典序对用户没有意义（会员/侧边/家长），
    条数序能一眼看出哪块是主战场。条数相同再按名字，保证顺序确定。"""
    cnt = dict(items)
    groups = module_groups([m for m, _ in items], min_size)
    return sorted(groups.items(),
                  key=lambda kv: (-sum(cnt[m] for m in kv[1]), kv[0]))


def group_options(items, min_size=1):
    """分组下拉的选项：[(值, 文案), ...]，文案带该组总条数。"""
    cnt = dict(items)
    return [(h, f"{h}（{sum(cnt[m] for m in ms)}）") for h, ms in
            _ordered_groups(items, min_size)]


def module_options(items, only_group=None, selected=(), min_size=1):
    """模块多选面板的结构：[(组头 or None, [(值, 文案, 条数), ...]), ...]。

    only_group 有值时只列该组的子模块——分组已选，面板跟着收窄。
    但**已选模块里只要有一个不在该组**（手改 URL 才能凑出来），就退回全量：
    否则那个 checkbox 不会被渲染，一提交就把这个模块静默丢了。
    组头为 None 的那组是"没有前缀的散项"（系统 / 认证 / 登录），排在最后。
    条数单独给一份：面板要实时算"已选 N 个模块 / M 条接口"。
    """
    cnt = dict(items)
    groups = module_groups([m for m, _ in items], min_size)
    sel = set(selected or ())

    def pack(ms):
        return [(m, f"{m}（{cnt[m]}）", cnt[m]) for m in ms]

    if only_group in groups and sel <= set(groups[only_group]):
        return [(only_group, pack(groups[only_group]))]
    grouped = {m for ms in groups.values() for m in ms}
    out = [(h, pack(ms)) for h, ms in _ordered_groups(items, min_size)]
    loose = pack(sorted(m for m in cnt if m not in grouped))
    if loose:
        out.append((None, loose))
    return out


def group_field(label, items, prefix="", name="group", min_size=1):
    """按一级分组筛选的 Field：'侧边栏' 命中 '侧边栏-客户' 与 '侧边栏-素材'。

    复用 map 而不是新增字段类型：mapping 在取数时按项目实际模块算好，
    组名走 ? 占位，SQL 片段只来自代码。没有分组时返回 None，模板连下拉都不渲染。
    """
    heads = tuple(module_groups([m for m, _ in items], min_size))
    if not heads:
        return None
    mapping = tuple(
        (h, f"({prefix}module=? OR {prefix}module LIKE ? ESCAPE '{LIKE_ESC}')",
         (h, escape_like(h) + MODULE_SEP + "%"))
        for h in heads)
    return Field(name, "map", label=label, mapping=mapping)


# ---------- 接口 ----------

# 运行类型口径（2026-10-23）：自检/诊断轮不是被测对象的质量结论，网页默认只看回归。
# 老库的 kind 可能为空（增量迁移只加列不给值），一律当 regression，否则会被默认视图漏掉。
RUN_KIND_EXPR = "COALESCE(NULLIF(kind,''),'regression')"
RUN_VIEW_ALL = "all"


def tab_counts(conn, pid):
    """tab 上的计数：Bug 数全部记录（不再只数"未关闭未驳回"，状态轴已废弃）。

    `runs` 仍是全部轮次，另给 `runs_regression` / `runs_other`：Tab 上显示"回归/全部"，
    这样"回归了几轮"不会被自检、诊断轮撑大（16 轮里只有 7 轮是回归）。
    """
    one = lambda sql: conn.execute(sql, (pid,)).fetchone()[0]  # noqa: E731
    runs = one("SELECT COUNT(*) FROM runs WHERE project_id=?")
    runs_reg = one("SELECT COUNT(*) FROM runs WHERE project_id=? AND "
                   + RUN_KIND_EXPR + "='regression'")
    return {
        "docs": one("SELECT COUNT(*) FROM docs WHERE project_id=?"),
        "interfaces": one("SELECT COUNT(*) FROM interfaces WHERE project_id=?"),
        "cases": one("SELECT COUNT(*) FROM cases WHERE project_id=?"),
        "bugs": one("SELECT COUNT(*) FROM bugs WHERE project_id=?"),
        "runs": runs,
        "runs_regression": runs_reg,
        "runs_other": runs - runs_reg,
    }


def bug_todo_where(alias=""):
    """未结案（待审核 + 待上报）的 SQL 条件，全站唯一实现。

    导航栏角标、项目页默认视图、`/review` 收件箱必须共用它。曾经分叉过一次：
    角标按"待审核 + 待上报"数，收件箱只 SELECT pending，于是待上报的那条把
    角标撑成 1，点进去却是空的（只有进项目页才看得见）。
    """
    p = f"{alias}." if alias else ""
    return (f"({p}review_status = 'pending' OR "
            f"({p}review_status = 'approved' AND COALESCE({p}reported_at, '') = ''))")


def bug_todo_count(conn, pid=None):
    """未结案数 = 待审核 + 待上报。导航栏的待办数用它；pid 为空时跨项目统计。"""
    sql = f"SELECT COUNT(*) FROM bugs WHERE {bug_todo_where()}"
    if pid is None:
        return conn.execute(sql).fetchone()[0]
    return conn.execute(sql + " AND project_id=?", (pid,)).fetchone()[0]


def bug_todo_breakdown(conn):
    """跨项目待办拆成两半：待审核 / 待上报。角标 tooltip 与收件箱标题共用同一口径，
    两者相加恒等于队列长度。"""
    rows = dict(conn.execute(
        f"SELECT review_status, COUNT(*) FROM bugs WHERE {bug_todo_where()} "
        "GROUP BY review_status").fetchall())
    return {"pending": rows.get("pending", 0), "toreport": rows.get("approved", 0)}


def interface_spec(conn, pid):
    """模块词表取项目内实际值：手改 URL 里的模块名不会筛出空页。

    module 是**多选**（?module=A&module=B → IN）：AI 生成用例时要一次读多个模块，
    单选下标量丢参数不会有任何提示，最危险。
    """
    items = module_counts(conn, "interfaces", pid)
    modules = tuple(m for m, _ in items)
    fields = [
        Field("module", "eq", col="module", vocab=modules, label="模块", multi=True),
        Field("method", "eq", col="method", label="方法",
              vocab=("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")),
        Field("q", "like_multi", cols=("path", "name", "module"), label="关键字"),
    ]
    g = group_field("分组", items)
    if g:
        fields.insert(0, g)  # 分组在最左：先挑大块，再挑具体模块
    return tuple(fields)


def interfaces_page(conn, pid, args, per_page=50):
    """接口列表：返回 (rows, pager, filter_state)。"""
    f = build(interface_spec(conn, pid), args)
    where = " AND ".join(["project_id=?"] + f["where"])
    params = [pid] + f["params"]
    total = conn.execute(
        f"SELECT COUNT(*) FROM interfaces WHERE {where}", params).fetchone()[0]
    pg = paginate(total, args.get("page"), per_page)
    pg["all_total"] = conn.execute(
        "SELECT COUNT(*) FROM interfaces WHERE project_id=?", (pid,)).fetchone()[0]
    rows = _rows(conn.execute(
        f"SELECT {ITF_LIST_COLS} FROM interfaces WHERE {where} "
        "ORDER BY module, path LIMIT ? OFFSET ?",
        params + [pg["per_page"], pg["offset"]]))
    return rows, pg, f


def interfaces_tree(conn, pid):
    """目录树要全量（折叠浏览靠它），但不带 evidence。"""
    return _rows(conn.execute(
        f"SELECT {ITF_TREE_COLS} FROM interfaces WHERE project_id=? "
        "ORDER BY module, path", (pid,)))


def interface_stats(conn, pid):
    """接口 tab 头部的三个计数（已验证/有变更/未验证），一次 GROUP BY 拿完。"""
    out = {"verified": 0, "changed": 0, "unverified": 0}
    for r in conn.execute(
            "SELECT verify_status, COUNT(*) FROM interfaces WHERE project_id=? "
            "GROUP BY verify_status", (pid,)):
        out[r[0]] = r[1]
    return out


def interface_panel(conn, iid):
    """目录树右侧面板按需拉取的一整条契约（不含 evidence）。"""
    row = conn.execute(
        "SELECT id, project_id, module, name, method, path, host, req_headers, "
        "req_params, resp_example, error_codes, notes, verify_status, verified_at "
        "FROM interfaces WHERE id=?", (iid,)).fetchone()
    return dict(row) if row else None


# ---------- 用例 ----------

def case_spec(conn, pid):
    items = module_counts(conn, "cases", pid)
    modules = tuple(m for m, _ in items)
    fields = [
        Field("module", "eq", col="c.module", vocab=modules, label="模块", multi=True),
        Field("priority", "eq", col="c.priority", label="优先级",
              vocab=("P0", "P1", "P2", "P3")),
        Field("dim", "like", col="c.dims", vocab=DIM_VOCAB, label="覆盖维度"),
        Field("result", "map", label="执行结果", mapping=(
            ("pass", "l.result=?", ("pass",)),
            ("fail", "l.result=?", ("fail",)),
            ("blocked", "l.result=?", ("blocked",)),
            ("none", "l.result IS NULL", ()),
        )),
        Field("anchor", "map", label="锚点", mapping=(
            ("interface", "c.interface_id IS NOT NULL OR EXISTS(SELECT 1 FROM "
                          "case_interfaces ci WHERE ci.case_id=c.id)", ()),
            ("doc", "c.doc_id IS NOT NULL", ()),
            ("module", "c.interface_id IS NULL AND c.doc_id IS NULL AND NOT EXISTS("
                       "SELECT 1 FROM case_interfaces ci WHERE ci.case_id=c.id)", ()),
        )),
        Field("q", "like_multi", cols=("c.title", "c.expected", "c.steps"),
              label="关键字"),
    ]
    g = group_field("分组", items, prefix="c.")
    if g:
        fields.insert(0, g)
    return tuple(fields)


def cases_page(conn, pid, args, per_page=50):
    """用例列表：一次 join 出最近执行结果，不再逐条查 executions。"""
    f = build(case_spec(conn, pid), args)
    where = " AND ".join(["c.project_id=?"] + f["where"])
    params = [pid] + f["params"]
    join = f"{LATEST_EXEC_CTE} SELECT {CASE_LIST_COLS}, l.result AS last_result, " \
           "l.created_at AS last_at, l.executed_by AS last_by, " \
           "(SELECT GROUP_CONCAT(ci.interface_id) FROM case_interfaces ci " \
           " WHERE ci.case_id=c.id) AS interface_ids " \
           "FROM cases c LEFT JOIN latest l ON l.case_id=c.id AND l.rn=1 "
    count_sql = (f"{LATEST_EXEC_CTE} SELECT COUNT(*) FROM cases c "
                 "LEFT JOIN latest l ON l.case_id=c.id AND l.rn=1 ")
    total = conn.execute(count_sql + f"WHERE {where}", params).fetchone()[0]
    all_total = conn.execute(
        "SELECT COUNT(*) FROM cases WHERE project_id=?", (pid,)).fetchone()[0]
    pg = paginate(total, args.get("page"), per_page)
    pg["all_total"] = all_total
    rows = _rows(conn.execute(
        join + f"WHERE {where} ORDER BY c.updated_at DESC, c.id DESC "
               "LIMIT ? OFFSET ?", params + [pg["per_page"], pg["offset"]]))
    for c in rows:
        c["interface_ids"] = [int(x) for x in (c["interface_ids"] or "").split(",") if x]
    return rows, pg, f


def case_detail(conn, cid):
    """用例全文 + 全部执行历史（列表页不再内嵌这些）。"""
    row = conn.execute(
        "SELECT c.*, p.name AS project_name, p.id AS pid FROM cases c "
        "JOIN projects p ON c.project_id=p.id WHERE c.id=?", (cid,)).fetchone()
    if not row:
        return None, [], []
    case = dict(row)
    case["interface_ids"] = [r[0] for r in conn.execute(
        "SELECT interface_id FROM case_interfaces WHERE case_id=?", (cid,))]
    if not case["interface_ids"] and case.get("interface_id"):
        case["interface_ids"] = [case["interface_id"]]
    runs = _rows(conn.execute(
        "SELECT * FROM executions WHERE case_id=? ORDER BY id DESC", (cid,)))
    linked = _rows(conn.execute(
        "SELECT id, method, path, name FROM interfaces WHERE id IN (%s) "
        "ORDER BY path" % ",".join("?" * len(case["interface_ids"])),
        case["interface_ids"])) if case["interface_ids"] else []
    return case, runs, linked


# ---------- 文档 ----------

DOC_SPEC = (
    Field("dtype", "eq", col="dtype", vocab=tuple(DOC_TYPES), label="类型"),
    Field("q", "like_multi", cols=("title", "created_by"), label="关键字"),
)


def docs_list(conn, pid, args):
    f = build(DOC_SPEC, args)
    where = " AND ".join(["project_id=?"] + f["where"])
    rows = _rows(conn.execute(
        "SELECT id, project_id, dtype, title, created_by, created_at, updated_at "
        f"FROM docs WHERE {where} ORDER BY updated_at DESC", [pid] + f["params"]))
    all_total = conn.execute(
        "SELECT COUNT(*) FROM docs WHERE project_id=?", (pid,)).fetchone()[0]
    return rows, len(rows), f, all_total


# ---------- Bug ----------

BUG_SPEC = (
    # Bug 只有一条轴：分诊进度。四态由 review_status × reported_at 组合而成——
    # 开发只在公司在线表格跟进修复，平台不追踪"修没修"，status 列已删（见 db.py 迁移注释）。
    Field("progress", "map", default="todo", label="进度", mapping=(
        # 未结案 = 待审核 + 待上报：一条记录只有"已上报"或"已驳回"才离开视野
        ("todo", bug_todo_where(), ()),
        ("pending", "review_status='pending'", ()),
        ("toreport", "review_status='approved' AND reported_at = ''", ()),
        ("reported", "review_status='approved' AND reported_at != ''", ()),
        ("rejected", "review_status='rejected'", ()),
        ("all", "1=1", ()),
    )),
    Field("b_severity", "map", default="all", label="严重程度", mapping=(
        ("all", "1=1", ()),
        ("critical", "severity=?", ("critical",)),
        ("major", "severity=?", ("major",)),
        ("normal", "severity=?", ("normal",)),
        ("minor", "severity=?", ("minor",)),
    )),
    Field("q", "like_multi", cols=("title", "module", "steps"), label="关键字"),
)


def bug_spec(conn, pid):
    modules = _distinct(conn,
                        "SELECT DISTINCT module FROM bugs WHERE project_id=? "
                        "ORDER BY module", (pid,))
    return BUG_SPEC + (Field("module", "eq", col="module", vocab=modules,
                             label="模块"),)


def bugs_page(conn, pid, args, per_page=20):
    """Bug 走左右分栏，左栏一次只放 20 条。

    50 条/页在 70vh 高的滚动区里只能露出 9~12 张卡片（卡片约 76px），
    要滚 5~6 屏才够到分页按钮，连续处理时手感很差。20 条刚好两屏。
    """
    f = build(bug_spec(conn, pid), args)
    where = " AND ".join(["project_id=?"] + f["where"])
    params = [pid] + f["params"]
    total = conn.execute(
        f"SELECT COUNT(*) FROM bugs WHERE {where}", params).fetchone()[0]
    pg = paginate(total, args.get("page"), per_page)
    pg["all_total"] = conn.execute(
        "SELECT COUNT(*) FROM bugs WHERE project_id=?", (pid,)).fetchone()[0]
    rows = _rows(conn.execute(
        f"SELECT {BUG_LIST_COLS} FROM bugs WHERE {where} "
        "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        params + [pg["per_page"], pg["offset"]]))
    return rows, pg, f


def bug_attachments(conn, bug_ids):
    """一次 IN 取完附件，别在循环里查。"""
    out = {}
    if not bug_ids:
        return out
    marks = ",".join("?" * len(bug_ids))
    for a in conn.execute(
            f"SELECT * FROM attachments WHERE linked_type='bug' "
            f"AND linked_id IN ({marks})", bug_ids):
        out.setdefault(a["linked_id"], []).append(dict(a))
    return out


def bug_detail(conn, bid):
    row = conn.execute(
        "SELECT b.*, p.name AS project_name, p.id AS pid FROM bugs b "
        "JOIN projects p ON b.project_id=p.id WHERE b.id=?", (bid,)).fetchone()
    if not row:
        return None, []
    atts = _rows(conn.execute(
        "SELECT * FROM attachments WHERE linked_type='bug' AND linked_id=?"
        " ORDER BY id", (bid,)))
    return dict(row), atts


# ---------- 审核队列 ----------

def review_queue(conn):
    """跨项目待办队列 = 未结案（待审核 + 待上报）；附件数用子查询带出，避免逐条 COUNT。

    口径必须与导航栏角标（bug_todo_breakdown）一致：待上报的那条也要在这里出现，
    否则角标有数、页面为空，人只能挨个项目点进去找。待审核排前面（要先审），
    待上报在后（只差抄进在线表格）。
    """
    rows = _rows(conn.execute(
        "SELECT b.id, b.project_id, b.title, b.severity, b.review_status, b.reported_at, "
        "b.created_by, b.created_at, b.evidence, b.module, p.name AS project_name, "
        "(SELECT COUNT(*) FROM attachments a WHERE a.linked_type='bug' "
        " AND a.linked_id=b.id) AS n_atts "
        "FROM bugs b JOIN projects p ON b.project_id=p.id "
        f"WHERE {bug_todo_where('b')} "
        "ORDER BY CASE b.review_status WHEN 'pending' THEN 0 ELSE 1 END, b.created_at"))
    for it in rows:
        it["has_evidence"] = bool((it.get("evidence") or "").strip()) or it["n_atts"] > 0
    return rows


# ---------- 操作日志 ----------

def audit_spec(conn):
    actors = _distinct(conn, "SELECT DISTINCT actor FROM audit ORDER BY actor")
    actions = _distinct(conn, "SELECT DISTINCT action FROM audit ORDER BY action")
    return (
        Field("actor", "eq", col="actor", vocab=actors, label="操作者"),
        Field("action", "eq", col="action", vocab=actions, label="动作"),
        Field("q", "like_multi", cols=("action", "target", "detail"), label="关键字"),
    )


def audit_options(conn):
    """日志筛选下拉的两个选项表（操作者 / 动作）。"""
    actors = [(r[0], r[0]) for r in conn.execute(
        "SELECT DISTINCT actor FROM audit ORDER BY actor")]
    actions = [(r[0], r[0]) for r in conn.execute(
        "SELECT DISTINCT action FROM audit ORDER BY action")]
    return actors, actions


def audit_page(conn, args, per_page=50):
    f = build(audit_spec(conn), args)
    where = " AND ".join(f["where"] or ["1=1"])
    params = list(f["params"])
    total = conn.execute(
        f"SELECT COUNT(*) FROM audit WHERE {where}", params).fetchone()[0]
    pg = paginate(total, args.get("apage"), per_page)
    pg["all_total"] = conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    rows = _rows(conn.execute(
        "SELECT * FROM audit WHERE " + where +
        " ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [pg["per_page"], pg["offset"]]))
    return rows, pg, f


# ---------- 执行批次（runs）：列表 / 详情 ----------
# 观测口径：运行中按 executions 现算，终态读 summary（见 core/runs.py run_progress）。

def _json(raw, default):
    try:
        return json.loads(raw) if raw else default
    except (ValueError, TypeError):
        return default


def results_by_run(conn, run_ids):
    """一次 GROUP BY 取回多轮的结果，避免列表页每行一次查询。"""
    ids = [i for i in (run_ids or []) if i is not None]
    if not ids:
        return {}
    out = {}
    for r in _rows(conn.execute(
            "SELECT run_id, result, COUNT(*) AS n FROM executions "
            f"WHERE run_id IN ({','.join('?' * len(ids))}) "
            "GROUP BY run_id, result", ids)):
        out.setdefault(r["run_id"], []).extend([r["result"]] * r["n"])
    return out


def scoped_cases(conn, project_id, scope):
    """一轮 run 范围内的候选用例（只取执行与分类要用的列）。"""
    clause, args = scope_where(scope or {})
    return _rows(conn.execute(
        "SELECT id, title, module, priority, steps_json FROM cases "
        f"WHERE project_id=? AND ({clause}) ORDER BY id", [project_id] + args))


def runs_page(conn, pid, args, now_str, per_page=50):
    """运行列表：类型 + 状态筛选 + 分页。

    类型口径（2026-10-23）：URL 不带 kind 时**默认只看回归**。自检只证明平台与管道、
    诊断只排查网络/部署，混进默认视图会让"回归了几轮、红了几条"变成假数
    （存量 16 轮里 9 轮不是回归）。要看全部显式给 `kind=all`；词表外的值仍按
    "没传"处理（回到默认回归），免得旧书签 / 手改 URL 筛出空页。

    `?status=stalled` 是派生状态（running 且心跳超时），SQL 里直接按同一个时间界
    过滤，不能用"先查全部再过滤"——那样分页数和实际条数会对不上。
    """
    raw_kind = (args.get("kind") or "").strip().lower()
    if raw_kind == RUN_VIEW_ALL:
        kind = RUN_VIEW_ALL
    elif raw_kind in RUN_KINDS:
        kind = raw_kind
    else:
        kind = "regression"                 # 缺省与词表外都落到默认视图
    state = {"status": (args.get("status") or "").strip(), "kind": kind}

    where, params = ["project_id=?"], [pid]
    kind_where, kind_params = "", []
    if kind != RUN_VIEW_ALL:
        kind_where = " AND " + RUN_KIND_EXPR + "=?"
        kind_params = [kind]
        where.append(RUN_KIND_EXPR + "=?")
        params.append(kind)

    if state["status"] == "stalled":
        where.append("status='running'")
        where.append("COALESCE(NULLIF(last_heartbeat_at,''), NULLIF(started_at,''), "
                     "created_at) < ?")
        params.append(stall_cutoff(now_str))
    elif state["status"] in RUN_STATUSES:
        where.append("status=?")
        params.append(state["status"])
    else:
        state["status"] = ""

    clause = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM runs WHERE {clause}", params).fetchone()[0]
    pg = paginate(total, args.get("page"), per_page)
    # all_total 是"当前类型口径内"的轮次数：否则会出现「共 16 轮，筛出 7 轮」，
    # 而清除筛选后还是 7 轮，数字自相矛盾。grand_total 才是全项目轮次。
    pg["all_total"] = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE project_id=?" + kind_where,
        [pid] + kind_params).fetchone()[0]
    pg["grand_total"] = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE project_id=?", (pid,)).fetchone()[0]

    rows = _rows(conn.execute(
        f"SELECT * FROM runs WHERE {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [pg["per_page"], pg["offset"]]))
    results = results_by_run(conn, [r["id"] for r in rows])
    for r in rows:
        r["scope"] = _json(r.get("scope"), {})
        r["summary"] = _json(r.get("summary"), {})
        r["progress"] = run_progress(r, results.get(r["id"], ()))
        r["stalled"] = is_stalled(r, now_str)

    # "全部类型"不是筛选条件（它就是不筛），所以不计入 active，结果行不会写
    # "按 类型 筛出 16 轮"这种废话。
    active = [name for key, name in (("kind", "类型"), ("status", "状态"))
              if state[key] and not (key == "kind" and kind == RUN_VIEW_ALL)]
    others = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE project_id=? AND " + RUN_KIND_EXPR + "!='regression'",
        (pid,)).fetchone()[0]
    f = {"state": state, "active": active, "where": where, "params": params,
         "others": others, "grand_total": pg["grand_total"]}
    return rows, pg, f


def attach_baseline_diff(conn, run, execs):
    """给 run 挂上 baseline/diff/diff_cases（2026-10-26 落地 baseline_run_id）。

    网页（/runs/<id>）与 API（/api/runs/<id>）共用这一份：用户在看板、AI 在读
    JSON，两边必须同一套答案——曾出现"网页有卡片、API 不返回"的割裂。
    execs 需含 case_id 与 result；没有基准轮或基准轮不存在时三项留空。
    """
    run["baseline"], run["diff"], run["diff_cases"] = None, None, {}
    if not run.get("baseline_run_id"):
        return run
    brow = conn.execute("SELECT id, name, kind, status FROM runs WHERE id=?",
                        (run["baseline_run_id"],)).fetchone()
    if not brow:
        return run
    bres = {r["case_id"]: r["result"] for r in conn.execute(
        "SELECT case_id, result FROM executions WHERE run_id=?",
        (run["baseline_run_id"],))}
    scope_ids = {c["id"] for c in
                 scoped_cases(conn, run["project_id"], run.get("scope") or {})}
    run["baseline"] = dict(brow)
    run["diff"] = regression_diff(
        bres, {e["case_id"]: e["result"] for e in execs}, scope_ids)
    diff_ids = [cid for v in run["diff"].values() for cid in v]
    if diff_ids:
        marks = ",".join("?" * len(diff_ids))
        run["diff_cases"] = {r["id"]: r["title"] for r in conn.execute(
            f"SELECT id, title FROM cases WHERE id IN ({marks})", diff_ids)}
    return run


def run_detail(conn, rid, now_str):
    """一轮 run 的全貌：进度、每条执行、还没跑到的用例、跑不了的用例（带原因）。"""
    row = conn.execute(
        "SELECT r.*, p.name AS project_name, p.id AS pid FROM runs r "
        "JOIN projects p ON r.project_id=p.id WHERE r.id=?", (rid,)).fetchone()
    if not row:
        return None, [], {}
    run = dict(row)
    run["scope"] = _json(run.get("scope"), {})
    run["summary"] = _json(run.get("summary"), {})
    execs = _rows(conn.execute(
        "SELECT e.*, c.title AS case_title, c.module AS case_module "
        "FROM executions e LEFT JOIN cases c ON c.id=e.case_id "
        "WHERE e.run_id=? ORDER BY e.id", (rid,)))
    run["progress"] = run_progress(run, [e["result"] for e in execs])
    run["stalled"] = is_stalled(run, now_str)
    run["heartbeat_at"] = heartbeat_at(run)
    if execs:
        ids = [e["id"] for e in execs]
        pkt = {r["linked_id"]: r["n"] for r in _rows(conn.execute(
            "SELECT linked_id, COUNT(*) AS n FROM packets WHERE linked_type='execution' "
            f"AND linked_id IN ({','.join('?' * len(ids))}) GROUP BY linked_id", ids))}
        for e in execs:
            e["packet_count"] = pkt.get(e["id"], 0)
    done_ids = {e["case_id"] for e in execs}
    runnable, unrunnable = classify_cases(
        scoped_cases(conn, run["project_id"], run["scope"]))
    # 回归 diff（2026-10-26 落地 baseline_run_id）：与基准轮对比，
    # 回答"比上轮多了哪些红、修好了哪些、一直红着哪些"。网页与 API 共用。
    attach_baseline_diff(conn, run, execs)
    return run, execs, {
        "pending": [c for c in runnable if c["id"] not in done_ids],
        "unrunnable": unrunnable,
    }


# ---------- 数据质量看板（独立评审修复项 13） ----------

# 每个指标的健康线。低于线 = "仪表盘绿、发动机空"的信号，看板上变色提醒。
# 这些线只是提示，不是门禁——超线不拦任何操作，只让人看见。
QUALITY_THRESHOLDS = {
    "verify_rate": 0.3,     # 真实验证率：有 full packet 的接口 ÷ 总接口
    "runnable_rate": 0.5,   # 可执行用例率：带 checks 的用例 ÷ 总用例
    "bug_pass_rate": 0.5,   # Bug 提交通过率：approved ÷ (approved + rejected)
    "orphan_execs": 0,      # 孤儿执行记录：run_id 为空的 executions
    # 2026-10-27 加：总量绿不代表测到了。161 接口里 125 个零用例、22 个模块只有
    # 1 个有 UI 用例，原四个指标全绿——这两条把"覆盖"本身变成可红的指标。
    "interface_coverage": 0.8,    # 有用例的接口 ÷ 总接口
    "ui_modules_coverage": 0.3,   # 有 UI 用例的模块 ÷ 有接口的模块
}


def quality_stats(conn, pid):
    """一个项目的数据质量：四个把"看起来在用"和"真的在用"分开的指标。

    起因（2026-10-26 独立评审）：线上 161 个接口全标 verified，只有 3 个有
    完整数据包；165 条用例里能跑的只有 21 条；Bug 57 投 55 驳。总量一路飘绿，
    发动机是空的——这四个数字就是要把这件事在首页摊开：
    1. 真实验证率——接口标 verified 不算数，挂完整数据包才算（verify_status
       只描述"上次什么时候验的"，不保证有证据）；
    2. 可执行用例率——没有 checks 的用例 runner 一律跳过，写了也跑不了；
    3. Bug 提交通过率——通过率长期偏低说明提交侧自检不足（查重/证据/复现步骤），
       审核的人在被误报淹没；
    4. 孤儿执行记录——run_id 为空的 execution 答不了"哪一轮跑的"，趋势图画不出来。
    """
    itf_total = conn.execute(
        "SELECT COUNT(*) c FROM interfaces WHERE project_id=?", (pid,)).fetchone()["c"]
    itf_full = conn.execute(
        "SELECT COUNT(DISTINCT pk.linked_id) c FROM packets pk "
        "JOIN interfaces i ON i.id = pk.linked_id "
        "WHERE i.project_id=? AND pk.linked_type='interface' "
        "AND pk.completeness='full'", (pid,)).fetchone()["c"]
    cases = _rows(conn.execute(
        "SELECT id, title, module, steps_json FROM cases WHERE project_id=?", (pid,)))
    runnable, _ = classify_cases(cases)
    # UI 覆盖单独一条轴：steps_json 里真的有 ui 步骤才算，补 dims 不算
    ui_cases = [c for c in cases if is_ui_case(c.get("steps_json"))]
    bug_rows = _rows(conn.execute(
        "SELECT review_status, COUNT(*) c FROM bugs WHERE project_id=? "
        "GROUP BY review_status", (pid,)))
    decided = sum(r["c"] for r in bug_rows if r["review_status"] in ("approved", "rejected"))
    approved = next((r["c"] for r in bug_rows if r["review_status"] == "approved"), 0)
    orphan = conn.execute(
        "SELECT COUNT(*) c FROM executions e JOIN cases c ON c.id = e.case_id "
        "WHERE c.project_id=? AND (e.run_id IS NULL OR e.run_id='')",
        (pid,)).fetchone()["c"]
    return {
        "thresholds": QUALITY_THRESHOLDS,
        "interfaces": {"total": itf_total, "full": itf_full,
                       "rate": (itf_full / itf_total) if itf_total else None},
        "coverage": interface_coverage(conn, pid),
        "ui": ui_module_coverage(conn, pid, ui_cases),
        "cases": {"total": len(cases), "runnable": len(runnable),
                  "rate": (len(runnable) / len(cases)) if cases else None},
        "bugs": {"approved": approved, "decided": decided,
                 "rate": (approved / decided) if decided else None},
        "orphan_execs": orphan,
        "runs": conn.execute(
            "SELECT COUNT(*) c FROM runs WHERE project_id=?", (pid,)).fetchone()["c"],
    }
