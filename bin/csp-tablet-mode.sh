#!/usr/bin/env bash
# CSP が使うタブレット API を切り替える。
#
#   ペンでカーソルは動くのに線が引けない場合の対処。
#   CSP は既定で Windows Ink / WMPOINTER (TabletPC) 経由でペンを読むが、
#   Wine はこの API を stub 実装しかしていない（paint.log に
#   `fixme:win:GetPointerDevices ... partial stub` が出る）。
#   その結果ペン先の筆圧・接地が届かず、カーソルだけが動く。
#   Wintab は Wine が実装済みなので、そちらに切り替える。
#
#   使い方:
#     csp-tablet-mode.sh            現在の設定を表示
#     csp-tablet-mode.sh show       同上
#     csp-tablet-mode.sh verify     Wintab 経路（DLL・psm.json・転送）を確認
#     csp-tablet-mode.sh wintab     Wintab を使う（推奨）
#     csp-tablet-mode.sh tabletpc   既定（Windows Ink）に戻す
#
#   CSP 本体は一切改変しない。書き換えるのはユーザー設定 DB のみ。
set -euo pipefail

CSP_HOME="${CSP_HOME:-$HOME/ClipStudio}"
PY="$HOME/opt/pyvenv/bin/python3"
BASE="$CSP_HOME/prefix/drive_c/users/$USER/AppData/Roaming/CELSYSUserData/CELSYS"
CFG="$BASE/CLIPStudioPaintVer1_5_0/Preference/Config.sqlite"
DIG="$BASE/CLIPStudioPaintVer1_5_0/Digitizer/digitizersettings"

[ -x "$PY" ] || PY=python3

if [ ! -f "$CFG" ]; then
  echo "設定 DB が見つかりません: $CFG" >&2
  echo "CSP を一度起動して終了してから、もう一度実行してください。" >&2
  exit 1
fi

mode="${1:-show}"

# CSP が動いていると終了時に設定を上書きしてしまう。
# pgrep は自プロセスのコマンド行にもマッチするので [C] で除外する。
if pgrep -f '[C]LIPStudioPaint\.exe' >/dev/null 2>&1; then
  if [ "$mode" != "show" ] && [ "$mode" != "verify" ]; then
    echo "CLIP STUDIO PAINT が起動中です。" >&2
    echo "作業を保存して終了してから実行してください（終了時に設定が上書きされます）。" >&2
    exit 1
  fi
fi

case "$mode" in
  show)
    "$PY" - "$CFG" "$DIG" <<'EOF'
import sqlite3, sys, os
cfg, dig = sys.argv[1], sys.argv[2]
c = sqlite3.connect(cfg)
row = c.execute(
    "select SetContextKindNextBoot, ContextKind, UseMouseMode, UseAccurateWMPointer from Tablet"
).fetchone()
names = {0: "TabletPC / Windows Ink (Wine では未実装 → 線が引けない)",
         1: "Wintab (Wine 実装あり → 推奨)"}
boot = row[0] if row else None
print("SetContextKindNextBoot = %s  %s" % (boot, names.get(boot, "不明")))
print("  ※ CSP 起動中・終了時にここが 0 へ書き戻ることがある。次回 csp-launch.sh / 転送終了時に 1 へ戻す。")
print("ContextKind            = %s" % (row[1] if row else None))
print("UseMouseMode           = %s  (1=座標はマウス / 0=タブレット座標)" % (row[2] if row else None))
print("UseAccurateWMPointer   = %s  (Wine の WM_POINTER は未実装なので 0 推奨)" % (row[3] if row else None))
row2 = c.execute("select IsEffective from Tablet").fetchone()
print("IsEffective            = %s  (1=タブレット設定を有効)" % (row2[0] if row2 else None))
if os.path.exists(dig):
    d = sqlite3.connect("file:%s?mode=ro" % dig, uri=True)
    r = d.execute("select coexistmode from general").fetchone()
    print("coexistmode            = %s" % (r[0] if r else None))
EOF
    ;;
  verify)
    csp_run=0
    pgrep -f '[C]LIPStudioPaint\.exe' >/dev/null 2>&1 && csp_run=1
    "$PY" - "$CFG" "$CSP_HOME" "$csp_run" <<'EOF'
import json, os, sqlite3, sys
cfg, home, csp_run = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
ok = True
def check(label, cond, detail=""):
    global ok
    mark = "OK " if cond else "NG "
    if not cond:
        ok = False
    print(f"{mark} {label}" + (f"  ({detail})" if detail else ""))

c = sqlite3.connect(cfg)
row = c.execute("select SetContextKindNextBoot, UseMouseMode, UseAccurateWMPointer, IsEffective from Tablet").fetchone()
boot = row[0] if row else None
if csp_run and boot == 0:
    # CSP は NextBoot を終了時に TabletPC へ書き戻す。本セッションは
    # csp-launch.sh が起動直前に Wintab を適用済みなので NG にしない。
    print(f"NOTE SetContextKindNextBoot={boot}  CSP 起動中に書換済み。"
          f"次回は csp-launch.sh が Wintab に戻します（本セッションは起動時適用）")
else:
    check("タブレットサービス = Wintab", boot == 1, f"SetContextKindNextBoot={boot}")
check("UseAccurateWMPointer = 0 推奨", row and row[2] == 0, f"現在 {row[2] if row else None}")
check("IsEffective = 1", row and row[3] == 1, f"現在 {row[3] if row else None}")

sys32 = os.path.join(home, "prefix/drive_c/windows/system32/wintab32.dll")
check("system32/wintab32.dll", os.path.isfile(sys32), sys32)
psm = os.path.join(home, "prefix/drive_c/users", os.environ.get("USER", "intel"), "AppData/Local/psm.json")
check("psm.json (Wintab 形状)", os.path.isfile(psm), psm)
preset = os.path.join(home, "pressure/psm.json")
check("pressure/psm.json (転送側)", os.path.isfile(preset), preset)

status = os.path.join(home, "logs/wacom-pressure-status.json")
if os.path.isfile(status):
    s = json.load(open(status))
    check("転送ブリッジ稼働", not s.get("stopped") and os.path.exists(f"/proc/{s.get('pid')}"))
    check("PSM 接続", bool(s.get("connected")))
else:
    check("転送ブリッジ状態", False, status)

print("結果:", "問題なし" if ok else "上記 NG を確認してください")
sys.exit(0 if ok else 1)
EOF
    ;;
  accurate)
    # UseAccurateWMPointer: on / off （Wine では off 推奨）
    val=1; [ "${2:-}" = "off" ] && val=0
    if [ "${2:-}" != "on" ] && [ "${2:-}" != "off" ]; then
      echo "使い方: csp-tablet-mode.sh accurate on|off" >&2
      exit 1
    fi
    cp -f "$CFG" "$CFG.bak.$(date +%Y%m%d%H%M%S)"
    "$PY" - "$CFG" "$val" <<'EOF'
import sqlite3, sys
cfg, val = sys.argv[1], int(sys.argv[2])
c = sqlite3.connect(cfg)
cur = c.execute("select _PW_ID from Tablet")
if cur.fetchone() is None:
    c.execute("insert into Tablet (UseAccurateWMPointer) values (?)", (val,))
else:
    c.execute("update Tablet set UseAccurateWMPointer=?", (val,))
c.commit()
print("UseAccurateWMPointer -> %d" % val)
EOF
    echo "設定しました。次回 CSP 起動時から有効になります。"
    ;;
  wintab|tabletpc)
    val=1; [ "$mode" = "tabletpc" ] && val=0
    cp -f "$CFG" "$CFG.bak.$(date +%Y%m%d%H%M%S)"
    "$PY" - "$CFG" "$val" <<'EOF'
import sqlite3, sys
cfg, val = sys.argv[1], int(sys.argv[2])
c = sqlite3.connect(cfg)
cur = c.execute("select _PW_ID from Tablet")
if cur.fetchone() is None:
    c.execute("insert into Tablet (SetContextKindNextBoot, IsEffective, UseAccurateWMPointer) values (?, 1, 0)", (val,))
else:
    # IsEffective: タブレット設定を有効にする。UseAccurateWMPointer=0 は
    # Wine の WM_POINTER 未実装を避ける。CSP 終了時に NextBoot だけが
    # TabletPC へ戻るので、その都度 wintab を書き直す（csp-launch.sh が行う）。
    c.execute("update Tablet set SetContextKindNextBoot=?, IsEffective=1, UseAccurateWMPointer=0", (val,))
c.commit()
print("SetContextKindNextBoot -> %d  (IsEffective=1, UseAccurateWMPointer=0)" % val)
EOF
    echo "設定しました。次回 CSP 起動時から有効になります。"
    [ "$mode" = "wintab" ] && cat <<'MSG'

起動後に CSP 側でも確認してください:
  環境設定 → タブレット → 使用するタブレットサービス = Wintab
筆圧が効かない場合は 環境設定 → タブレット で筆圧調整を実行。
MSG
    ;;
  *)
    echo "使い方: csp-tablet-mode.sh [show|verify|wintab|tabletpc|accurate on|off]" >&2
    exit 1
    ;;
esac
