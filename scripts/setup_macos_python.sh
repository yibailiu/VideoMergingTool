#!/usr/bin/env bash
set -euo pipefail

# Deliberately CI-only: local builds should point VMT_PYTHON_BINARY at an existing
# python.org universal2 installation instead of modifying the user's system.
[[ "${GITHUB_ACTIONS:-}" == "true" && "$(uname -s)" == "Darwin" ]] || {
  echo "This installer is for macOS GitHub runners only." >&2
  exit 1
}
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
read -r PYTHON_VERSION PYTHON_URL PYTHON_SHA < <(python3 -c 'import json,sys; p=json.load(open(sys.argv[1]))["python"]; print(p["version"],p["url"],p["sha256"])' "$PROJECT_ROOT/scripts/macos-build-inputs.json")
PACKAGE_DIR="$(mktemp -d "${RUNNER_TEMP}/vmt-python.XXXXXX")"
PACKAGE_PATH="$PACKAGE_DIR/python.pkg"
curl --fail --location --retry 3 --output "$PACKAGE_PATH" "$PYTHON_URL"
printf '%s  %s\n' "$PYTHON_SHA" "$PACKAGE_PATH" | shasum -a 256 -c -
pkgutil --check-signature "$PACKAGE_PATH"
sudo installer -pkg "$PACKAGE_PATH" -target /
PYTHON_SERIES="${PYTHON_VERSION%.*}"
PYTHON_BINARY="/Library/Frameworks/Python.framework/Versions/$PYTHON_SERIES/bin/python$PYTHON_SERIES"
"$PYTHON_BINARY" -c 'import sys; print(sys.version)'
"$PYTHON_BINARY" "$PROJECT_ROOT/scripts/verify_python_architecture.py"
echo "VMT_PYTHON_BINARY=$PYTHON_BINARY" >> "$GITHUB_ENV"
echo "MACOSX_DEPLOYMENT_TARGET=13.0" >> "$GITHUB_ENV"
echo "ARCHFLAGS=-arch x86_64 -arch arm64" >> "$GITHUB_ENV"
