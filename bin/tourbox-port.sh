#!/usr/bin/env bash
# TourBox Lite (VID cafe / PID 4001) は CDC-ACM デバイスで /dev/ttyACM* として現れる。
# Wine の COM1 にその実体を割り当てる。再接続で番号が変わっても追従する。
set -euo pipefail
source "$HOME/ClipStudio/env.sh"

VID=cafe
PID=4001
port=""
for t in /sys/class/tty/ttyACM*; do
  [ -e "$t" ] || continue
  d="$(readlink -f "$t/device/.." 2>/dev/null)" || continue
  vid="$(cat "$d/idVendor" 2>/dev/null || true)"
  pid="$(cat "$d/idProduct" 2>/dev/null || true)"
  if [ "$vid" = "$VID" ] && [ "$pid" = "$PID" ]; then
    port="/dev/$(basename "$t")"
    break
  fi
done

if [ -z "$port" ]; then
  echo "TourBox (cafe:4001) が見つかりません。USB 接続を確認してください。" >&2
  exit 1
fi
if [ ! -r "$port" ] || [ ! -w "$port" ]; then
  echo "警告: $port に読み書きできません (dialout グループ権限が必要)" >&2
fi

wine reg add 'HKLM\Software\Wine\Ports' /v com1 /d "$port" /f >/dev/null
echo "$port"
