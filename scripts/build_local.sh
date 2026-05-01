#!/usr/bin/env bash
set -euo pipefail

NAME="${1:-VideoMergingTool}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ICON_PNG="$PROJECT_ROOT/assets/icons/VideoMergingTool.png"
ICON_ICNS="$PROJECT_ROOT/assets/icons/VideoMergingTool.icns"
VENDOR_FFMPEG_DIR="$PROJECT_ROOT/build/vendor/ffmpeg"
cd "$PROJECT_ROOT"

python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements-build.txt

rm -rf build

./.venv/bin/python scripts/prepare_ffmpeg.py --output "$VENDOR_FFMPEG_DIR" --force

PYINSTALLER_ARGS=(
  --clean
  --noconfirm
  --name "$NAME"
  --collect-all typer
  --collect-all click
  --collect-all rich
  --collect-all webview
  --collect-all certifi
  --hidden-import videomerge.gui
  --hidden-import tkinter
)

if [[ "$(uname -s)" == "Darwin" ]]; then
  PYINSTALLER_ARGS+=(
    --windowed
    --icon "$ICON_ICNS"
    --add-binary "$VENDOR_FFMPEG_DIR/ffmpeg:ffmpeg"
    --add-binary "$VENDOR_FFMPEG_DIR/ffprobe:ffmpeg"
  )
else
  PYINSTALLER_ARGS+=(
    --onefile
    --windowed
    --icon "$ICON_PNG"
    --add-binary "$VENDOR_FFMPEG_DIR/ffmpeg:ffmpeg"
    --add-binary "$VENDOR_FFMPEG_DIR/ffprobe:ffmpeg"
  )
fi

./.venv/bin/pyinstaller "${PYINSTALLER_ARGS[@]}" main.py

echo
if [[ "$(uname -s)" == "Darwin" && -d "$PROJECT_ROOT/dist/$NAME.app" ]]; then
  DMG_PATH="$PROJECT_ROOT/dist/$NAME.dmg"
  DMG_ROOT="$PROJECT_ROOT/build/dmg-root"
  rm -f "$DMG_PATH"
  rm -rf "$DMG_ROOT"
  mkdir -p "$DMG_ROOT"
  cp -R "$PROJECT_ROOT/dist/$NAME.app" "$DMG_ROOT/"
  ln -s /Applications "$DMG_ROOT/Applications"
  hdiutil create -volname "$NAME" -srcfolder "$DMG_ROOT" -ov -format UDZO "$DMG_PATH"
  echo "Build complete: $PROJECT_ROOT/dist/$NAME.app"
  echo "Installer image: $DMG_PATH"
else
  echo "Build complete: $PROJECT_ROOT/dist/$NAME"
fi
