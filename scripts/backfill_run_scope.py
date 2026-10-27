"""一次性回填 executions.run_id（孤儿执行治理，幂等，重复跑不改变结果）。

起因（2026-10-26 独立评审）：本地快照 159 条 executions 里 157 条 run_id 为空，
线上比例相仿——"这一轮跑了什么"在历史数据上答不了，趋势图也无从画起。

归属规则（三条同时满足才认）：
1. 范围：run 的 scope 覆盖该 execution 的 case（同项目）；
2. 时间：run.started_at ≤ execution.created_at ≤ run.finished_at
   （finished_at 为空 = 这轮还没收尾；queued 没 started_at，从未跑过，不算候选）；
3. 多轮都满足时取 started_at 最晚的那轮（最近启动的最可能是生产者）。

归不了的（没有时间覆盖的 run、或 case 已删）**不硬塞**：保持 run_id 为空，
在看板"孤儿执行"里继续计数，报告里逐条列出来。宁可答"不知道"，
不能编一个轮次——那会让"哪一轮"这个问题彻底失去可信度。

配套：dashboard 数据质量看板的"孤儿执行"徽标读同一口径
（core/lists.quality_stats），治理后这里应该归零。

用法：
    python scripts/backfill_run_scope.py            # 预览（默认，不写库）
    python scripts/backfill_run_scope.py --apply    # 落库

容器内（镜像已带 scripts/）：
    docker compose -f deploy/docker-compose.yml exec -T platform \
        python scripts/backfill_run_scope.py --apply
"""

import json
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.exists(os.path.join(BASE, "db.py")):
    BASE = os.getcwd()
sys.path.insert(0, BASE)
os.chdir(BASE)

import db  # noqa: E402
from core.lists import scoped_cases  # noqa: E402


def _covers(run, ts):
    """这轮的时间窗是否覆盖执行时刻。queued（没 started_at）永远不覆盖。"""
    started = (run["started_at"] or "").strip()
    if not started or not ts:
        return False
    if ts < started:
        return False
    finished = (run["finished_at"] or "").strip()
    return not finished or ts <= finished


def _load_runs(conn):
    """所有真正跑过的轮次 + 各自 scope 覆盖的 case 集合（按项目分）。"""
    runs = []
    for r in conn.execute(
            "SELECT id, project_id, name, kind, status, scope, started_at, finished_at "
            "FROM runs ORDER BY id").fetchall():
        try:
            scope = json.loads(r["scope"] or "{}")
        except ValueError:
            continue
        if not scope:
            continue
        try:
            cases = scoped_cases(conn, r["project_id"], scope)
        except Exception:
            continue
        runs.append({"row": r, "cases": {c["id"] for c in cases}})
    return runs


def main(apply=False):
    db.init_db()           # 幂等迁移：老库确保列存在
    conn = db.get_db()
    runs = _load_runs(conn)
    orphans = conn.execute(
        "SELECT e.id, e.case_id, e.result, e.created_at FROM executions e "
        "WHERE e.run_id IS NULL OR e.run_id='' ORDER BY e.id").fetchall()
    # 顺带查一类脏数据：run_id 有值但指向别的项目的 run（跨项目串轮）
    cross = conn.execute(
        "SELECT e.id, e.case_id, e.run_id FROM executions e "
        "JOIN cases c ON c.id = e.case_id JOIN runs r ON r.id = e.run_id "
        "WHERE r.project_id != c.project_id ORDER BY e.id").fetchall()

    hit = defaultdict(list)          # run_id -> [execution id]
    no_run, no_case = [], []
    for e in orphans:
        case = conn.execute("SELECT id, project_id FROM cases WHERE id=?",
                            (e["case_id"],)).fetchone()
        if not case:
            no_case.append(e)
            continue
        cands = [r for r in runs
                 if r["row"]["project_id"] == case["project_id"]
                 and e["case_id"] in r["cases"] and _covers(r["row"], e["created_at"])]
        if not cands:
            no_run.append(e)
            continue
        best = max(cands, key=lambda r: r["row"]["started_at"])   # 最晚启动
        hit[best["row"]["id"]].append(e["id"])
        if apply:
            conn.execute("UPDATE executions SET run_id=? WHERE id=?",
                         (best["row"]["id"], e["id"]))
    if apply:
        conn.commit()
    conn.close()

    print(f"孤儿执行（run_id 为空）：{len(orphans)} 条")
    print(f"时间上可归属的轮次数：{len(runs)}（queued 无 started_at，不算候选）")
    for rid in sorted(hit):
        r = next(x["row"] for x in runs if x["row"]["id"] == rid)
        print(f"  → run {rid}「{r['name']}」（{r['kind']}/{r['status']}）"
              f"归入 {len(hit[rid])} 条")
    print(f"归不了（没有时间覆盖的 run，保持为空）：{len(no_run)} 条"
          + ("".join(f"\n    execution {e['id']} case {e['case_id']} "
                     f"{e['result']} @ {e['created_at']}" for e in no_run[:20])
             + (f"\n    ……还有 {len(no_run) - 20} 条" if len(no_run) > 20 else "")))
    if no_case:
        print(f"用例已删（无从匹配 scope，保持为空）：{len(no_case)} 条"
              + "".join(f"\n    execution {e['id']} → case {e['case_id']}"
                        for e in no_case[:10]))
    if cross:
        print(f"跨项目串轮（run 与 case 不同项目，需人工核对）：{len(cross)} 条"
              + "".join(f"\n    execution {c['id']} case {c['case_id']} → run {c['run_id']}"
                        for c in cross[:10]))
    total_hit = sum(len(v) for v in hit.values())
    print(f"\n{'已回填' if apply else '待回填'} {total_hit} 条 / 孤儿 {len(orphans)} 条；"
          f"仍有 {len(no_run) + len(no_case)} 条归不了（看板'孤儿执行'继续显示）")
    if not apply and total_hit:
        print("加 --apply 落库")
    return 0


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
