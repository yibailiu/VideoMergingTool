#!/usr/bin/env bash
set -euo pipefail

NAME="${1:-VideoMergingTool}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ICON_PNG="$PROJECT_ROOT/assets/icons/VideoMergingTool.png"
ICON_ICNS="$PROJECT_ROOT/assets/icons/VideoMergingTool.icns"
VENDOR_FFMPEG_DIR="$PROJECT_ROOT/build/vendor/ffmpeg"
MACOS_CODESIGN_IDENTITY="${MACOS_CODESIGN_IDENTITY:--}"
cd "$PROJECT_ROOT"

if [[ "${VMT_FRONTEND_PREBUILT:-0}" != "1" ]]; then
  npm --prefix frontend ci --no-audit --no-fund
  npm --prefix frontend run build
fi

PYTHON="${VMT_PYTHON_BINARY:-python3}"
MACOS_TARGET_ARCH="${MACOS_TARGET_ARCH:-universal2}"
if [[ "$(uname -s)" == "Darwin" && "$MACOS_TARGET_ARCH" == "universal2" ]]; then
  lipo -verify_arch x86_64 arm64 "$("$PYTHON" -c 'import sys; print(sys.executable)')"
fi
"$PYTHON" -m venv .venv-build
BUILD_PYTHON="$PROJECT_ROOT/.venv-build/bin/python"
"$BUILD_PYTHON" -m pip install --upgrade pip
"$BUILD_PYTHON" -m pip install -r requirements-build.txt
"$BUILD_PYTHON" scripts/verify_bundle.py videomerge/web --web-only
VERSION="$("$BUILD_PYTHON" -c 'from videomerge import __version__; print(__version__)')"
BUNDLE_VERSION="${VERSION%%-*}"

rm -rf build

FFMPEG_ARGS=()
if [[ "$(uname -s)" == "Darwin" ]]; then
  FFMPEG_ARGS+=(--architecture "$MACOS_TARGET_ARCH")
fi
"$BUILD_PYTHON" scripts/prepare_ffmpeg.py --output "$VENDOR_FFMPEG_DIR" --force "${FFMPEG_ARGS[@]}"

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
  --add-data "$PROJECT_ROOT/videomerge/web:videomerge/web"
)

if [[ "$(uname -s)" == "Darwin" ]]; then
  PYINSTALLER_ARGS+=(
    --windowed
    --target-arch "$MACOS_TARGET_ARCH"
    --codesign-identity "$MACOS_CODESIGN_IDENTITY"
    --icon "$ICON_ICNS"
    --osx-bundle-identifier "com.yibailiu.VideoMergingTool"
    --hidden-import Foundation
    --hidden-import AppKit
    --hidden-import UserNotifications
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

./.venv-build/bin/pyinstaller "${PYINSTALLER_ARGS[@]}" main.py

echo
if [[ "$(uname -s)" == "Darwin" && -d "$PROJECT_ROOT/dist/$NAME.app" ]]; then
  DMG_PATH="$PROJECT_ROOT/dist/$NAME.dmg"
  DMG_ROOT="$PROJECT_ROOT/build/dmg-root"
  INFO_PLIST="$PROJECT_ROOT/dist/$NAME.app/Contents/Info.plist"
  plutil -replace CFBundleShortVersionString -string "$BUNDLE_VERSION" "$INFO_PLIST"
  plutil -replace CFBundleVersion -string "$VERSION" "$INFO_PLIST"
  plutil -replace CFBundleIconFile -string "VideoMergingTool.icns" "$INFO_PLIST"
  plutil -remove CFBundleIconName "$INFO_PLIST" 2>/dev/null || true
  CODESIGN_ARGS=(--force --deep --sign "$MACOS_CODESIGN_IDENTITY")
  if [[ "$MACOS_CODESIGN_IDENTITY" != "-" ]]; then
    CODESIGN_ARGS+=(--options runtime --timestamp)
  fi
  codesign "${CODESIGN_ARGS[@]}" "$PROJECT_ROOT/dist/$NAME.app"
  VERIFY_ARGS=()
  if [[ "$MACOS_TARGET_ARCH" == "universal2" ]]; then
    VERIFY_ARGS+=(--universal)
  fi
  "$BUILD_PYTHON" scripts/verify_bundle.py "$PROJECT_ROOT/dist/$NAME.app" "${VERIFY_ARGS[@]}"
  touch "$PROJECT_ROOT/dist/$NAME.app"
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
