from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from .errors import CommandError, ProbeError
from .models import MergeMode, MergeResult, ToolPaths
from .probe import probe_file
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
    expected_duration: float = 0.0,
    expected_source_size: int = 0,
    expected_file_count: int = 0,
) -> MergeResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="videomerge_concat_", dir=temp_root) as temp_dir:
        logger.info("Concat temp directory: %s", temp_dir)
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

    if not dry_run:
        validate_merged_output(
            output_path,
            tools,
            logger,
            expected_duration=expected_duration,
            expected_source_size=expected_source_size,
            expected_file_count=expected_file_count or len(files),
        )
    logger.info("Output written: %s", output_path)
    return MergeResult(output_path=output_path, files=files, mode=mode)


def validate_merged_output(
    output_path: Path,
    tools: ToolPaths,
    logger: logging.Logger,
    expected_duration: float = 0.0,
    expected_source_size: int = 0,
    expected_file_count: int = 0,
) -> None:
    try:
        output_size = output_path.stat().st_size
    except OSError as exc:
        raise CommandError(f"Merged output was not created: {output_path}: {exc}") from exc
    if output_size <= 0:
        raise CommandError(f"Merged output is empty: {output_path}")

    try:
        media = probe_file(output_path, tools, logger)
    except ProbeError as exc:
        raise CommandError(f"Could not validate merged output {output_path}: {exc}") from exc

    if media.duration <= 0:
        raise CommandError(f"Merged output has no valid duration: {output_path}")
    if expected_duration > 0:
        tolerance = max(1.0, expected_duration * 0.001, max(expected_file_count, 1) * 0.03)
        if media.duration + tolerance < expected_duration:
            raise CommandError(
                f"Merged output appears incomplete: duration={media.duration:.3f}s, "
                f"expected at least {expected_duration - tolerance:.3f}s ({expected_file_count} source files)"
            )

    if expected_source_size > 0:
        allowed_size = int(expected_source_size * 1.15) + 16 * 1024 * 1024
        if output_size > allowed_size:
            raise CommandError(
                f"Merged output exceeds the source-size safety limit: output={output_size} bytes, "
                f"sources={expected_source_size} bytes, limit={allowed_size} bytes"
            )

    logger.info(
        "Validated merged output: %s | duration=%.3fs size=%d bytes source_files=%d",
        output_path.name,
        media.duration,
        output_size,
        expected_file_count,
    )


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
