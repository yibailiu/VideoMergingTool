from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from videomerge.architecture import macho_architectures, require_macos_architectures
from videomerge.self_check import verify_web_assets


def verify_app(app: Path, universal: bool = False) -> None:
    resources = app / "Contents" / "Resources"
    verify_web_assets(resources / "videomerge" / "web")
    tools = [resources / "ffmpeg" / name for name in ("ffmpeg", "ffprobe")]
    for path in tools:
        if not path.is_file():
            raise RuntimeError(f"Missing bundled tool: {path}")
    count = 0
    for path in app.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        arches = macho_architectures(path)
        if not arches:
            continue
        count += 1
        if universal:
            require_macos_architectures(path, {"x86_64", "arm64"})
        dependencies = subprocess.check_output(["otool", "-L", str(path)], text=True)
        for line in dependencies.splitlines():
            if not line[:1].isspace():
                continue
            dependency = line.strip().split(" (", 1)[0]
            if dependency.startswith("/") and not dependency.startswith(("/usr/lib/", "/System/")) and not dependency.endswith(":"):
                raise RuntimeError(f"Non-portable dependency in {path}: {dependency}")
    if not count:
        raise RuntimeError("No native executable was found")
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    print(f"Verified {count} native binaries in {app}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--universal", action="store_true")
    parser.add_argument("--web-only", action="store_true")
    args = parser.parse_args()
    if args.web_only:
        print(verify_web_assets(args.path))
    else:
        verify_app(args.path, args.universal)
