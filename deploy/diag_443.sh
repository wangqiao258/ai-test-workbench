#!/usr/bin/env bash
# 443 连通性诊断：一条命令输出可直接截图给网络/运维的结论。
#
# 用法：bash deploy/diag_443.sh <域名或IP> [端口]
# 不给参数时读 DIAG_TARGET；都没有则用示例域名 test.example.com（公开仓库不写真实域名）

set -u

TARGET="${1:-${DIAG_TARGET:-test.example.com}}"
PORT="${2:-443}"
STAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
IFACE=$(ip route get 223.5.5.5 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1)
IP=$(getent hosts "$TARGET" 2>/dev/null | awk '{print $1}' | head -1)
[ -z "$IP" ] && IP="$TARGET"

ok()   { printf '  %-28s \033[32mOK\033[0m    %s\n' "$1" "$2"; }
fail() { printf '  %-28s \033[31mFAIL\033[0m  %s\n' "$1" "$2"; }

echo "============================================================"
echo " 443 连通性诊断（可直接截图给网络/运维）"
echo "============================================================"
printf '%-10s %s\n' "时间" "$STAMP"
printf '%-10s %s  (%s, %s)\n' "执行主机" "$LOCAL_IP" "$(hostname)" "${IFACE:-unknown}"
printf '%-10s %s -> %s\n' "目标" "$TARGET" "$IP"
printf '%-10s %s\n' "端口" "$PORT"
echo

# 1) DNS
if [ "$IP" != "$TARGET" ]; then
  ok "[1] DNS resolve" "$IP"
else
  fail "[1] DNS resolve" "解析失败，只能按 IP 访问"
fi

# 2) ICMP
PING=$(ping -c 3 -W 2 "$IP" 2>/dev/null | tail -2 | tr '\n' ' ')
if echo "$PING" | grep -q "0% packet loss\|0% 丢包"; then
  RTT=$(echo "$PING" | sed -n 's/.*rtt min\/avg\/max\/mdev = \([^/]*\/[^/]*\/[^/]*\)\/.*/\1/p')
  ok "[2] ICMP ping" "0% packet loss${RTT:+, rtt $RTT ms}"
else
  fail "[2] ICMP ping" "$(echo "$PING" | tr -s ' ')"
fi

# 3) 对照端口 22
if timeout 3 bash -c "cat < /dev/null > /dev/tcp/$IP/22" 2>/dev/null; then
  ok "[3] TCP:22 (control)" "可连接"
else
  fail "[3] TCP:22 (control)" "不可连接"
fi

# 4) 问题端口
if timeout 4 bash -c "cat < /dev/null > /dev/tcp/$IP/$PORT" 2>/dev/null; then
  ok "[4] TCP:$PORT (problem)" "可连接"
  PROBLEM=0
else
  fail "[4] TCP:$PORT (problem)" "连接超时"
  PROBLEM=1
fi

# 5) 对照站点
OTHER=$(curl -sk -m 5 -o /dev/null -w "%{http_code}" https://github.com 2>/dev/null)
if [ "$OTHER" != "000" ] && [ -n "$OTHER" ]; then
  ok "[5] github:443 (reference)" "HTTP $OTHER"
else
  fail "[5] github:443 (reference)" "不可达（说明整体出网也有问题）"
fi

# 6) 抓包
if [ "$PROBLEM" = "1" ] && command -v tcpdump >/dev/null 2>&1; then
  TD=$(mktemp)
  (timeout 8 tcpdump -i "${IFACE:-any}" -n "host $IP and tcp port $PORT" -c 6 > "$TD" 2>/dev/null &)
  sleep 2
  curl -sk -m 4 -o /dev/null "https://$IP:$PORT/" 2>/dev/null || true
  sleep 3
  echo
  echo "抓包摘要（$IFACE）:"
  if [ -s "$TD" ]; then
    sed -n 's/^\(.*\)$/  \1/p' "$TD" | head -6
    if grep -q "Flags \[S\]" "$TD" && ! grep -q "Flags \[S\.\]" "$TD"; then
      echo "  => 只看到 SYN，没有 SYN-ACK，也没有 RST：路径上静默丢包"
    fi
  else
    echo "  （未抓到包，可能被更前置的设备丢弃）"
  fi
  rm -f "$TD"
fi

# 7) 本机防火墙
echo
echo "本机防火墙:"
OUT=$(iptables -L OUTPUT -n 2>/dev/null | head -3)
if echo "$OUT" | grep -q "policy ACCEPT" && [ "$(echo "$OUT" | wc -l)" -le 3 ]; then
  echo "  iptables OUTPUT policy ACCEPT（无拦截规则）"
else
  echo "$OUT" | sed 's/^/  /'
fi

# 结论
echo
echo "------------------------------------------------------------"
if [ "$PROBLEM" = "0" ]; then
  echo "结论：$TARGET:$PORT 可正常连接，无需处理。"
else
  echo "结论："
  echo "  SYN 已正常发出，目标未回任何包 —— 路径上被静默丢弃（DROP）。"
  echo "  不是本机问题（防火墙放行、其他站点 443 正常）；"
  echo "  也不是目标服务问题（其他客户端可正常访问）。"
  echo
  echo "需要处理："
  echo "  在网关 $(ip route | awk '/default/ {print $3; exit}') 或目标入口，放行"
  echo "  $LOCAL_IP -> $IP:$PORT 的 TCP 流量。"
fi
echo "============================================================"
