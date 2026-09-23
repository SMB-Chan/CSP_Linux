#!/bin/bash
# TourBox Lite ネイティブドライバの起動ラッパ
#
#   tourbox-daemon.sh              常駐（ログ: ~/ClipStudio/logs/tourbox-daemon.log）
#   tourbox-daemon.sh --scan       ボタンコード確認（フォアグラウンド）
#   tourbox-daemon.sh --probe      デバイス応答の確認だけ
#   tourbox-daemon.sh --test ACT   注入テスト
#   tourbox-daemon.sh --stop       停止
set -euo pipefail

CSP_HOME="${CSP_HOME:-$HOME/ClipStudio}"
PY="$HOME/opt/pyvenv/bin/python3"
DAEMON="$CSP_HOME/bin/tourbox-daemon.py"
CONF="$CSP_HOME/etc/tourbox.conf"
RUN_DIR="$CSP_HOME/run"
PIDFILE="$RUN_DIR/tourbox-daemon.pid"
LOG="$CSP_HOME/logs/tourbox-daemon.log"

mkdir -p "$RUN_DIR" "$CSP_HOME/logs"
export DISPLAY="${DISPLAY:-:0}"

case "${1:-}" in
  --stop)
    if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      pid="$(cat "$PIDFILE")"
      kill "$pid" && echo "停止しました (PID $pid)"
      rm -f "$PIDFILE"
    else
      rm -f "$PIDFILE"
      echo "起動していません"
    fi
    exit 0
    ;;
  --reload)
    if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      kill -HUP "$(cat "$PIDFILE")" && echo "設定を再読み込みしました"
      exit 0
    fi
    echo "起動していません（先に tourbox-daemon.sh で起動してください）" >&2
    exit 1
    ;;
  --status)
    if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "稼働中 (PID $(cat "$PIDFILE"))"
      exit 0
    fi
    echo "停止しています"
    exit 1
    ;;
esac

if [[ ! -x "$PY" ]]; then
  echo "error: $PY が見つかりません（python-xlib が必要です）" >&2
  exit 1
fi

case "${1:-}" in
  --scan|--probe|--test)
    exec "$PY" "$DAEMON" --config "$CONF" "$@"
    ;;
esac

if [[ -f "$PIDFILE" ]]; then
  if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "すでに起動しています (PID $(cat "$PIDFILE"))"
    exit 0
  fi
  rm -f "$PIDFILE"          # 前回異常終了した残骸を掃除する
fi

echo "起動します。ログ: $LOG"
setsid nohup "$PY" "$DAEMON" --config "$CONF" >>"$LOG" 2>&1 &
echo $! >"$PIDFILE"
sleep 1
if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "PID $(cat "$PIDFILE") で起動しました"
else
  echo "起動に失敗しました。ログを確認してください:" >&2
  tail -20 "$LOG" >&2
  exit 1
fi
