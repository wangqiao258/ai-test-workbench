"""执行批次（run）的纯规则：scope 校验、状态机、summary、可执行性。

不连库、不碰 Flask。查询条件只生成 SQL 片段，由 api 层拼装。
"""

import json

from datetime import datetime, timedelta

from .steps import parse_steps

RUN_STATUSES = ("queued", "running", "done", "failed")

# 僵尸判定阈值：单条用例最长实测 151 秒（run 6 的 case 30，连接超时 30s × 多步），
# 取 180 秒留余量。宁可晚报，不要误报——僵死只做展示，不自动改状态。
STALL_SECONDS = 180

TRIGGERS = ("ai", "manual")

# 一轮的**性质**，和状态正交（状态是跑没跑完，类型是这轮为什么跑）。
# 起因：列表里"回归轮"和"脚本自检/网络诊断"混在一起，看的人分不清哪轮结论能用。
RUN_KINDS = ("regression", "selfcheck", "diagnostic")
KIND_DEFAULT = "regression"

SCOPE_KEYS = ("case_ids", "batch", "module", "group")

SCOPES_DOC = (
    '{"batch":"接口回归-会员侧"} | {"module":["侧边栏-素材"]} | '
    '{"group":"侧边栏"} | {"case_ids":[12,13]}'
)


def normalize_kind(raw):
    """校验 run 类型，返回 (kind, err)。缺省 regression——多数轮次是正经回归。"""
    kind = (str(raw or "")).strip().lower() or KIND_DEFAULT
    if kind not in RUN_KINDS:
        return None, f"kind 只能是 {' / '.join(RUN_KINDS)}（缺省 {KIND_DEFAULT}）"
    return kind, None


def normalize_scope(raw):
    """校验 scope，返回 (规范化 dict, err)。必须恰好给一个键。"""
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None, "scope 必填"
        try:
            raw = json.loads(raw)
        except ValueError:
            return None, "scope 不是合法 JSON"
    if not isinstance(raw, dict):
        return None, f"scope 应为对象，例如 {SCOPES_DOC}"
    keys = [k for k in SCOPE_KEYS if k in raw and raw[k] not in (None, "", [])]
    if not keys:
        return None, f"scope 至少要给一个键：{SCOPES_DOC}"
    if len(keys) > 1:
        return None, f"scope 一次只接受一个键，收到 {keys}（要组合请拆成多次 run）"
    key = keys[0]
    val = raw[key]
    if key == "case_ids":
        if not isinstance(val, list) or not val:
            return None, "case_ids 必须是非空数组"
        out = []
        for v in val:
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                return None, f"case_ids 里有非数字: {v!r}"
        if len(set(out)) != len(out):
            return None, "case_ids 有重复"
        return {"case_ids": out}, None
    if key == "batch":
        s = str(val).strip()
        if not s:
            return None, "batch 不能为空"
        return {"batch": s}, None
    if key == "group":
        s = str(val).strip()
        if not s:
            return None, "group 不能为空"
        return {"group": s}, None
    # module：字符串或数组
    mods = val if isinstance(val, list) else [val]
    mods = [str(m).strip() for m in mods if str(m).strip()]
    if not mods:
        return None, "module 不能为空"
    return {"module": mods}, None


def scope_where(scope):
    """把 scope 变成 cases 表的 WHERE 片段与参数。"""
    if "case_ids" in scope:
        ids = scope["case_ids"]
        return f"id IN ({','.join('?' * len(ids))})", list(ids)
    if "batch" in scope:
        return "batch = ?", [scope["batch"]]
    if "group" in scope:
        g = scope["group"]
        return "(module = ? OR module LIKE ?)", [g, g + "-%"]
    mods = scope["module"]
    return f"module IN ({','.join('?' * len(mods))})", list(mods)


def describe_scope(scope):
    """人读的 scope 摘要，写进 run 的 name 缺省值。"""
    if "case_ids" in scope:
        return f"用例 {len(scope['case_ids'])} 条"
    if "batch" in scope:
        return f"批次 {scope['batch']}"
    if "group" in scope:
        return f"分组 {scope['group']}"
    return "模块 " + "、".join(scope["module"])


def can_transition(cur, nxt):
    """只允许 queued→running、running→done/failed、queued→failed（取消）。"""
    return (cur, nxt) in {
        ("queued", "running"),
        ("running", "done"),
        ("running", "failed"),
        ("queued", "failed"),
    }


def summarize(total, results):
    """results 为 executions.result 的列表；skipped = 范围内没跑到的。"""
    counts = {"pass": 0, "fail": 0, "blocked": 0}
    for r in results:
        if r in counts:
            counts[r] += 1
    executed = sum(counts.values())
    return {
        "total": int(total),
        "pass": counts["pass"],
        "fail": counts["fail"],
        "blocked": counts["blocked"],
        "skipped": max(int(total) - executed, 0),
    }


def case_runnability(struct):
    """判断一条用例能不能交给 runner 跑，返回 (能否, 原因)。

    没有 checks 的用例一律跳过——不拿自然语言 expect 猜判定，
    这是 §6.3 定的语义：宁可 skipped，也不要假 pass。

    P2 起 api / ui / mixed 都能跑：api 走 requests，ui 走 Playwright，
    判定都落到同一份 core/asserts.py。每步必须二选一（要么 request 要么 ui）。
    """
    if not struct:
        return False, "没有 steps_json"
    kind = (struct.get("kind") or "mixed").lower()
    if kind not in ("api", "ui", "mixed"):
        return False, f"未知的用例类型: {kind}"
    steps = struct.get("steps") or []
    if not steps:
        return False, "steps 为空"
    for s in steps:
        no = s.get("no")
        has_req = isinstance(s.get("request"), dict)
        has_ui = isinstance(s.get("ui"), dict)
        if not has_req and not has_ui:
            return False, f"第 {no} 步既没 request 也没 ui"
        if not s.get("checks"):
            return False, f"第 {no} 步没有 checks"
    return True, ""


def classify_cases(cases):
    """把候选用例分成可执行 / 跳过两类，跳过必须带原因。

    平台和网页端共用这一份判定：跳过原因写在 run 详情里，不能一边一套说法。
    """
    runnable, skipped = [], []
    for c in cases:
        struct = parse_steps(c.get("steps_json"))
        ok, why = case_runnability(struct)
        if ok:
            runnable.append(c)
        else:
            skipped.append({"id": c["id"], "title": c["title"], "reason": why})
    return runnable, skipped


def progress_of(total, results):
    """实时进度：不等 finish 也要能回答"跑到第几条、红了几条"。

    finish 时写的 summary 是终值；run 还在跑时 summary 里的 pass/fail 恒为 0
    （创建时只写了 total），所以列表和详情必须按 executions 现算——否则跑到
    一半的 run 看起来像"一条都没跑"。
    """
    counts = {"pass": 0, "fail": 0, "blocked": 0}
    for r in results:
        if r in counts:
            counts[r] += 1
    done = sum(counts.values())
    total = int(total or 0)
    return {"total": total, "done": done,
            "pass": counts["pass"], "fail": counts["fail"],
            "blocked": counts["blocked"], "left": max(total - done, 0)}


def run_progress(run, results):
    """一轮的进度：终态读 summary，运行中按 executions 现算。

    终态的 summary 是那一轮的事实（finish/cancel 时从 executions 汇总写入），
    拿它当准，避免执行记录被清掉后"完成的一轮显示 0/0"。
    """
    summary = run.get("summary") or {}
    total = int(summary.get("total") or 0)
    if run.get("status") in ("done", "failed") and any(
            k in summary for k in ("pass", "fail", "blocked")):
        done = sum(int(summary.get(k) or 0) for k in ("pass", "fail", "blocked"))
        return {"total": total, "done": done,
                "pass": int(summary.get("pass") or 0),
                "fail": int(summary.get("fail") or 0),
                "blocked": int(summary.get("blocked") or 0),
                "left": max(total - done, 0)}
    return progress_of(total, results)


def _parse_ts(raw):
    raw = (raw or "").strip()[:19]
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def heartbeat_at(row):
    """最后一次"有生命迹象"的时间：心跳优先，退回 started_at / created_at。"""
    return (row.get("last_heartbeat_at") or row.get("started_at")
            or row.get("created_at") or "")


def is_stalled(row, now_str, threshold=STALL_SECONDS):
    """running 且超过 threshold 秒没有任何心跳 → 僵死。

    只读判定：不改状态、不自动收尾。自动收尾会把"runner 为什么死的"一起埋掉，
    见 docs/执行任务管理与观测边界.md。
    """
    if (row.get("status") or "") != "running":
        return False
    seen, cur = _parse_ts(heartbeat_at(row)), _parse_ts(now_str)
    if not seen or not cur:
        return False
    return (cur - seen).total_seconds() > threshold


def stall_cutoff(now_str, threshold=STALL_SECONDS):
    """僵死判定的时间界（给 SQL 用），与 is_stalled 同一口径。"""
    cur = _parse_ts(now_str)
    if not cur:
        return ""
    return (cur - timedelta(seconds=threshold)).strftime("%Y-%m-%d %H:%M:%S")


def cancelled_summary(total, results, note):
    """取消/收尾时的 summary：按已回填的执行现算，并把原因带出去。

    中途收掉的 run 不能留 pass/fail=0——那会让"跑了 8 条挂了 6 条"变成"没跑"。
    """
    summary = summarize(total, results)
    summary["note"] = (note or "人工取消").strip()[:500]
    return summary


def regression_diff(baseline, current, scope_ids=None):
    """两轮执行结果的对比（2026-10-26 落地 baseline_run_id）。

    baseline / current 都是 {case_id: result}；scope_ids 是本轮的范围内用例
    （给了才能把"没跑到"和"不在范围"分开，不把没复跑的红说成已修复）。

    回归测试最常问的四个问题一次答完：比上轮多了哪些红、修好了哪些、
    一直红着哪些、新跑绿了哪些。
    """
    out = {"new_fail": [], "still_fail": [], "fixed": [], "new_pass": [],
           "not_rerun": []}
    for cid, res in current.items():
        prev = baseline.get(cid)
        if res == "fail":
            out["still_fail" if prev == "fail" else "new_fail"].append(cid)
        elif res == "pass" and prev != "pass":
            out["fixed" if prev == "fail" else "new_pass"].append(cid)
    if scope_ids:
        for cid, prev in baseline.items():
            if prev == "fail" and cid in scope_ids and cid not in current:
                out["not_rerun"].append(cid)
    return out
