#!/usr/bin/env bash
# TourBox キー設定画面（GTK4）を起動する。
set -u
BASE="${CSP_HOME:-$HOME/ClipStudio}"
GUI="$HOME/デスクトップ/clip/tourbox/tourbox-settings.py"
LOG="$BASE/logs/tourbox-settings.log"
mkdir -p "$BASE/logs"
[ -f "$GUI" ] || { echo "設定画面がありません: $GUI" >&2; exit 1; }
# GNOME/XWayland では GTK4 を X11 バックエンドで動かす（メモリ参照）。
export GDK_BACKEND="${GDK_BACKEND:-x11}"
setsid nohup python3 "$GUI" >> "$LOG" 2>&1 &
sleep 0.3
echo "TourBox 設定画面を開きました（ログ: $LOG）"
