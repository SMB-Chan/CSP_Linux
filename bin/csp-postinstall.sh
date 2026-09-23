#!/bin/bash
# Post-install environment tuning for Clip Studio Paint under Wine.
# Idempotent: only touches registry keys of the dedicated prefix.
set -u
. "$HOME/ClipStudio/env.sh"

set_appdefault() {
  wine reg add "HKCU\\Software\\Wine\\AppDefaults\\$1" /v Version /t REG_SZ /d "$2" /f >/dev/null 2>&1
  printf '  %-24s -> %s\n' "$1" "$2"
}

echo "[csp] per-application Windows versions"
set_appdefault CLIPStudioPaint.exe win81
set_appdefault CLIPStudio.exe      win81
set_appdefault msedgewebview2.exe  win7

echo "[csp] disabling the WebView2 background updater"
wine reg add 'HKLM\SOFTWARE\Policies\Microsoft\EdgeUpdate' /v UpdateDefault /t REG_DWORD /d 0 /f >/dev/null 2>&1
wine reg add 'HKLM\SOFTWARE\Policies\Microsoft\EdgeUpdate' /v AutoUpdateCheckPeriodMinutes /t REG_DWORD /d 0 /f >/dev/null 2>&1

echo "[csp] suppressing the Wine crash dialog"
wine reg add 'HKCU\Software\Wine\WineDbg' /v ShowCrashDialog /t REG_DWORD /d 0 /f >/dev/null 2>&1

echo "[csp] done"
