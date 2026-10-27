"""覆盖缺口的统一口径（无 IO，便于单测与三个调用方复用）。

调用方必须共用这一份，否则会出现"首页说 22%、覆盖矩阵说 20%"：
- api/coverage.py     覆盖矩阵响应
- core/lists.py       首页质量面板
- api/generation.py   按缺口派活

核心口径：**UI 用例 = steps_json 里真的有 ui 步骤的用例，不看 dims。**
给一个模块补多少维度都不会让它的 UI 覆盖变成 1——这正是"AI 只补接口维度、
不测 UI"能在原有统计里藏住的原因。
"""
import json

from core.validation import DIM_VOCAB, parse_dims


def case_struct(steps_json):
    """steps_json 可能是 JSON 串、dict 或空；统一成 dict 或 None。"""
    if not steps_json:
        return None
    if isinstance(steps_json, dict):
        return steps_json
    try:
        val = json.loads(steps_json)
    except (TypeError, ValueError):
        return None
    return val if isinstance(val, dict) else None


def has_ui_step(struct):
    if not isinstance(struct, dict):
        return False
    return any(isinstance(s.get("ui"), dict) for s in struct.get("steps") or [])


def is_ui_case(steps_json):
    """一条用例算不算 UI 用例：有任意一步是页面动作。

    不用 kind 判定：kind=mixed 的用例也含 UI 步骤，只看 kind 会漏；
    更不能用 steps_json LIKE '%"ui"%'——请求体里出现 "ui" 键就会误判。
    """
    return has_ui_step(case_struct(steps_json))


def dims_of(row):
    """用例行的 dims 归一成 list（可能是 JSON 串或已解析）。"""
    val = row.get("dims")
    return list(val) if isinstance(val, (list, tuple)) else parse_dims(val)


def _ratio(num, den):
    return round(num / den, 4) if den else None


def summarize(itf_rows, case_rows, links, page_docs=()):
    """把范围内的接口/用例/文档算成覆盖缺口。

    itf_rows   当前范围的接口行（需 id / module）
    case_rows  当前项目的全部用例行（需 id / module / dims / steps_json / interface_id / doc_id）
    links      {case_id: [interface_id]}（case_interfaces 关联表）
    page_docs  page/flow 文档行（需 id / title / dtype）

    用例按接口归集：有关联表用关联表，没有就回退主锚点；都没有则按 module 落到模块。
    这样跨接口用例、仅模块用例都不会在两套统计里各算一次。
    """
    modules = {}
    for r in itf_rows:
        m = r.get("module") or ""
        if not m:
            continue          # 空模块不进词表，但接口仍计入 totals.interfaces
        item = modules.setdefault(m, {"module": m, "interfaces": 0, "case_ids": set(),
                                      "ui_case_ids": set(), "doc_ids": set(), "_dims": {}})
        item["interfaces"] += 1

    by_itf = {}
    for c in case_rows:
        cid = c["id"]
        targets = links.get(cid) or ([c["interface_id"]] if c.get("interface_id") else [])
        if targets:
            for tid in targets:
                by_itf.setdefault(tid, []).append(c)

    itf_module = {r["id"]: (r.get("module") or "") for r in itf_rows}
    for c in case_rows:
        cid = c["id"]
        struct = c.get("steps_json")
        is_ui = is_ui_case(struct)
        dims = dims_of(c)
        targets = links.get(cid) or ([c["interface_id"]] if c.get("interface_id") else [])
        hit_modules = {itf_module[t] for t in targets
                       if t in itf_module and itf_module[t]}
        if not hit_modules:
            # 无接口锚点（页面 / 跨切面用例）按它自己的 module 落到范围内
            m = c.get("module") or ""
            if m in modules:
                hit_modules = {m}
        for m in hit_modules:
            item = modules[m]
            item["case_ids"].add(cid)
            if is_ui:
                item["ui_case_ids"].add(cid)
            if c.get("doc_id"):
                item["doc_ids"].add(c["doc_id"])
            item["_dims"][cid] = dims

    page_by_id = {d["id"]: d for d in page_docs}
    module_rows, gaps_cases, gaps_ui = [], [], []
    for m in sorted(modules, key=lambda x: (-modules[x]["interfaces"], x)):
        item = modules[m]
        dims_by_case = item.pop("_dims", {})
        case_dims = [d for cid in item["case_ids"] for d in dims_by_case.get(cid, [])]
        ui_dims = [d for cid in item["ui_case_ids"] for d in dims_by_case.get(cid, [])]
        covered = [d for d in DIM_VOCAB if d in case_dims]
        ui_covered = [d for d in DIM_VOCAB if d in ui_dims]
        pages = [{"id": d, "title": page_by_id[d]["title"], "dtype": page_by_id[d]["dtype"]}
                 for d in sorted(item["doc_ids"]) if d in page_by_id]
        row = {
            "module": m,
            "interfaces": item["interfaces"],
            "cases": len(item["case_ids"]),
            "ui_cases": len(item["ui_case_ids"]),
            "dims_covered": covered,
            "dims_missing": [d for d in DIM_VOCAB if d not in covered],
            "ui_dims_covered": ui_covered,
            "ui_dims_missing": [d for d in DIM_VOCAB if d not in ui_covered],
            "page_docs": pages,
        }
        module_rows.append(row)
        if not item["case_ids"]:
            gaps_cases.append({"module": m, "interfaces": item["interfaces"]})
        if not item["ui_case_ids"]:
            gaps_ui.append({"module": m, "interfaces": item["interfaces"]})

    itf_total = len(itf_rows)
    itf_covered = sum(1 for r in itf_rows
                      if by_itf.get(r["id"]))
    ui_case_ids = {c["id"] for c in case_rows if is_ui_case(c.get("steps_json"))}
    ui_modules_total = len(modules)
    ui_modules_covered = sum(1 for r in module_rows if r["ui_cases"])
    return {
        "totals": {
            "interfaces": itf_total,
            "interfaces_with_cases": itf_covered,
            "interfaces_without_cases": itf_total - itf_covered,
            "cases_total": len(case_rows),
            "interface_coverage": _ratio(itf_covered, itf_total),
            "ui_cases": len(ui_case_ids),
            "ui_modules_total": ui_modules_total,
            "ui_modules_covered": ui_modules_covered,
            "ui_modules_coverage": _ratio(ui_modules_covered, ui_modules_total),
        },
        "ui": {"modules": module_rows},
        "gaps": {"modules_without_cases": gaps_cases, "modules_without_ui": gaps_ui},
    }


def load_summary(conn, pid):
    """查库并汇总全项目缺口（按缺口派活时用）。

    api/coverage.py 不走这里：它的接口范围要按 module/group 过滤，自己查更直接。
    """
    itf_rows = [dict(r) for r in conn.execute(
        "SELECT id, module FROM interfaces WHERE project_id=?", (pid,))]
    cols = [r[1] for r in conn.execute("PRAGMA table_info(cases)")]
    sel = ["id", "module", "interface_id"]
    for optional in ("dims", "steps_json", "doc_id"):
        if optional in cols:
            sel.append(optional)
    case_rows = [dict(r) for r in conn.execute(
        f"SELECT {', '.join(sel)} FROM cases WHERE project_id=?", (pid,))]
    links = {}
    for lk in conn.execute(
            "SELECT ci.case_id, ci.interface_id FROM case_interfaces ci "
            "JOIN cases c ON c.id=ci.case_id WHERE c.project_id=?", (pid,)):
        links.setdefault(lk["case_id"], []).append(lk["interface_id"])
    page_docs = [dict(r) for r in conn.execute(
        "SELECT id, title, dtype FROM docs WHERE project_id=? "
        "AND dtype IN ('page', 'flow') ORDER BY id", (pid,))]
    return summarize(itf_rows, case_rows, links, page_docs)


def gap_targets(summary, include="both", limit=8):
    """把覆盖缺口转成待登记的测试目标（纯数据，不写库）。

    每个模块最多一条目标：零用例模块先给"补接口用例"，已经有用例但没 UI 的
    模块才给"补页面链路"。同一模块派两条会互相挤占本轮 5~10 个目标的名额。
    """
    items = []
    zero_modules = {g["module"] for g in summary["gaps"]["modules_without_cases"]}
    if include in ("api", "both"):
        for g in summary["gaps"]["modules_without_cases"]:
            items.append({
                "module": g["module"],
                "title": f'{g["module"]}：{g["interfaces"]} 个接口零用例',
                "intent": (f'模块 {g["module"]} 共 {g["interfaces"]} 个接口，当前 0 条用例；'
                           "按风险先挑有副作用的接口（写/删除/状态变更/鉴权）补正常流 + 一个"
                           "边界场景，同模块的纯查询合并成一条用例并用 interface_ids 挂全"),
                "source_ref": "coverage.gaps.modules_without_cases",
                "gap_kind": "api",
            })
    if include in ("ui", "both"):
        for g in summary["gaps"]["modules_without_ui"]:
            if g["module"] in zero_modules:
                continue          # 已由上面的接口目标覆盖，不再重复派活
            items.append({
                "module": g["module"],
                "title": f'{g["module"]}：页面链路零 UI 用例',
                "intent": (f'模块 {g["module"]} 有 {g["interfaces"]} 个接口但 0 条 UI 用例；'
                           "先补 page 文档写清地址/关键元素文本/交互，再写打开→关键元素→"
                           "点击→断言的链路，每步带 checks"),
                "source_ref": "coverage.gaps.modules_without_ui",
                "gap_kind": "ui",
            })
    return items[:limit]


def interface_coverage(conn, pid):
    """全项目的接口覆盖率（首页质量面板用，SQL 口径与覆盖矩阵一致）。"""
    total = conn.execute(
        "SELECT COUNT(*) FROM interfaces WHERE project_id=?", (pid,)).fetchone()[0]
    covered = conn.execute(
        "SELECT COUNT(DISTINCT i.id) FROM interfaces i WHERE i.project_id=? AND ("
        "EXISTS(SELECT 1 FROM cases c WHERE c.interface_id=i.id) OR "
        "EXISTS(SELECT 1 FROM case_interfaces ci WHERE ci.interface_id=i.id))",
        (pid,)).fetchone()[0]
    return {"total": total, "covered": covered, "rate": _ratio(covered, total)}


def ui_module_coverage(conn, pid, ui_cases):
    """UI 覆盖率 = 有 UI 用例的模块 ÷ 有接口的模块。

    ui_cases 由调用方传入（它通常已经为 classify_cases 解析过全部用例），
    避免在这里再扫一遍 cases 表。
    """
    modules_total = conn.execute(
        "SELECT COUNT(DISTINCT module) FROM interfaces WHERE project_id=? AND module!=''",
        (pid,)).fetchone()[0]
    covered = {c.get("module") for c in ui_cases if c.get("module")}
    return {"total": modules_total, "covered": len(covered),
            "cases": len(ui_cases), "rate": _ratio(len(covered), modules_total)}
