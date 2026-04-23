#!/usr/bin/env bash
set -euo pipefail

NAME="${1:-VideoMergingTool}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements-build.txt

rm -rf build

./.venv/bin/pyinstaller \
  --onefile \
  --clean \
  --name "$NAME" \
  --collect-all typer \
  --collect-all click \
  --collect-all rich \
  main.py

echo
echo "Build complete: $PROJECT_ROOT/dist/$NAME"
