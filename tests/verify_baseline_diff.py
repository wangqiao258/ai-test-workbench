"""验证 run 详情页的基准轮对比卡片（修复项 11）在副本库上渲染。"""
import json
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_diffcard.db")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)

import db  # noqa: E402
db.DB_PATH = TEST_DB
db.init_db()
import app as platform  # noqa: E402
from werkzeug.security import check_password_hash, generate_password_hash  # noqa: E402

conn = db.get_db()
fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not cond:
        fails.append(name)


# 造基准轮与当前轮：同一 case，基准 fail → 当前 pass（应进"已修复"）
cid = conn.execute("SELECT id FROM cases WHERE project_id=1 LIMIT 1").fetchone()[0]
conn.execute(
    "INSERT INTO runs (project_id, name, scope, kind, status, summary, started_at, "
    "finished_at, created_at) VALUES (1,'基准轮',?,'regression','done',?,'2026-10-25 10:00:00',"
    "'2026-10-25 10:30:00','2026-10-25 09:00:00')",
    (json.dumps({"case_ids": [cid]}), json.dumps(
        {"total": 1, "pass": 0, "fail": 1, "blocked": 0, "skipped": 0})))
base = conn.execute("SELECT MAX(id) FROM runs").fetchone()[0]
conn.execute("INSERT INTO executions (case_id, result, run_id, created_at) VALUES (?, 'fail', ?, '2026-10-25 10:05:00')", (cid, base))
conn.execute(
    "INSERT INTO runs (project_id, name, scope, kind, status, baseline_run_id, summary, "
    "started_at, finished_at, created_at) VALUES (1,'当前轮',?,'regression','done',?,?,'2026-10-26 10:00:00',"
    "'2026-10-26 10:30:00','2026-10-26 09:00:00')",
    (json.dumps({"case_ids": [cid]}), base,
     json.dumps({"total": 1, "pass": 1, "fail": 0, "blocked": 0, "skipped": 0})))
cur = conn.execute("SELECT MAX(id) FROM runs").fetchone()[0]
conn.execute("INSERT INTO executions (case_id, result, run_id, created_at) VALUES (?, 'pass', ?, '2026-10-26 10:05:00')", (cid, cur))
conn.commit()
conn.close()

# API 层：diff 结构
client = platform.app.test_client()
TOKEN = open(os.path.join(BASE, "data", "api-token.txt"), encoding="utf-8").read().strip()
H = {"X-API-Token": TOKEN}
r = client.get(f"/api/runs/{cur}", headers=H)
body = r.get_json()
check("详情返回 baseline 信息", body.get("baseline", {}).get("id") == base)
check("diff 把 fail→pass 归入 fixed", body.get("diff", {}).get("fixed") == [cid],
      str(body.get("diff")))
check("diff_cases 带标题", str(cid) in body.get("diff_cases", {}))

# 网页层：详情页渲染对比卡片
admin_pw = None
import sqlite3  # noqa: E402
raw = sqlite3.connect(TEST_DB)
admin_pw = raw.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
raw.close()
if not check_password_hash(admin_pw, "admin123"):
    conn = db.get_db()
    conn.execute("UPDATE users SET password_hash=? WHERE username='admin'",
                 (generate_password_hash("admin123"),))
    conn.commit()
    conn.close()
client.post("/login", data={"username": "admin", "password": "admin123"})
html = client.get(f"/runs/{cur}").get_data(as_text=True)
check("详情页出现基准轮卡片", "与基准轮" in html and "已修复" in html)
check("卡片列出用例标题", "已修复" in html and "1" in html)

os.remove(TEST_DB)
print()
if fails:
    print(f"失败 {len(fails)} 项")
    sys.exit(1)
print("全部通过")
