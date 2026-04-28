#!/usr/bin/env bash
set -euo pipefail

NAME="${1:-VideoMergingTool}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ICON_PNG="$PROJECT_ROOT/assets/icons/VideoMergingTool.png"
ICON_ICNS="$PROJECT_ROOT/assets/icons/VideoMergingTool.icns"
cd "$PROJECT_ROOT"

python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements-build.txt

rm -rf build

PYINSTALLER_ARGS=(
  --clean
  --noconfirm
  --name "$NAME"
  --collect-all typer
  --collect-all click
  --collect-all rich
  --collect-all webview
  --hidden-import videomerge.gui
  --hidden-import tkinter
)

if [[ "$(uname -s)" == "Darwin" ]]; then
  PYINSTALLER_ARGS+=(--windowed --icon "$ICON_ICNS")
else
  PYINSTALLER_ARGS+=(--onefile --windowed --icon "$ICON_PNG")
fi

./.venv/bin/pyinstaller "${PYINSTALLER_ARGS[@]}" main.py

echo
if [[ "$(uname -s)" == "Darwin" && -d "$PROJECT_ROOT/dist/$NAME.app" ]]; then
  DMG_PATH="$PROJECT_ROOT/dist/$NAME.dmg"
  rm -f "$DMG_PATH"
  hdiutil create -volname "$NAME" -srcfolder "$PROJECT_ROOT/dist/$NAME.app" -ov -format UDZO "$DMG_PATH"
  echo "Build complete: $PROJECT_ROOT/dist/$NAME.app"
  echo "Installer image: $DMG_PATH"
else
  echo "Build complete: $PROJECT_ROOT/dist/$NAME"
fi
