#!/usr/bin/env bash
# TourBox Console 5.11.3 (Wine prefix 内) を起動する。
# 起動前に COM1 -> /dev/ttyACM* の割り当てを更新する。
set -euo pipefail
source "$HOME/ClipStudio/env.sh"

CONSOLE='C:\Program Files\TourBox Console\TourBox Console.exe'
mkdir -p "$CSP_HOME/logs"

port="$("$CSP_HOME/bin/tourbox-port.sh" || true)"
if [ -n "$port" ]; then
  echo "TourBox を $port として COM1 に割り当てました"
else
  echo "警告: TourBox 未接続のまま起動します" >&2
fi

if [ "${1:-}" = "--debug" ]; then
  export WINEDEBUG=warn,err,+comm,+file
  wine "$CONSOLE" 2>&1 | tee "$CSP_HOME/logs/tourbox-console.log"
  exit "${PIPESTATUS[0]}"
fi

export WINEDEBUG="${WINEDEBUG:--all}"
cd "$WINEPREFIX/drive_c/Program Files/TourBox Console"
exec wine "$CONSOLE" >>"$CSP_HOME/logs/tourbox-console.log" 2>&1
