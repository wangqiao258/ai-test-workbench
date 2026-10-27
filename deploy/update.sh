#!/usr/bin/env bash
# 一键更新：备份 → 拉代码 → 构建 → 副本库 smoke → 绿才重启；任何一步失败都不切换（旧容器照跑）。
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE="docker compose -f deploy/docker-compose.yml"
TS=$(date +%Y%m%d-%H%M)
BAK="backups/${TS}_app.db.bak"
mkdir -p backups
trap 'echo "更新中断：未切换，旧版本仍在运行（备份在 ${BAK}）" >&2' ERR

echo "[1/5] 备份数据库 -> ${BAK}"
if $COMPOSE ps --status running -q platform 2>/dev/null | grep -q .; then
  $COMPOSE exec -T platform python -c "import sqlite3; s=sqlite3.connect('/app/data/app.db'); d=sqlite3.connect('/app/backups/${TS}_app.db.bak'); s.backup(d); d.close(); s.close()"
else
  cp data/app.db "${BAK}"   # 容器没在跑=冷备，直接 cp 安全
fi

echo "[2/5] 拉取代码"
git pull --ff-only

echo "[3/5] 构建镜像（旧容器不受影响）"
$COMPOSE build

echo "[4/5] 副本库 smoke 验证（不碰真库）"
$COMPOSE run --rm --no-deps platform python tests/smoke_api.py

echo "[5/5] 重启生效"
$COMPOSE up -d
echo "更新完成。备份在 ${BAK}"
