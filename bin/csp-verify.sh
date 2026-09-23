#!/bin/bash
# Reports what is installed inside the prefix and whether the CSP tree looks sane.
set -u
. "$HOME/ClipStudio/env.sh"

CS="$WINEPREFIX/drive_c/Program Files/CELSYS"
PAINTDIR="$CS/CLIP STUDIO 1.5/CLIP STUDIO PAINT"

echo "== prefix =="
echo "wine      : $(wine --version 2>/dev/null)"
echo "prefix    : $WINEPREFIX"
echo "windows ver: $(wine reg query 'HKCU\Software\Wine\Version' 2>/dev/null | awk '/REG_SZ/{print $3}')"

echo
echo "== WebView2 runtime =="
EDGE="$WINEPREFIX/drive_c/Program Files (x86)/Microsoft/EdgeWebView/Application"
if [ -d "$EDGE" ]; then ls "$EDGE"; else echo "MISSING"; fi
wine reg query 'HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}' 2>/dev/null | grep -E 'pv|REG_SZ' || true

echo
echo "== CELSYS tree =="
if [ -d "$CS" ]; then
  du -sh "$CS" 2>/dev/null
  find "$CS" -maxdepth 3 -type d | head -25
else
  echo "MISSING: $CS"
fi

echo
echo "== main executables =="
for f in "$PAINTDIR/CLIPStudioPaint.exe" "$CS/CLIP STUDIO 1.5/CLIP STUDIO/CLIPStudio.exe"; do
  if [ -f "$f" ]; then
    printf '%-70s %s bytes\n' "${f#$WINEPREFIX/drive_c/}" "$(stat -c %s "$f")"
  else
    printf '%-70s MISSING\n' "${f#$WINEPREFIX/drive_c/}"
  fi
done

echo
echo "== .NET assemblies in the CSP tree =="
if [ -d "$CS" ]; then
  ~/opt/pyvenv/bin/python "$CSP_HOME/bin/find-dotnet.py" "$CS" 2>/dev/null | head -20 || \
    python3 "$CSP_HOME/bin/find-dotnet.py" "$CS" | head -20
fi
