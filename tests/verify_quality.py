"""验证数据质量看板（修复项 13）：在库副本上算数并渲染 dashboard。"""
import json
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_quality.db")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)

import db  # noqa: E402
db.DB_PATH = TEST_DB
import app as platform  # noqa: E402

conn = db.get_db()
q = platform.lists.quality_stats(conn, 1)
conn.close()
print(json.dumps(q, ensure_ascii=False, indent=1))

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not cond:
        fails.append(name)


check("接口总数与库内一致", q["interfaces"]["total"] == db.get_db().execute(
    "SELECT COUNT(*) c FROM interfaces WHERE project_id=1").fetchone()["c"])
check("full 口径只数完整包", q["interfaces"]["full"] <= q["interfaces"]["total"])
check("用例可执行数不超总数", q["cases"]["runnable"] <= q["cases"]["total"])
check("通过率分子不超分母", q["bugs"]["approved"] <= q["bugs"]["decided"])
check("阈值齐全（四个原有 + 覆盖率两条轴）",
      set(q["thresholds"]) == {"verify_rate", "runnable_rate", "bug_pass_rate",
                               "orphan_execs", "interface_coverage",
                               "ui_modules_coverage"})
check("接口覆盖率与接口总数同源",
      q["coverage"]["total"] == q["interfaces"]["total"]
      and q["coverage"]["covered"] <= q["coverage"]["total"],
      f'{q["coverage"]["covered"]}/{q["coverage"]["total"]}')
check("UI 覆盖率分母是有接口的模块",
      q["ui"]["total"] == db.get_db().execute(
          "SELECT COUNT(DISTINCT module) FROM interfaces "
          "WHERE project_id=1 AND module!=''").fetchone()[0],
      f'{q["ui"]["covered"]}/{q["ui"]["total"]} 个模块')

# 空项目不除零
conn = db.get_db()
conn.execute("INSERT INTO projects (name, description, created_at) VALUES ('空项目', '', '2026-10-26')")
conn.commit()
empty_pid = conn.execute("SELECT MAX(id) FROM projects").fetchone()[0]
q2 = platform.lists.quality_stats(conn, empty_pid)
conn.close()
check("空项目各项为 None/0 不崩", q2["interfaces"]["rate"] is None
      and q2["cases"]["rate"] is None and q2["bugs"]["rate"] is None
      and q2["coverage"]["rate"] is None and q2["ui"]["rate"] is None
      and q2["orphan_execs"] == 0)

# dashboard 页面能渲染（登录后）
client = platform.app.test_client()
import sqlite3  # noqa: E402
from werkzeug.security import check_password_hash, generate_password_hash  # noqa: E402
raw = sqlite3.connect(TEST_DB)
admin_pw = raw.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
raw.close()
if not check_password_hash(admin_pw, "admin123"):
    # 副本里密码被改过：直接重置成 admin123 再测渲染
    conn = db.get_db()
    conn.execute("UPDATE users SET password_hash=? WHERE username='admin'",
                 (generate_password_hash("admin123"),))
    conn.commit()
    conn.close()
r = client.post("/login", data={"username": "admin", "password": "admin123"},
                follow_redirects=True)
html = r.get_data(as_text=True)
check("dashboard 渲染 200", r.status_code == 200)
check("看板出现真实验证徽标", "真实验证" in html)
check("看板出现接口覆盖徽标", "接口覆盖" in html)
check("看板出现 UI 覆盖徽标", "UI 覆盖" in html)
check("看板出现可执行用例徽标", "可执行用例" in html)
check("看板出现孤儿执行徽标", "孤儿执行" in html)
check("徽标带颜色类（pass/fail）", 'class="badge pass"' in html or 'class="badge fail"' in html,
      "")

os.remove(TEST_DB)
print()
if fails:
    print(f"失败 {len(fails)} 项：" + "；".join(fails))
    sys.exit(1)
print("全部通过")
