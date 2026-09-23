#!/bin/bash
# ペンタブレット（Wacom One M）の設定操作 — CLIP STUDIO PAINT / Wine
# 引数なし or --gui : 設定画面を開く
#   --show   : 現在の設定と動作中の転送プログラムの状態を表示
#   --set K V: 設定を書き換えて即反映（例: --set pressure.gain 1.4）
#   --reload : 設定ファイルを読み直させる（保存後は自動反映されるので通常は不要）
#   --check  : 設定ファイルの検証のみ
#   --restart: 転送プログラムを再起動（スクリプト自体を更新したときに使う）
#   --status : 転送プログラムの稼働状態だけを表示
set -u
BASE="$HOME/ClipStudio"
CONF="$BASE/etc/pentab.conf"
BRIDGE="$BASE/bin/wacom-pressure.py"
GUI="$HOME/デスクトップ/clip/pentab/pentab-settings.py"
STATUS="$BASE/logs/wacom-pressure-status.json"
LOG="$BASE/logs/wacom-pressure.log"

bridge_pid() {
  local pid
  pid=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["pid"])' "$STATUS" 2>/dev/null)
  if [ -n "${pid:-}" ] && grep -qa 'wacom-pressure.py' "/proc/$pid/cmdline" 2>/dev/null; then
    echo "$pid"; return 0
  fi
  pgrep -f 'wacom-pressure[.]py' | head -1
}

reload() {
  local pid; pid=$(bridge_pid)
  if [ -z "${pid:-}" ]; then
    echo "転送プログラムは起動していません（設定は次回 CSP 起動時に読み込まれます）"
    return 1
  fi
  kill -HUP "$pid" && echo "転送プログラム (PID $pid) に設定の再読み込みを指示しました"
}

restart() {
  local pid; pid=$(bridge_pid)
  local args=() env=()
  if [ -n "${pid:-}" ]; then
    mapfile -t args < <(tr '\0' '\n' < "/proc/$pid/cmdline" | tail -n +3)
    while IFS= read -r line; do
      case "$line" in DISPLAY=*|XAUTHORITY=*|WAYLAND_DISPLAY=*|XDG_RUNTIME_DIR=*|PSM_LOG_FILE=*) env+=("$line");; esac
    done < <(tr '\0' '\n' < "/proc/$pid/environ")
    kill "$pid"; for _ in $(seq 1 20); do
      [ -d "/proc/$pid" ] || break
      # ゾンビ（終了済み・回収待ち）は停止完了として扱う
      [ "$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null)" = Z ] && break
      sleep .3
    done
    [ -d "/proc/$pid" ] && [ "$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null)" != Z ] \
      && { echo "停止できませんでした (PID $pid)"; return 1; }
  fi
  env DISPLAY="${DISPLAY:-:0}" "${env[@]}" setsid nohup python3 "$BRIDGE" "${args[@]}" \
    >> "$BASE/logs/wacom-pressure-console.log" 2>&1 &
  sleep 1.5
  pid=$(bridge_pid)
  if [ -n "${pid:-}" ]; then
    echo "転送プログラムを再起動しました (PID $pid)"
    tail -4 "$LOG"
  else
    echo "再起動に失敗しました。ログ: $BASE/logs/wacom-pressure-console.log"
    tail -6 "$BASE/logs/wacom-pressure-console.log"
    return 1
  fi
}

case "${1:-}" in
  --show)
    python3 "$BRIDGE" --config "$CONF" --check || exit 1
    echo
    pid=$(bridge_pid)
    if [ -n "${pid:-}" ]; then
      echo "転送プログラム: 稼働中 (PID $pid)"
      python3 - "$STATUS" <<'PY'
import json, sys, time
try:
    st = json.load(open(sys.argv[1]))
except OSError:
    raise SystemExit('状態ファイルがまだありません: '+sys.argv[1])
print('  PSM 接続: {} / CSP 前面: {} / 排他占有: {} / 送信 {} パケット / 最大筆圧 {}'.format(
    'あり' if st.get('connected') else 'なし', 'はい' if st.get('active') else 'いいえ',
    'はい' if st.get('grabbed') else 'いいえ',
    st.get('packets'), st.get('max_pressure')))
if st.get('settings'):
    print('  反映中の設定: '+json.dumps(st['settings'], ensure_ascii=False))
age = time.time()-st.get('updated', 0)
print(f'  状態更新: {age:.0f} 秒前')
PY
    else
      echo "転送プログラム: 停止中（CSP 起動時に自動で始まります）"
    fi
    ;;
  --set)
    [ $# -ge 3 ] || { echo "使い方: $0 --set section.key value （例: --set pressure.gain 1.4）"; exit 2; }
    python3 - "$CONF" "$2" "$3" <<'PY'
import re, sys, pathlib
path, key, value = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
if '.' not in key:
    raise SystemExit('キーは pressure.gain のように「セクション.キー」で指定してください')
section, name = key.split('.', 1)
text = path.read_text()
lines, done, inside = [], False, False
for line in text.splitlines():
    if line.strip().startswith('['):
        inside = line.strip() == f'[{section}]'
    elif inside and not done:
        m = re.match(rf'^(\s*{re.escape(name)}\s*=)(.*)$', line)
        if m:
            tail = m.group(2)
            comment = tail.split('#', 1)[1].strip() if '#' in tail else ''
            line = f'{name} = {value}' + (f'  # {comment}' if comment else '')
            done = True
    lines.append(line)
if not done:
    raise SystemExit(f'{key} が見つかりません（{path}）')
path.write_text('\n'.join(lines)+'\n')
print(f'{key} = {value}')
PY
    [ $? -eq 0 ] || exit 1
    reload
    ;;
  --reload) reload ;;
  --restart) restart ;;
  --check) python3 "$BRIDGE" --config "$CONF" --check ;;
  --status)
    pid=$(bridge_pid)
    [ -n "${pid:-}" ] && { echo "稼働中 (PID $pid)"; tail -3 "$LOG"; } || echo "停止中"
    ;;
  --gui|"")
    [ -f "$GUI" ] || { echo "設定画面がありません: $GUI"; exit 1; }
    # GNOME/XWayland では GTK4 を X11 バックエンドで動かす。
    GDK_BACKEND="${GDK_BACKEND:-x11}" setsid nohup python3 "$GUI" >> "$BASE/logs/pentab-settings.log" 2>&1 &
    sleep 1
    echo "設定画面を開きました（ログ: $BASE/logs/pentab-settings.log）"
    ;;
  *) echo "使い方: $0 [--gui|--show|--set K V|--reload|--restart|--check|--status]"; exit 2 ;;
esac
