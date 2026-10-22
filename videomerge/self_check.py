"""Offline checks executed against the packaged application before publication."""
from __future__ import annotations

import logging
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__
from .env_check import _bundled_binary, default_tools_dir, resolve_tools
from .merge import concat_copy
from .models import MergeMode, ToolPaths
from .probe import probe_file


def verify_web_assets(root: Path) -> list[str]:
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"Missing Vue entry: {index}")
    references = re.findall(r'(?:src|href)="(/assets/[^"?#]+)', index.read_text(encoding="utf-8"))
    if not any(path.endswith(".js") for path in references) or not any(path.endswith(".css") for path in references):
        raise RuntimeError("Vue entry does not reference built JavaScript and CSS")
    for reference in references:
        candidate = (root / reference.lstrip("/")).resolve()
        if root.resolve() not in candidate.parents or not candidate.is_file():
            raise RuntimeError(f"Missing or unsafe Vue asset: {reference}")
    return references


def run_self_check(require_bundled: bool = True) -> dict:
    assets = verify_web_assets(Path(__file__).parent / "web")
    logger = logging.getLogger("videomerge-self-check")
    if require_bundled:
        extension = ".exe" if platform.system() == "Windows" else ""
        paths = [_bundled_binary(name + extension) for name in ("ffmpeg", "ffprobe")]
        if not all(paths):
            raise RuntimeError("Packaged FFmpeg/FFprobe are missing; system tools are not accepted for this check")
        tools = ToolPaths(*paths)
    else:
        tools = resolve_tools(logger, False, default_tools_dir())
    if platform.system() == "Darwin":
        from .architecture import require_macos_architectures
        for binary in (tools.ffmpeg, tools.ffprobe):
            require_macos_architectures(binary, {platform.machine()})
    versions = {}
    for name in ("ffmpeg", "ffprobe"):
        output = subprocess.run([str(getattr(tools, name)), "-version"], capture_output=True, text=True, check=True, timeout=30)
        versions[name] = output.stdout.splitlines()[0]
    with tempfile.TemporaryDirectory(prefix="vmt_smoke_") as directory:
        root = Path(directory)
        first, second, output = root / "01.mp4", root / "02.mp4", root / "merged.mp4"
        subprocess.run([str(tools.ffmpeg), "-hide_banner", "-v", "error", "-nostdin",
                        "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=25:d=1",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(first)],
                       check=True, capture_output=True, timeout=60)
        shutil.copyfile(first, second)
        concat_copy([first, second], output, tools, logger, MergeMode.fast, False, False, expected_duration=2, expected_file_count=2)
        media = probe_file(output, tools, logger)
        if media.duration < 1.9:
            raise RuntimeError("Packaged merge output is incomplete")
    return {"status": "passed", "version": __version__, "system": platform.system(),
            "architecture": platform.machine(), "frozen": bool(getattr(sys, "frozen", False)),
            "assets": assets, "tools": versions, "merged_duration": media.duration}
