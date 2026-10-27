"""验证项目页「设置」tab 渲染出运行通知卡片（回答"设置页面没看到"）。"""
import os
import shutil
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_settings_render.db")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)

import db  # noqa: E402
db.DB_PATH = TEST_DB
import app as platform  # noqa: E402
from werkzeug.security import check_password_hash, generate_password_hash  # noqa: E402

raw = sqlite3.connect(TEST_DB)
pw = raw.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
raw.close()
if not check_password_hash(pw, "admin123"):
    conn = db.get_db()
    conn.execute("UPDATE users SET password_hash=? WHERE username='admin'",
                 (generate_password_hash("admin123"),))
    conn.commit()
    conn.close()

client = platform.app.test_client()
client.post("/login", data={"username": "admin", "password": "admin123"})

# 项目 1 的设置 tab（notify 卡片应在"账号"卡片之后）
html = client.get("/projects/1?tab=settings").get_data(as_text=True)
print("设置 tab 渲染长度:", len(html))
for probe in ("运行通知", "Webhook 地址", "发送测试", "企业微信", "/projects/1/notify"):
    print(f"  {'PASS' if probe in html else 'FAIL'}  含 {probe!r}")

# 入口标签：顶部导航不再叫"设置"（避免与项目设置 tab 混淆），项目 tab 叫"项目设置"
print("\n顶部导航含「账号」:", ">账号</a>" in html)
print("项目 tab 叫「项目设置」:", "项目设置" in html)
print("表单 action 指向 /projects/1/notify:", 'action="/projects/1/notify"' in html)

# 账号设置页（顶部导航那个）——确认它没有 notify，解释用户的疑惑
html2 = client.get("/settings").get_data(as_text=True)
print("\n账号设置页 /settings 含 '运行通知':", "运行通知" in html2,
      "（顶部导航的「账号」是这一页，所以看不到 notify）")
print("账号设置页含 '修改密码':", "修改密码" in html2)

os.remove(TEST_DB)
