from __future__ import annotations

import argparse
import logging
import shutil
import sys
import platform
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from videomerge.env_check import download_ffmpeg_tools
from videomerge.architecture import require_macos_architectures
from videomerge.models import ToolPaths


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the minimal FFmpeg tools bundled with installers.")
    parser.add_argument("--output", type=Path, default=Path("build/vendor/ffmpeg"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--architecture", choices=["arm64", "x86_64", "universal2"])
    args = parser.parse_args()

    if args.force and args.output.exists():
        shutil.rmtree(args.output)

    logger = logging.getLogger("prepare-ffmpeg")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.architecture == "universal2":
        if platform.system() != "Darwin":
            parser.error("universal2 tools must be prepared on macOS")
        args.output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="vmt_ffmpeg_slices_") as directory:
            slices = {arch: download_ffmpeg_tools(Path(directory) / arch, logger, arch) for arch in ("x86_64", "arm64")}
            for name in ("ffmpeg", "ffprobe"):
                output = args.output / name
                subprocess.run(["lipo", "-create", str(getattr(slices["x86_64"], name)), str(getattr(slices["arm64"], name)), "-output", str(output)], check=True)
                output.chmod(0o755)
                require_macos_architectures(output, {"x86_64", "arm64"})
                subprocess.run(["codesign", "--force", "--sign", "-", str(output)], check=True)
        tools = ToolPaths(args.output / "ffmpeg", args.output / "ffprobe")
    else:
        tools = download_ffmpeg_tools(args.output, logger, args.architecture)

    for path in args.output.iterdir():
        if path.name not in {tools.ffmpeg.name, tools.ffprobe.name}:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

    print(f"Bundled ffmpeg: {tools.ffmpeg}")
    print(f"Bundled ffprobe: {tools.ffprobe}")


if __name__ == "__main__":
    main()
