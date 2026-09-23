#!/bin/bash
# Launches Clip Studio Paint with the environment settings that keep it stable
# under Wine. Nothing inside the application directory is modified.
set -u
. "$HOME/ClipStudio/env.sh"

# Wacom pressure forwarding via Pain Studio Mask
export PSM_LOG_FILE="$(winepath -w "$CSP_HOME/logs/psm.log" 2>/dev/null)"

# DXVK: point at our config/state cache instead of the app directory.
export DXVK_CONFIG_FILE="$WINEPREFIX/dxvk.conf"
export DXVK_STATE_CACHE=1
export DXVK_STATE_CACHE_PATH="$WINEPREFIX"

# Threading / caching.
export STAGING_SHARED_MEMORY=1
export STAGING_WRITECOPY=1
export mesa_glthread=true
export __GL_SHADER_DISK_CACHE=1
export __GL_SHADER_DISK_CACHE_PATH="$WINEPREFIX"

# WebView2 (asset store / login panels): keep it off the GPU compositor and quiet.
export WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--no-sandbox --disable-gpu-compositing --disable-gpu-vsync --in-process-gpu --disable-background-networking --no-first-run --disable-sync --disable-renderer-accessibility --disable-extensions --disable-component-extensions-with-background-pages --disk-cache-size=33554432 --disable-features=msEdgeSidebar"

PAINT='C:\Program Files\CELSYS\CLIP STUDIO 1.5\CLIP STUDIO PAINT\CLIPStudioPaint.exe'
UNIX_PAINT="$WINEPREFIX/drive_c/Program Files/CELSYS/CLIP STUDIO 1.5/CLIP STUDIO PAINT/CLIPStudioPaint.exe"
if [ ! -f "$UNIX_PAINT" ]; then
  echo "[csp] CLIPStudioPaint.exe not found in $WINEPREFIX" >&2
  exit 1
fi

# Convert Unix file arguments (e.g. a .clip document) to Windows paths.
ARGS=()
for a in "$@"; do
  if [ -f "$a" ]; then
    w="$(winepath -w "$a" 2>/dev/null)" && [ -n "$w" ] && a="$w"
  fi
  ARGS+=("$a")
done

mkdir -p "$CSP_HOME/logs"

# CSP is not running yet, so it is safe to force Wintab. A running CSP writes
# SetContextKindNextBoot back to TabletPC on exit; apply again on every launch.
if ! pgrep -f '[C]LIPStudioPaint\.exe' >/dev/null 2>&1; then
  "$CSP_HOME/bin/csp-tablet-mode.sh" wintab >/dev/null || true
fi

# Start pressure forwarding for this CSP session only.
nohup python3 "$CSP_HOME/bin/wacom-pressure.py" --watch-pid "$$" >> "$CSP_HOME/logs/wacom-pressure-console.log" 2>&1 &

if [ "${ARGS[0]:-}" = "--debug" ]; then
  export WINEDEBUG=warn,err
  wine "$PAINT" "${ARGS[@]:1}" 2>&1 | tee "$CSP_HOME/logs/paint.log"
  exit "${PIPESTATUS[0]}"
fi
export WINEDEBUG="${WINEDEBUG:--all}"
exec wine "$PAINT" "${ARGS[@]}"
