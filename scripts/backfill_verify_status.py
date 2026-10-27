"""一次性回填 interfaces.verify_status（幂等，重复跑不改变结果）。

起因（2026-10-26 独立评审）：线上 161/161 接口全是 verified，但真有完整数据包的
只有 3 条——`POST /api/interfaces` 的显式 verify_status 参数允许"补录历史数据"时
自封 verified，结果质量轴 100% 绿、证据覆盖 1.9%，verified 失去分辨力。

规则（只有一条）：
- verified 且没有 completeness=full 的数据包 → unverified（从未有过可复核的实测）
- verified 且有 full 数据包              → 保持
- changed / unverified                   → 不动

配套的代码侧修复（api/interfaces.py）：POST/PUT 不再接受自封 verified，
verified 只能由随接口提交的完整数据包产生。本脚本只治理存量。

用法：
    python scripts/backfill_verify_status.py            # 预览（默认）
    python scripts/backfill_verify_status.py --apply    # 落库

容器内（镜像已带 scripts/）：
    docker compose -f deploy/docker-compose.yml exec -T platform \
        python scripts/backfill_verify_status.py --apply
"""

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.exists(os.path.join(BASE, "db.py")):
    BASE = os.getcwd()
sys.path.insert(0, BASE)
os.chdir(BASE)

import db  # noqa: E402


def has_full_packet(conn, itf_id):
    return conn.execute(
        "SELECT 1 FROM packets WHERE linked_type='interface' AND linked_id=? "
        "AND completeness='full' LIMIT 1", (itf_id,)).fetchone() is not None


def main(apply=False):
    db.init_db()           # 幂等迁移：老库确保列存在
    conn = db.get_db()
    rows = conn.execute(
        "SELECT id, name, path, verify_status FROM interfaces ORDER BY id").fetchall()
    changed, stats = [], {}
    for r in rows:
        cur = r["verify_status"] or "unverified"
        stats[cur] = stats.get(cur, 0) + 1
        if cur == "verified" and not has_full_packet(conn, r["id"]):
            changed.append((r["id"], r["name"], r["path"]))
    for iid, name, path in changed:
        print(f"  interface {iid:>4} verified → unverified　{name}（{path}）")
        if apply:
            conn.execute("UPDATE interfaces SET verify_status='unverified', "
                         "updated_at=? WHERE id=?", (db.now(), iid))
    if apply:
        conn.commit()
    conn.close()
    print("\n当前分布：" + "　".join(f"{k} {v}" for k, v in sorted(stats.items())))
    print(f"{'已回填' if apply else '待回填'} {len(changed)} 条 / 共 {len(rows)} 条接口")
    if not apply and changed:
        print("加 --apply 落库")
    return 0


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
