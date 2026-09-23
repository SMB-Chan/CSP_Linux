#!/usr/bin/env bash
# Apply the environment-side configuration that keeps Clip Studio Paint stable
# under Wine. Idempotent: safe to re-run. Touches only the Wine prefix and the
# launcher environment — never the application's own files.
set -euo pipefail
source "$HOME/ClipStudio/env.sh"

DL="$HOME/opt/dl"
GECKO_MSI="$DL/wine-gecko-2.47.4-x86_64.msi"
MONO_MSI="$DL/wine-mono-11.0.0-x86.msi"

log() { printf '\033[36m[csp]\033[0m %s\n' "$*"; }

# --- Wine Gecko (MSHTML) so IE-based panels render instead of going blank ----
if [ -d "$WINEPREFIX/drive_c/windows/system32/gecko" ]; then
    log "wine-gecko already installed"
elif [ -f "$GECKO_MSI" ]; then
    log "installing wine-gecko 2.47.4"
    WINEDEBUG=-all wine msiexec /i "$GECKO_MSI" /qn
fi

# --- Wine Mono (.NET Framework support) -------------------------------------
if wine reg query "HKLM\Software\Microsoft\.NETFramework" /v MonoVersion >/dev/null 2>&1; then
    log "wine-mono already registered"
elif [ -f "$MONO_MSI" ]; then
    log "installing wine-mono 11.0.0"
    WINEDEBUG=-all wine msiexec /i "$MONO_MSI" /qn
fi

# --- Stability registry settings -------------------------------------------
log "registry: Windows version, DLL overrides, crash dialog, services"
wine reg add "HKCU\\Software\\Wine" /v Version /t REG_SZ /d win10 /f >/dev/null
wine reg add "HKCU\\Software\\Wine" /v Drivers /t REG_SZ /d x11 /f >/dev/null
wine reg add "HKCU\\Software\\Wine\\DllOverrides" /v concrt140 /t REG_SZ /d "native,builtin" /f >/dev/null
wine reg add "HKCU\\Software\\Wine\\WineDbg" /v ShowCrashDialog /t REG_DWORD /d 0 /f >/dev/null
# Wine services that only add startup latency / device-enumeration hangs here.
wine reg add "HKLM\\System\\CurrentControlSet\\Services\\PlugPlay" /v Start /t REG_DWORD /d 4 /f >/dev/null
wine reg add "HKLM\\System\\CurrentControlSet\\Services\\WineBus" /v Start /t REG_DWORD /d 4 /f >/dev/null

# --- Japanese font substitution --------------------------------------------
# Host has Noto Sans CJK JP; map the Windows Japanese faces onto it so CSP and
# its web panels pick a real Japanese font instead of falling back to boxes.
log "registry: Japanese font replacements"
FR="HKCU\\Software\\Wine\\Fonts\\Replacements"
wine reg add "$FR" /v "MS Gothic" /t REG_SZ /d "Noto Sans Mono CJK JP" /f >/dev/null
wine reg add "$FR" /v "MS PGothic" /t REG_SZ /d "Noto Sans CJK JP" /f >/dev/null
wine reg add "$FR" /v "ＭＳ ゴシック" /t REG_SZ /d "Noto Sans Mono CJK JP" /f >/dev/null
wine reg add "$FR" /v "ＭＳ Ｐゴシック" /t REG_SZ /d "Noto Sans CJK JP" /f >/dev/null
wine reg add "$FR" /v "MS UI Gothic" /t REG_SZ /d "Noto Sans CJK JP" /f >/dev/null
wine reg add "$FR" /v "Meiryo" /t REG_SZ /d "Noto Sans CJK JP" /f >/dev/null
wine reg add "$FR" /v "Meiryo UI" /t REG_SZ /d "Noto Sans CJK JP" /f >/dev/null
wine reg add "$FR" /v "Yu Gothic" /t REG_SZ /d "Noto Sans CJK JP" /f >/dev/null
wine reg add "$FR" /v "Yu Gothic UI" /t REG_SZ /d "Noto Sans CJK JP" /f >/dev/null
wine reg add "$FR" /v "MS Mincho" /t REG_SZ /d "Noto Serif CJK JP" /f >/dev/null
wine reg add "$FR" /v "ＭＳ 明朝" /t REG_SZ /d "Noto Serif CJK JP" /f >/dev/null

# --- DXVK tuning ------------------------------------------------------------
log "writing dxvk.conf"
cat > "$WINEPREFIX/dxvk.conf" <<'EOF'
dxgi.deferSurfaceCreation = True
dxvk.enableGraphicsPipelineLibrary = True
dxvk.numCompilerThreads = 0
dxvk.maxChunkSize = 16
EOF

log "configuration applied"
