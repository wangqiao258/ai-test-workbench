"""覆盖矩阵与模块词表。"""

from flask import jsonify, request

from . import api_bp

from .common import rows_to_list, table_cols

from .deps import token_required

from core.validation import DIM_VOCAB, parse_dims

from core.coverage import is_ui_case, summarize

from core.filters import LIKE_ESC, escape_like

from db import get_db

@api_bp.route("/coverage")
@token_required
def api_coverage():
    """覆盖矩阵：每个接口覆盖了哪些维度、还缺哪些。

    AI 生成新用例前读它，就不必把全项目用例正文拉进上下文：
    返回的是"标题 + 维度 + 缺口"，不是 steps 全文。三种取范围的方式（互斥，先命中先用）：

        ?module=A&module=B   多个模块（AI 一次补多条线的用例）
        ?group=侧边栏         一整块（= 侧边栏-* 的全部模块，比手拼 13 个模块名省事）
        都不传                全项目（161 个接口，只适合做总览）

    参数：project_id（必填）、module/group、only_missing=1（只看没用例的接口）
    """
    pid = request.args.get("project_id", type=int)
    if not pid:
        return jsonify({"error": "project_id required"}), 400
    mods = [m.strip() for m in request.args.getlist("module") if m.strip()]
    group = (request.args.get("group") or "").strip()
    only_missing = request.args.get("only_missing") in ("1", "true", "yes")
    cond, args = "project_id=?", [pid]
    if mods:
        cond += f" AND module IN ({','.join('?' * len(mods))})"
        args.extend(mods)
    elif group:
        cond += f" AND (module=? OR module LIKE ? ESCAPE '{LIKE_ESC}')"
        args.extend([group, escape_like(group) + "-%"])

    def in_scope(m):
        """这条用例算不算在当前范围里（用于"没挂接口的用例"那一列）。"""
        if mods:
            return m in mods
        if group:
            return m == group or (m or "").startswith(group + "-")
        return True

    conn = get_db()
    itf_rows = [dict(r) for r in conn.execute(
        f"SELECT id, module, name, method, path, host, verify_status "
        f"FROM interfaces WHERE {cond} ORDER BY path", args)]
    cols = table_cols("cases")
    sel_cols = ["id", "title", "expected", "interface_id", "module"]
    for optional in ("dims", "steps_json", "doc_id"):
        if optional in cols:
            sel_cols.append(optional)
    # 用例按"接口"归集，不按 cases.module 过滤：module 是派生字段，老数据可能还没同步，
    # 用 module 过滤会静默漏掉已挂在该接口上的用例。
    case_rows = rows_to_list(conn.execute(
        f"SELECT {', '.join(sel_cols)} FROM cases WHERE project_id=?", (pid,)))
    links = {}
    for lk in conn.execute(
            "SELECT ci.case_id, ci.interface_id FROM case_interfaces ci "
            "JOIN cases c ON c.id=ci.case_id WHERE c.project_id=?", (pid,)):
        links.setdefault(lk["case_id"], []).append(lk["interface_id"])
    # 页面/流程文档：UI 用例的锚点，也是"这个模块到底有没有页面事实"的依据
    page_docs = rows_to_list(conn.execute(
        "SELECT id, title, dtype FROM docs WHERE project_id=? "
        "AND dtype IN ('page', 'flow') ORDER BY id", (pid,)))
    conn.close()

    by_itf, unlinked = {}, []
    for c in case_rows:
        c["dims"] = parse_dims(c.get("dims"))
        # 一条用例可覆盖多个接口：关联表优先，没有关联记录时回退到主锚点
        targets = links.get(c["id"]) or ([c["interface_id"]] if c["interface_id"] else [])
        if targets:
            for tid in targets:
                by_itf.setdefault(tid, []).append(c)
        elif in_scope(c["module"]):
            unlinked.append(c)

    items, covered_cnt = [], 0
    for r in itf_rows:
        cs = by_itf.get(r["id"], [])
        covered = [d for d in DIM_VOCAB if any(d in c["dims"] for c in cs)]
        if cs:
            covered_cnt += 1
        if only_missing and cs:
            continue
        items.append({
            "id": r["id"], "module": r["module"], "name": r["name"],
            "method": r["method"], "path": r["path"],
            "verify_status": r["verify_status"],
            "n_cases": len(cs),
            "dims_covered": covered,
            "dims_missing": [d for d in DIM_VOCAB if d not in covered],
            "cases": [{"id": c["id"], "title": c["title"],
                       "expected": c["expected"], "dims": c["dims"]} for c in cs],
        })
    # 一条用例挂多个接口时只计一次
    matched = {c["id"] for r in itf_rows for c in by_itf.get(r["id"], [])}
    matched |= {c["id"] for c in unlinked}

    # UI / 缺口口径与首页质量面板同源（core/coverage.py），避免两处各算一套
    summary = summarize(itf_rows, case_rows, links, page_docs)
    ui_full = (request.args.get("ui") or "").strip().lower() == "full"
    if ui_full:
        doc_module = {}
        for c in case_rows:
            did = c.get("doc_id")
            if did and c.get("module"):
                doc_module.setdefault(did, c["module"])
        pages = [{
            "id": d["id"], "title": d["title"], "dtype": d["dtype"],
            "module": doc_module.get(d["id"], ""),
            "ui_cases": sum(1 for c in case_rows
                            if c.get("doc_id") == d["id"] and is_ui_case(c.get("steps_json"))),
        } for d in page_docs]
    else:
        # 默认只给计数：页面明细在模块行里已有，整份展开会把小接口项目的响应撑大
        pages = {"total": len(page_docs),
                 "used_by_cases": len({c.get("doc_id") for c in case_rows if c.get("doc_id")})}

    return jsonify({
        "project_id": pid,
        "module": mods[0] if len(mods) == 1 else None,   # 单值兼容旧调用
        "modules": mods or None,
        "group": group or None,
        "dim_vocabulary": list(DIM_VOCAB),
        "totals": {
            "interfaces": len(itf_rows),
            "interfaces_with_cases": covered_cnt,
            "interfaces_without_cases": len(itf_rows) - covered_cnt,
            "cases": len(matched),
            # 以下为覆盖缺口口径（2026-10-27）：UI 覆盖不参与 dims，单独一条轴
            "cases_total": summary["totals"]["cases_total"],
            "interface_coverage": summary["totals"]["interface_coverage"],
            "ui_cases": summary["totals"]["ui_cases"],
            "ui_modules_total": summary["totals"]["ui_modules_total"],
            "ui_modules_covered": summary["totals"]["ui_modules_covered"],
            "ui_modules_coverage": summary["totals"]["ui_modules_coverage"],
        },
        "interfaces": items,
        "ui": {"modules": summary["ui"]["modules"], "pages": pages},
        "gaps": summary["gaps"],
        "unlinked_cases": [{"id": c["id"], "module": c["module"], "title": c["title"],
                            "dims": c["dims"]} for c in unlinked],
    })

@api_bp.route("/modules")
@token_required
def api_modules():
    """项目的模块词表（受控词表，来自 interfaces.module，附接口数/用例数）。"""
    pid = request.args.get("project_id", type=int)
    if not pid:
        return jsonify({"error": "project_id required"}), 400
    conn = get_db()
    itf_cnt = {r["module"]: r["c"] for r in conn.execute(
        "SELECT module, COUNT(*) c FROM interfaces WHERE project_id=? GROUP BY module", (pid,))}
    case_cnt = {r["module"]: r["c"] for r in conn.execute(
        "SELECT module, COUNT(*) c FROM cases WHERE project_id=? GROUP BY module", (pid,))}
    names, sort = [], {}
    if "modules" in [t[0] for t in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]:
        for r in conn.execute("SELECT name, sort FROM modules WHERE project_id=?", (pid,)):
            sort[r["name"]] = r["sort"]
            names.append(r["name"])
    conn.close()
    names = sorted(set(names) | set(itf_cnt) | set(case_cnt),
                   key=lambda n: (sort.get(n, 10 ** 6), n))
    return jsonify([{"name": n, "interfaces": itf_cnt.get(n, 0),
                     "cases": case_cnt.get(n, 0)} for n in names])

