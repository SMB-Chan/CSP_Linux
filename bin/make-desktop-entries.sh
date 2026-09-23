#!/bin/bash
# Creates user-level .desktop entries for Clip Studio Paint (no root needed).
set -u
. "$HOME/ClipStudio/env.sh"

APPDIR="$WINEPREFIX/drive_c/Program Files/CELSYS/CLIP STUDIO 1.5/CLIP STUDIO PAINT"
DEST="$HOME/.local/share/applications"
ICONDIR="$CSP_HOME/share/icons"
mkdir -p "$DEST" "$ICONDIR"

ICON="$ICONDIR/clipstudio.png"
if [ ! -f "$ICON" ]; then
  SRC=$(find "$APPDIR" "$WINEPREFIX/drive_c/Program Files/CELSYS" -maxdepth 4 -iname '*.ico' 2>/dev/null | head -1)
  if [ -n "${SRC:-}" ]; then
    convert "$SRC" -resize 256x256 "$ICON" 2>/dev/null \
      || magick "$SRC" -resize 256x256 "$ICON" 2>/dev/null \
      || cp "$SRC" "$ICONDIR/clipstudio.ico"
  fi
fi
[ -f "$ICON" ] || ICON="$ICONDIR/clipstudio.ico"

cat > "$DEST/clipstudio-paint.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Clip Studio Paint
Name[ja]=Clip Studio Paint
Comment=Clip Studio Paint 5.1.4 (Wine)
Exec=$CSP_HOME/bin/csp-launch.sh %f
Icon=$ICON
Terminal=false
Categories=Graphics;2DGraphics;RasterGraphics;
MimeType=application/x-clipstudio-paint;
StartupWMClass=CLIPStudioPaint.exe
StartupNotify=false
EOF

chmod +x "$CSP_HOME/bin/csp-launch.sh" \
  "$CSP_HOME/bin/pentab.sh" \
  "$CSP_HOME/bin/tourbox-gui.sh"

cat > "$DEST/csp-pentab-settings.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Pen Tablet Settings
Name[ja]=ペンタブレット設定
Comment=Wacom One の筆圧・対応マップ・サイドスイッチ
Comment[ja]=Wacom One の筆圧・対応マップ・サイドスイッチ
Exec=$CSP_HOME/bin/pentab.sh --gui
Icon=input-tablet
Terminal=false
Categories=Settings;HardwareSettings;
Keywords=tablet;pen;wacom;pressure;タブレット;ペン;筆圧;
StartupNotify=false
EOF

cat > "$DEST/csp-tourbox-settings.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=TourBox Settings
Name[ja]=TourBox キー設定
Comment=TourBox Lite のボタン割り当て
Comment[ja]=TourBox Lite のボタン割り当て
Exec=$CSP_HOME/bin/tourbox-gui.sh
Icon=input-gaming
Terminal=false
Categories=Settings;HardwareSettings;
Keywords=tourbox;shortcut;hotkey;ショートカット;キー;
StartupNotify=false
EOF

chmod +x "$DEST/csp-pentab-settings.desktop" "$DEST/csp-tourbox-settings.desktop"
update-desktop-database "$DEST" 2>/dev/null
echo "[csp] wrote $DEST/clipstudio-paint.desktop (icon: ${ICON:-none})"
echo "[csp] wrote $DEST/csp-pentab-settings.desktop"
echo "[csp] wrote $DEST/csp-tourbox-settings.desktop"
