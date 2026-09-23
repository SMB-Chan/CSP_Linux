#!/usr/bin/env bash
# Capture a screenshot of a window belonging to the CSP Wine prefix.
# Usage: wineshot.sh [out.png] [name-regex]
# Requires ImageMagick (import) and x11-utils (xwininfo), both present on this host.
set -euo pipefail
source "$HOME/ClipStudio/env.sh"

out="${1:-$HOME/ClipStudio/logs/shot-$(date +%H%M%S).png}"
filter="${2:-}"

mapfile -t wins < <(xwininfo -root -tree -all 2>/dev/null | awk 'NF>3 {print}')
printf '%s\n' "${wins[@]}" | grep -iE "$filter" || true
echo "--- all top-level-ish windows ---"
xwininfo -root -children 2>/dev/null | sed -n '1,40p'

id=$(xwininfo -root -tree 2>/dev/null \
     | grep -iE 'CLIPStudio|CELSYS|Clip Studio|Wine|Setup|Install' \
     | grep -viE 'xwininfo|"root"' \
     | awk '{print $1}' | tail -1 || true)

if [ -z "$id" ]; then
    echo "no matching X11 window found" >&2
    exit 2
fi
echo "capturing window $id -> $out"
import -window "$id" "$out"
echo "saved $out"
