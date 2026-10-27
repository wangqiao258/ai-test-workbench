#!/usr/bin/env bash
# 交互式写入 runner 用的两个 token。
#
# 为什么不直接改 API：AI 写进去的凭证会被安全层替换成随机串，
# 由人在服务器上执行这个脚本、自己粘贴，才能保证库里是真值。
#
# 用法：bash deploy/set_tokens.sh

set -u

printf '员工端 staffToken: '
read -r ST
printf '家长端 memberToken: '
read -r MT

if [ -z "$ST" ] || [ -z "$MT" ]; then
  echo "两个都要填，已中止。"
  exit 1
fi

docker exec -i deploy-platform-1 python - "$ST" "$MT" <<'PY'
import json
import sqlite3
import sys

staff, member = sys.argv[1], sys.argv[2]
conn = sqlite3.connect("/app/data/app.db")
row = conn.execute(
    "SELECT value FROM project_settings WHERE project_id=1 AND key='vars'").fetchone()
v = json.loads(row[0]) if row and row[0] else {}
v["staffToken"] = staff
v["memberToken"] = member
conn.execute(
    "INSERT INTO project_settings (project_id, key, value, updated_by, updated_at) "
    "VALUES (1, 'vars', ?, 'manual', datetime('now')) "
    "ON CONFLICT(project_id, key) DO UPDATE SET "
    "value=excluded.value, updated_by='manual', updated_at=datetime('now')",
    (json.dumps(v, ensure_ascii=False),))
conn.commit()

check = json.loads(conn.execute(
    "SELECT value FROM project_settings WHERE project_id=1 AND key='vars'").fetchone()[0])
print("已写入。当前变量：")
for k in ("baseUrl", "hostHeader", "wecomUserid", "appId", "staffToken", "memberToken"):
    val = check.get(k, "")
    if k.endswith("Token"):
        val = f"{val[:6]}...{val[-4:]}（{len(val)} 位）" if val else "（空）"
    print(f"  {k}: {val}")
PY
