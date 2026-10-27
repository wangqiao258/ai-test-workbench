"""一次性回填 runs.kind（幂等，重复跑不改变结果）。

起因（2026-10-23）：列表里"回归轮"和"脚本自检 / 网络诊断"混在一起，看的人分不清
哪一轮结论能用。新建立的 run 由发起方显式给 kind；存量 16 条按**当时的目的**回填，
判据取 name/reason，不看结果——run 15 跑了 21 条但目的是验服务器执行，仍算诊断。

分类规则（前缀匹配，未命中一律 regression）：
- selfcheck   自检：回填验证、脚本自检、观测自检
- diagnostic  诊断：服务器执行系列、诊断用
- regression  回归：其余（全量基线、家长端/员工端回归、参照、补接口、config 校验）

用法：
    python scripts/backfill_run_kind.py            # 预览
    python scripts/backfill_run_kind.py --apply    # 落库

容器内（镜像已带 scripts/）：
    docker compose -f deploy/docker-compose.yml exec -T platform \
        python scripts/backfill_run_kind.py --apply
"""

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.exists(os.path.join(BASE, "db.py")):
    BASE = os.getcwd()
sys.path.insert(0, BASE)
os.chdir(BASE)

import db  # noqa: E402

RULES = (
    ("回填验证-", "selfcheck"),
    ("脚本自检", "selfcheck"),
    ("观测自检", "selfcheck"),
    ("服务器执行-", "diagnostic"),
    ("诊断用", "diagnostic"),
)
DEFAULT = "regression"


def classify(name, reason=""):
    text = f"{name or ''}{reason or ''}"
    for prefix, kind in RULES:
        if prefix in text:
            return kind
    return DEFAULT


def main(apply=False):
    db.init_db()           # 幂等迁移：老库补 kind 列（默认 regression）
    conn = db.get_db()
    rows = conn.execute(
        "SELECT id, name, reason, kind FROM runs ORDER BY id").fetchall()
    changed, stats = [], {}
    for r in rows:
        want = classify(r["name"], r["reason"])
        stats[want] = stats.get(want, 0) + 1
        if r["kind"] != want:
            changed.append((r["id"], r["name"], r["kind"], want))
    for rid, name, old, new in changed:
        print(f"  run {rid:>3} {old or '(空)':<11} → {new:<11} {name}")
        if apply:
            conn.execute("UPDATE runs SET kind=? WHERE id=?", (new, rid))
    if apply:
        conn.commit()
    conn.close()
    print("\n统计：" + "　".join(f"{k} {v}" for k, v in sorted(stats.items())))
    print(f"{'已回填' if apply else '待回填'} {len(changed)} 条 / 共 {len(rows)} 条")
    if not apply and changed:
        print("加 --apply 落库")
    return 0


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
