from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from videomerge.env_check import download_ffmpeg_tools


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the minimal FFmpeg tools bundled with installers.")
    parser.add_argument("--output", type=Path, default=Path("build/vendor/ffmpeg"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.force and args.output.exists():
        shutil.rmtree(args.output)

    logger = logging.getLogger("prepare-ffmpeg")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    tools = download_ffmpeg_tools(args.output, logger)

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
