from __future__ import annotations

import logging
import tempfile
import os
import uuid
import sys
from pathlib import Path

from .errors import CommandError, ProbeError, NoUsableInputs
from .models import MergeMode, MergeResult, ToolPaths
from .probe import probe_file
from .utils import FFMPEG_RUNTIME_ARGS, run_command, write_concat_list


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
    from .reliability import current_run, is_system_failure
    task_run = current_run.get()
    if not files:
        raise NoUsableInputs("No successful input files remain for merging.")
    # Commit the result only after validation. Existing destinations survive failures.
    staging = output_path.with_name(f".{output_path.stem}.{uuid.uuid4().hex}.partial{output_path.suffix}")
    logger.info("Staging output: %s", staging)
    inputs = list(files)
    try:
        while True:
            known = [task_run.sources.get(path) for path in inputs] if task_run else []
            if known and all(known):
                expected_duration = sum(file.duration for file in known)
                expected_file_count = len(known)
                expected_source_size = sum(file.path.stat().st_size for file in known)
            try:
                _concat_copy_once(inputs, staging, tools, logger, mode, True, dry_run,
                                           temp_root, expected_duration, expected_source_size, expected_file_count)
                break
            except CommandError as exc:
                if not task_run or task_run.policy != "skip" or is_system_failure(str(exc)):
                    raise
                bad = []
                for path in inputs:
                    source = task_run.sources.get(path)
                    if source and task_run.recover_input(source, tools, exc):
                        bad.append(path)
                if not bad:
                    raise  # A muxer/target error must never be disguised as a bad input.
                inputs = [path for path in inputs if path not in bad]
                if not inputs:
                    raise NoUsableInputs("All input files failed integrity checks.") from exc
                logger.warning("Retrying concat after excluding %d confirmed bad input(s).", len(bad))
        if not dry_run:
            if overwrite:
                os.replace(staging, output_path)
            else:
                _publish_no_replace(staging, output_path)
        if task_run and not dry_run:
            task_run.outputs.append(str(output_path))
            task_run.emit()
        logger.info("Planned output: %s" if dry_run else "Output written: %s", output_path)
        source_paths = [task_run.sources[path].path if task_run and path in task_run.sources else path for path in inputs]
        return MergeResult(output_path, source_paths, mode)
    finally:
        staging.unlink(missing_ok=True)


def _publish_no_replace(source: Path, destination: Path) -> None:
    """Use exclusive rename where available, including volumes without hard links."""
    if os.name == "nt":
        os.rename(source, destination)  # Windows rename refuses an existing target.
        return
    import ctypes
    import errno
    libc = ctypes.CDLL(None, use_errno=True)
    result = None
    if sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = rename(os.fsencode(source), os.fsencode(destination), 0x4)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1)  # AT_FDCWD, RENAME_NOREPLACE
    if result == 0:
        return
    if result is not None:
        error = ctypes.get_errno()
        if error not in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
            raise OSError(error, os.strerror(error), str(destination))
    os.link(source, destination)
    source.unlink()


def _concat_copy_once(
    files: list[Path], output_path: Path, tools: ToolPaths, logger: logging.Logger,
    mode: MergeMode, overwrite: bool, dry_run: bool, temp_root: Path | None,
    expected_duration: float, expected_source_size: int, expected_file_count: int,
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
            *FFMPEG_RUNTIME_ARGS,
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
            output_path.unlink(missing_ok=True)
            raise CommandError(
                f"Merged output appears incomplete: duration={media.duration:.3f}s, "
                f"expected at least {expected_duration - tolerance:.3f}s ({expected_file_count} source files)"
            )

    if expected_source_size > 0:
        allowed_size = int(expected_source_size * 1.15) + 16 * 1024 * 1024
        if output_size > allowed_size:
            output_path.unlink(missing_ok=True)
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
