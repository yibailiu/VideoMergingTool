from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from .models import MergeMode, MergeResult, ToolPaths
from .utils import run_command, write_concat_list


def concat_copy(
    files: list[Path],
    output_path: Path,
    tools: ToolPaths,
    logger: logging.Logger,
    mode: MergeMode,
    overwrite: bool,
    dry_run: bool,
    temp_root: Path | None = None,
) -> MergeResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="videomerge_concat_", dir=temp_root) as temp_dir:
        list_path = Path(temp_dir) / "concat.txt"
        write_concat_list(files, list_path)
        logger.info("Merge order:")
        for index, file in enumerate(files, start=1):
            logger.info("  %03d. %s", index, file)

        args = [
            tools.ffmpeg,
            "-y" if overwrite else "-n",
            "-hide_banner",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            list_path,
            "-c",
            "copy",
            output_path,
        ]
        run_command(args, logger, dry_run=dry_run)

    logger.info("Output written: %s", output_path)
    return MergeResult(output_path=output_path, files=files, mode=mode)


def warn_container_compatibility(
    output_format: str,
    video_encoder: str,
    audio_encoder: str,
    logger: logging.Logger,
) -> None:
    fmt = output_format.lower()
    if fmt == "webm":
        if video_encoder not in {"libvpx", "libvpx-vp9", "libaom-av1"}:
            logger.warning("webm usually requires VP8/VP9/AV1 video; requested encoder is %s.", video_encoder)
        if audio_encoder not in {"libopus", "libvorbis"}:
            logger.warning("webm usually requires Opus/Vorbis audio; requested encoder is %s.", audio_encoder)
    if fmt == "mp4":
        if video_encoder in {"libvpx", "libvpx-vp9"}:
            logger.warning("mp4 is not a good container for VP8/VP9; consider webm or mkv.")
        if audio_encoder in {"libvorbis"}:
            logger.warning("mp4 is not a good container for Vorbis; consider mkv or webm.")
