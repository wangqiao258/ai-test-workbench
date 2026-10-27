"""合成数据验证 backfill_run_scope 的归属逻辑（进程内调用，库用副本，不碰真实数据）。

注意：不能用子进程跑 backfill_run_scope.py——脚本自己 os.chdir + db.init_db，
子进程里的 DB_PATH 是默认的真实库。进程内 import 后改 db.DB_PATH 才是副本。
"""
import importlib
import io
import json
import os
import shutil
import sys
from contextlib import redirect_stdout

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_scope.db")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)

import db  # noqa: E402
db.DB_PATH = TEST_DB
db.init_db()
sys.path.insert(0, os.path.join(BASE, "scripts"))
import backfill_run_scope as bfs  # noqa: E402  导入即 chdir(BASE)，写库走副本

conn = db.get_db()

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not cond:
        fails.append(name)


def run(apply):
    buf = io.StringIO()
    with redirect_stdout(buf):
        bfs.main(apply=apply)
    return buf.getvalue()


# 构造：run A 覆盖 10:00-10:30，run B 覆盖 11:00-11:30，queued 轮无 started_at
conn.execute("INSERT INTO runs (project_id, name, scope, status, started_at, finished_at, created_at) "
             "VALUES (1, '轮A', ?, 'done', '2026-10-20 10:00:00', '2026-10-20 10:30:00', '2026-10-20 09:00:00')",
             (json.dumps({"case_ids": [100, 101]}),))
run_a = conn.execute("SELECT MAX(id) FROM runs").fetchone()[0]
conn.execute("INSERT INTO runs (project_id, name, scope, status, started_at, finished_at, created_at) "
             "VALUES (1, '轮B', ?, 'done', '2026-10-20 11:00:00', '2026-10-20 11:30:00', '2026-10-20 10:45:00')",
             (json.dumps({"case_ids": [100, 101]}),))
run_b = conn.execute("SELECT MAX(id) FROM runs").fetchone()[0]
conn.execute("INSERT INTO runs (project_id, name, scope, status, created_at) "
             "VALUES (1, '轮Q', ?, 'queued', '2026-10-20 09:00:00')",
             (json.dumps({"case_ids": [100]}),))
# 三条孤儿执行：落在 A 窗内 / 落在 B 窗内 / 两轮之间（归不了）
for cid, ts in ((100, "2026-10-20 10:15:00"), (101, "2026-10-20 11:10:00"),
                (100, "2026-10-20 10:45:00")):
    conn.execute("INSERT INTO executions (case_id, result, created_at) VALUES (?, 'pass', ?)",
                 (cid, ts))
conn.commit()

base_orphans = conn.execute(
    "SELECT COUNT(*) c FROM executions WHERE run_id IS NULL OR run_id=''").fetchone()["c"]

# 预览：不应写库
preview = run(False)
still = conn.execute(
    "SELECT COUNT(*) c FROM executions WHERE run_id IS NULL OR run_id=''").fetchone()["c"]
check("预览模式不写库", still == base_orphans, f"孤儿 {still}")
check("预览报告点名轮A/轮B", "轮A" in preview and "轮B" in preview)

# 落库
run(True)
a_hits = conn.execute("SELECT COUNT(*) c FROM executions WHERE run_id=?", (run_a,)).fetchone()["c"]
b_hits = conn.execute("SELECT COUNT(*) c FROM executions WHERE run_id=?", (run_b,)).fetchone()["c"]
gap = conn.execute(
    "SELECT COUNT(*) c FROM executions WHERE (run_id IS NULL OR run_id='') "
    "AND created_at='2026-10-20 10:45:00'").fetchone()["c"]
check("A 窗内的执行归到轮A", a_hits == 1, f"run {run_a}: {a_hits}")
check("B 窗内的执行归到轮B", b_hits == 1, f"run {run_b}: {b_hits}")
check("两轮之间的归不了（不硬塞）", gap == 1)

# 幂等：再跑一次 --apply 不改变归属
run(True)
a2 = conn.execute("SELECT COUNT(*) c FROM executions WHERE run_id=?", (run_a,)).fetchone()["c"]
b2 = conn.execute("SELECT COUNT(*) c FROM executions WHERE run_id=?", (run_b,)).fetchone()["c"]
check("重复跑不改变结果（幂等）", a2 == 1 and b2 == 1)

conn.close()
os.remove(TEST_DB)
print()
if fails:
    print(f"失败 {len(fails)} 项")
    sys.exit(1)
print("全部通过")
