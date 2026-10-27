"""账号改/删的页面级校验：在数据库副本上跑，不污染真实数据。

覆盖 2026-10-23「环境与账号」里账号可维护的改造：
1) 表格加操作列（编辑 / 删除），密码默认只见圆点、点开才明文
2) ?edit=<id> 就地展开整行表单（URL 决定编辑哪一行，零前端状态）
3) 改：按 id 原地更新、不新增行；密码留空=不改；username 必填；跨项目 pid 不动数据
4) 删：硬删，删完 API 不再返回；重复删不 500；不影响 Bug
5) 审计：update_account / delete_account，detail 只记字段名与用户名，不记密码
6) 环境保持只读（没有 /env/<id> 路由）、API 仍是只读但返回明文（AI 要登录）
7) 用户名带单引号时删除确认文案不会撑破 HTML 属性

用法（在 ai-test-platform 目录下）：
    python tests/verify_settings.py
"""
import json
import os
import re
import shutil
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

TEST_DB = os.path.join(BASE, "data", "_verify_settings.db")
shutil.copy(os.path.join(BASE, "data", "app.db"), TEST_DB)
for extra in ("-wal", "-shm"):
    p = TEST_DB + extra
    if os.path.exists(p):
        os.remove(p)

import db  # noqa: E402
db.DB_PATH = TEST_DB
import app as platform  # noqa: E402

client = platform.app.test_client()
with client.session_transaction() as sess:
    sess["user"] = "admin"

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail else ''}")
    if not cond:
        fails.append(name)


def get(url):
    return client.get(url).get_data(as_text=True)


def sql(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(query, args).fetchall()
    finally:
        conn.close()


def scalar(query, args=()):
    conn = sqlite3.connect(TEST_DB)
    try:
        return conn.execute(query, args).fetchone()[0]
    finally:
        conn.close()


def post(url, data=None):
    return client.post(url, data=data or {}, follow_redirects=True)


def add_account(**kw):
    payload = {"env_id": "1", "label": "verify", "username": "verify_user",
               "password": "P@ss-1234", "role": "tester", "notes": "临时账号"}
    payload.update(kw)
    r = post("/projects/1/account", payload)
    aid = scalar("SELECT MAX(id) FROM accounts")
    return aid, r.get_data(as_text=True)


PID = 1
BEFORE_BUGS = scalar("SELECT COUNT(*) FROM bugs")

print("== 1. 表格：操作列 + 密码遮蔽 ==")
aid, _ = add_account()
html = get(f"/projects/{PID}?tab=settings")
check("表头有操作列", "<th>操作</th>" in html)
check("每行有编辑入口", f"?tab=settings&amp;edit={aid}" in html, aid)
check("每行有删除入口", f"/projects/{PID}/account/{aid}/delete" in html)
check("密码默认显示圆点", '<summary title="点击显示明文">••••••</summary>' in html)
check("明文收在 <details> 里（折叠，不是移除）", f"<code>P@ss-1234</code>" in html)
check("明文不在单元格里裸奔", html.count(">P@ss-1234<") == 1, html.count(">P@ss-1234<"))
check("环境为空时显示（未指定）而不是 None",
      "None" not in re.findall(r"<td>([^<]*)</td>", html))

print("\n== 2. ?edit=<id> 就地展开 ==")
edit_html = get(f"/projects/{PID}?tab=settings&edit={aid}")
check("出现编辑行", 'class="acct-edit-row"' in edit_html)
check("表单指向 update 路由", f'action="/projects/{PID}/account/{aid}"' in edit_html)
check("预填标签", 'name="label" value="verify"' in edit_html)
check("预填用户名", 'name="username" value="verify_user"' in edit_html)
check("预填角色", 'name="role" value="tester"' in edit_html)
check("预填备注", 'name="notes" value="临时账号"' in edit_html)
check("密码框留空（不把明文回填进表单）",
      'name="password" placeholder="留空表示不修改"' in edit_html)
check("环境下拉含“（不指定环境）”", "（不指定环境）" in edit_html)
check("只有被选中的那一行展开", edit_html.count('class="acct-edit-row"') == 1)

bad = get(f"/projects/{PID}?tab=settings&edit=999999")
check("?edit= 指向不存在的 id 不报错、不展开",
      'class="acct-edit-row"' not in bad)

print("\n== 3. 改 ==")
rows_before = scalar("SELECT COUNT(*) FROM accounts")
r = post(f"/projects/{PID}/account/{aid}",
         {"env_id": "1", "label": "生产", "username": "verify_user",
          "password": "", "role": "admin", "notes": "改过"})
row = sql("SELECT * FROM accounts WHERE id=?", (aid,))[0]
check("标签已改", row["label"] == "生产", row["label"])
check("角色已改", row["role"] == "admin", row["role"])
check("备注已改", row["notes"] == "改过", row["notes"])
check("密码留空时不被清空", row["password"] == "P@ss-1234", row["password"])
check("不新增行", scalar("SELECT COUNT(*) FROM accounts") == rows_before)

post(f"/projects/{PID}/account/{aid}",
     {"env_id": "1", "label": "生产", "username": "verify_user",
      "password": "NewP@ss-9", "role": "admin", "notes": "改过"})
check("填了密码才改密码",
      scalar("SELECT password FROM accounts WHERE id=?", (aid,)) == "NewP@ss-9")

r = post(f"/projects/{PID}/account/{aid}",
         {"env_id": "1", "label": "生产", "username": "  ",
          "password": "", "role": "admin", "notes": "改过"})
check("username 为空被拒", "用户名不能为空" in r.get_data(as_text=True))
check("被拒时数据原样", scalar("SELECT username FROM accounts WHERE id=?", (aid,)) == "verify_user")

r = post(f"/projects/999/account/{aid}",
         {"env_id": "1", "label": "被越权改掉", "username": "hacked",
          "password": "", "role": "", "notes": ""})
check("别的项目 pid 改不动它", scalar("SELECT label FROM accounts WHERE id=?", (aid,)) == "生产")
check("越权时给出提示", "不属于该项目" in r.get_data(as_text=True))
check("越权后落在账号自己的项目页",
      r.request.path == f"/projects/{PID}" and "tab=settings" in r.request.query_string.decode(),
      r.request.path)

r = post(f"/projects/{PID}/account/{aid}",
         {"env_id": "1", "label": "生产", "username": "verify_user",
          "password": "", "role": "admin", "notes": "改过"})
check("无改动时提示没有改动", "没有改动" in r.get_data(as_text=True))

print("\n== 4. 删 ==")
r = post(f"/projects/{PID}/account/{aid}/delete")
check("记录已删除", scalar("SELECT COUNT(*) FROM accounts WHERE id=?", (aid,)) == 0)
check("提示带用户名", "verify_user" in r.get_data(as_text=True))
r = post(f"/projects/{PID}/account/{aid}/delete")
check("重复删除不 500", r.status_code == 200, r.status_code)
check("重复删除给出提示", "不存在" in r.get_data(as_text=True))

print("\n== 5. 删除后 API 不再返回 / API 仍给明文 ==")
aid2, _ = add_account(label="api-check", username="api_user", password="ApiP@ss-1")
tok = scalar("SELECT token FROM tokens WHERE revoked=0 LIMIT 1")
resp = client.get(f"/api/projects/{PID}/accounts", headers={"X-API-Token": tok})
data = json.loads(resp.get_data(as_text=True))
by_id = {a["id"]: a for a in data}
check("API 能读到新账号", aid2 in by_id, list(by_id))
check("API 返回明文密码（AI 要拿它登录）",
      by_id.get(aid2, {}).get("password") == "ApiP@ss-1")
post(f"/projects/{PID}/account/{aid2}/delete")
data2 = json.loads(client.get(f"/api/projects/{PID}/accounts",
                              headers={"X-API-Token": tok}).get_data(as_text=True))
check("删除后 API 不再返回", aid2 not in {a["id"] for a in data2})

print("\n== 6. 审计 ==")
upd = sql("SELECT detail FROM audit WHERE action='update_account' ORDER BY id DESC")
dels = sql("SELECT detail FROM audit WHERE action='delete_account' ORDER BY id DESC")
check("记录了 update_account", len(upd) >= 1, len(upd))
check("detail 是“用户名: 改动字段名”",
      any("verify_user: " in u["detail"] and "label" in u["detail"] for u in upd),
      upd[0]["detail"] if upd else None)
check("update detail 不含密码值",
      not any("P@ss" in (u["detail"] or "") for u in upd))
check("记录了 delete_account", len(dels) >= 2, len(dels))
check("delete detail 含用户名不含密码",
      any("verify_user" in d["detail"] for d in dels)
      and not any("P@ss" in (d["detail"] or "") for d in dels))

print("\n== 7. 回归：新增与只读边界 ==")
r = post("/projects/1/account", {"env_id": "1", "label": "空名", "username": ""})
check("新增时 username 也为必填", "用户名不能为空" in r.get_data(as_text=True))
check("空名账号没有落库", scalar("SELECT COUNT(*) FROM accounts WHERE label='空名'") == 0)
r = post("/projects/1/account", {"env_id": "999999", "label": "野环境",
                                 "username": "wild_env"})
check("伪造 env_id 被拒（不撞外键 500）",
      "环境不存在或不属于该项目" in r.get_data(as_text=True) and r.status_code == 200)
check("野环境账号没有落库", scalar("SELECT COUNT(*) FROM accounts WHERE label='野环境'") == 0)
check("环境仍只读（没有 /env/<id> 路由）",
      client.post(f"/projects/{PID}/env/1", data={}).status_code in (404, 405),
      client.post(f"/projects/{PID}/env/1", data={}).status_code)
check("删账号不影响 Bug", scalar("SELECT COUNT(*) FROM bugs") == BEFORE_BUGS)

print("\n== 8. 确认文案的转义 ==")
aid3, _ = add_account(label="quote", username="o'brien", password="Q'1")
qh = get(f"/projects/{PID}?tab=settings")
check("含引号的用户名被转成 \\u0027，不会撑破 onsubmit 属性",
      "\\u0027" in qh and "o'brien" not in re.search(r"onsubmit='[^']*'", qh).group(0))
post(f"/projects/{PID}/account/{aid3}/delete")

print("\n== 9. 修改密码：二次核对、规则与 PRG（2026-10-23）==")
from werkzeug.security import check_password_hash as chk, generate_password_hash as gen


def set_admin_pwd(plain):
    conn = sqlite3.connect(TEST_DB)
    conn.execute("UPDATE users SET password_hash=? WHERE username='admin'", (gen(plain),))
    conn.commit()
    conn.close()


def admin_pwd_is(plain):
    return chk(scalar("SELECT password_hash FROM users WHERE username='admin'"), plain)


def change(old, new, confirm=None):
    """confirm 传 None 表示两次输同一个；传 "" 表示前端只发了一个框。"""
    data = {"old_password": old, "new_password": new,
            "confirm_password": new if confirm is None else confirm}
    return post("/settings", data).get_data(as_text=True)


set_admin_pwd("OldPass123")
form = get("/settings")
check("表单有 3 个密码框（原 / 新 / 确认）", form.count('type="password"') == 3,
      form.count('type="password"'))
check("有“显示新密码”开关（点开能肉眼比对两次输入）",
      'class="chk"' in form and "wbEye" in form)
check("规则提示来自 core.passwords（单一来源）",
      "至少 8 位，需同时包含字母和数字" in form)

b = change("OldPass123", "NewPass456", "NewPass999")
check("两次输入不一致被拒", "两次输入的新密码不一致" in b)
check("不一致时密码没变", admin_pwd_is("OldPass123"))

b = post("/settings", {"old_password": "OldPass123", "new_password": "Abc12345"})
check("只提交一个新密码框（绕过前端）被拒",
      "两次输入的新密码不一致" in b.get_data(as_text=True))
check("绕过前端时密码没变", admin_pwd_is("OldPass123"))

check("空提交提示的是长度而不是原密码错", "新密码至少 8 位" in change("OldPass123", ""))
check("3 位被拒", "新密码至少 8 位" in change("OldPass123", "Ab1"))
check("纯数字 8 位被拒", "需同时包含字母和数字" in change("OldPass123", "12345678"))
check("纯字母 8 位被拒", "需同时包含字母和数字" in change("OldPass123", "abcdefgh"))
check("首尾带空格被拒（不悄悄 strip）",
      "不能以空格开头或结尾" in change("OldPass123", " Abc12345"))
check("与原密码相同被拒", "不能与原密码相同" in change("OldPass123", "OldPass123"))
check("默认口令 admin123 被拒", "该密码过于常见" in change("OldPass123", "admin123"))
b = change("wrong", "NewPass456")
check("原密码错只说原密码错（不再是三合一长句）",
      "原密码错误" in b and "或新密码太短" not in b)

texts = {re.search(r'class="flash[^"]*">(.*?)<', x).group(1)
         for x in (change("wrong", "NewPass456"),
                   change("OldPass123", "Ab1"),
                   change("OldPass123", "12345678"),
                   change("OldPass123", "NewPass456", "Other456"))}
check("四种失败的文案互不相同（能定位到哪一项错）", len(texts) == 4, len(texts))

set_admin_pwd("OldPass123")
r = client.post("/settings?action=login",
                data={"old_password": "OldPass123", "new_password": "NewPass456",
                      "confirm_password": "NewPass456"}, follow_redirects=False)
check("成功后 302（PRG，刷新不会重发）", r.status_code == 302, r.status_code)
check("跳回 /settings 并带回原日志筛选", "action=login" in r.headers.get("Location", ""),
      r.headers.get("Location"))
check("新密码已生效", admin_pwd_is("NewPass456"))
check("旧密码已失效", not admin_pwd_is("OldPass123"))
check("改完当前会话仍可用（不被踢）", client.get("/").status_code == 200)

set_admin_pwd("OldPass123")
b = post("/settings", {"old_password": "OldPass123", "new_password": "NewPass456",
                       "confirm_password": "NewPass456"}).get_data(as_text=True)
check("成功提示是 ok 样式、文案为“密码已修改”",
      'class="flash ok"' in b and "密码已修改" in b)

rows = sql("SELECT detail FROM audit WHERE action='change_password'")
check("审计记了 change_password", len(rows) >= 1, len(rows))
check("审计不记密码值", not any("NewPass456" in (r["detail"] or "") for r in rows))
check("失败也记审计（change_password_failed）",
      scalar("SELECT COUNT(*) FROM audit WHERE action='change_password_failed'") >= 1)

set_admin_pwd("OldPass123")
client.post("/settings", data={"old_password": "OldPass123", "new_password": "NewPass456",
                               "confirm_password": "NewPass456"})
b = client.post("/settings", data={"old_password": "OldPass123", "new_password": "NewPass456",
                                   "confirm_password": "NewPass456"},
                follow_redirects=True).get_data(as_text=True)
check("重发旧表单（模拟 F5）只报原密码错", "原密码错误" in b)
check("重发不会把密码改坏", admin_pwd_is("NewPass456"))

print()
print("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}")
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
sys.exit(1 if fails else 0)
