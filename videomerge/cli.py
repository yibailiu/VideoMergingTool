from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import typer

from .env_check import resolve_tools
from .errors import CommandError, DependencyError, VideoMergeError
from .grouping import choose_canvas, choose_fps, group_fast, majority_codec_plan, split_by_orientation
from .logger import setup_logging
from .merge import concat_copy, warn_container_compatibility
from .models import CodecPlan, MergeMode, MergeResult, Orientation, VideoFile
from .naming import SUPPORTED_OUTPUT_FORMATS, auto_name, prepare_output_dir, unique_output_path
from .probe import probe_files
from .scanner import scan_video_files
from .transcode import preprocess_group

app = typer.Typer(help="Local batch video merging tool powered by FFmpeg.", no_args_is_help=True)


@app.callback()
def root() -> None:
    """Local batch video merging tool powered by FFmpeg."""


@app.command()
def merge(
    input_dir: Path = typer.Argument(..., help="Directory containing videos to merge."),
    mode: MergeMode = typer.Option(MergeMode.fast, "--mode", "-m", help="Merge mode."),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", "-o", help="Output directory."),
    output_format: str = typer.Option("mp4", "--output-format", help="mp4, mkv, mov, avi, ts, webm."),
    name: Optional[str] = typer.Option(None, "--name", help="Custom output filename without extension."),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive", help="Scan subdirectories."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing output files."),
    keep_temp: bool = typer.Option(False, "--keep-temp", help="Keep temporary preprocessed files."),
    log_file: Optional[Path] = typer.Option(None, "--log-file", help="Write detailed logs to this file."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print actions without running FFmpeg."),
    pad_color: str = typer.Option("black", "--pad-color", help="Padding color used for transcode modes."),
    fps_policy: str = typer.Option("majority", "--fps-policy", help="majority, max, or min."),
    resolution_policy: str = typer.Option("largest", "--resolution-policy", help="Currently supports largest."),
    video_codec: Optional[str] = typer.Option(None, "--video-codec", help="Override target video codec."),
    audio_codec: Optional[str] = typer.Option(None, "--audio-codec", help="Override target audio codec."),
    crf: int = typer.Option(20, "--crf", min=0, max=51, help="Video CRF for transcode modes."),
    preset: str = typer.Option("medium", "--preset", help="FFmpeg encoder preset."),
    ffmpeg_path: Optional[Path] = typer.Option(None, "--ffmpeg-path", help="Explicit ffmpeg path."),
    ffprobe_path: Optional[Path] = typer.Option(None, "--ffprobe-path", help="Explicit ffprobe path."),
    auto_download_deps: bool = typer.Option(
        True,
        "--auto-download-deps/--no-auto-download-deps",
        help="Automatically download ffmpeg/ffprobe if missing.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose console logs."),
) -> None:
    started = time.perf_counter()
    output_format = output_format.lower().lstrip(".")
    logger = setup_logging(log_file=log_file, verbose=verbose)

    try:
        _validate_cli(input_dir, output_format, fps_policy, resolution_policy)
        out_dir = prepare_output_dir(input_dir, output_dir)
        tools = resolve_tools(
            logger=logger,
            auto_download=auto_download_deps,
            tools_dir=Path.cwd() / ".tools" / "ffmpeg",
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
        )

        paths = scan_video_files(input_dir, recursive=recursive)
        logger.info("Scanned %d candidate video files from %s", len(paths), input_dir)
        if not paths:
            raise VideoMergeError("No recognized video files found.")

        media_files, failures = probe_files(paths, tools, logger)
        if failures:
            for path, reason in failures.items():
                logger.warning("Probe failure: %s | %s", path, reason)
        if not media_files:
            raise VideoMergeError("No readable video files found.")

        if mode == MergeMode.fast:
            results = _run_fast(
                media_files=media_files,
                input_dir=input_dir,
                output_dir=out_dir,
                output_format=output_format,
                name=name,
                tools=tools,
                logger=logger,
                overwrite=overwrite,
                dry_run=dry_run,
            )
        elif mode == MergeMode.optimal:
            results = _run_optimal(
                media_files=media_files,
                input_dir=input_dir,
                output_dir=out_dir,
                output_format=output_format,
                name=name,
                tools=tools,
                logger=logger,
                overwrite=overwrite,
                dry_run=dry_run,
                keep_temp=keep_temp,
                pad_color=pad_color,
                fps_policy=fps_policy,
                video_codec=video_codec,
                audio_codec=audio_codec,
                crf=crf,
                preset=preset,
            )
        else:
            results = _run_extreme(
                media_files=media_files,
                input_dir=input_dir,
                output_dir=out_dir,
                output_format=output_format,
                name=name,
                tools=tools,
                logger=logger,
                overwrite=overwrite,
                dry_run=dry_run,
                keep_temp=keep_temp,
                pad_color=pad_color,
                fps_policy=fps_policy,
                video_codec=video_codec,
                audio_codec=audio_codec,
                crf=crf,
                preset=preset,
            )

        if not results:
            raise VideoMergeError("No outputs were produced. Check skip reasons in the log.")

        _log_merge_summary(
            total_video_count=len(paths),
            merged_video_count=sum(len(result.files) for result in results),
            logger=logger,
        )
        logger.info("Completed %d output file(s):", len(results))
        for result in results:
            logger.info("  %s", result.output_path)
    except (VideoMergeError, DependencyError, CommandError) as exc:
        logger.error("%s", exc)
        raise typer.Exit(code=1) from exc
    finally:
        elapsed = time.perf_counter() - started
        logger.info("Total runtime: %.2fs", elapsed)


def _validate_cli(input_dir: Path, output_format: str, fps_policy: str, resolution_policy: str) -> None:
    if not input_dir.exists():
        raise VideoMergeError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise VideoMergeError(f"Input path is not a directory: {input_dir}")
    if output_format not in SUPPORTED_OUTPUT_FORMATS:
        raise VideoMergeError(f"Unsupported output format: {output_format}")
    if fps_policy not in {"majority", "max", "min"}:
        raise VideoMergeError("Invalid --fps-policy. Use majority, max, or min.")
    if resolution_policy != "largest":
        raise VideoMergeError("Only --resolution-policy largest is currently supported.")


def _log_merge_summary(total_video_count: int, merged_video_count: int, logger: logging.Logger) -> None:
    unmerged_video_count = max(total_video_count - merged_video_count, 0)
    logger.info(
        "Summary: directory contains %d video(s), %d video(s) were merged, %d video(s) were not merged.",
        total_video_count,
        merged_video_count,
        unmerged_video_count,
    )


def _run_fast(
    media_files: list[VideoFile],
    input_dir: Path,
    output_dir: Path,
    output_format: str,
    name: str | None,
    tools,
    logger: logging.Logger,
    overwrite: bool,
    dry_run: bool,
) -> list[MergeResult]:
    logger.info("Mode: fast. Stream copy only; no transcoding will be performed.")
    groups = group_fast(media_files)
    results: list[MergeResult] = []
    for index, (key, files) in enumerate(groups.items(), start=1):
        logger.info("Fast group %d: %d file(s) | %s", index, len(files), key)
        if len(files) < 2:
            logger.warning("Skipping %s: no compatible peer for stream-copy concat.", files[0].path)
            continue
        resolution = f"{key.width}x{key.height}"
        base_name = name or auto_name(input_dir.name, f"fast_{index}", resolution)
        if name and len(groups) > 1:
            base_name = f"{name}_{index}"
        output_path = unique_output_path(output_dir, base_name, output_format, overwrite)
        results.append(
            concat_copy(
                files=[file.path for file in files],
                output_path=output_path,
                tools=tools,
                logger=logger,
                mode=MergeMode.fast,
                overwrite=overwrite,
                dry_run=dry_run,
            )
        )
    return results


def _run_optimal(
    media_files: list[VideoFile],
    input_dir: Path,
    output_dir: Path,
    output_format: str,
    name: str | None,
    tools,
    logger: logging.Logger,
    overwrite: bool,
    dry_run: bool,
    keep_temp: bool,
    pad_color: str,
    fps_policy: str,
    video_codec: str | None,
    audio_codec: str | None,
    crf: int,
    preset: str,
) -> list[MergeResult]:
    logger.info("Mode: optimal. Files will be split into landscape and portrait outputs.")
    codec_plan = _container_adjusted_plan(
        majority_codec_plan(media_files, video_codec, audio_codec),
        output_format,
        logger,
    )
    logger.info("Target codecs by file-count majority: video=%s audio=%s", codec_plan.video_codec, codec_plan.audio_codec)
    groups = split_by_orientation(media_files)
    results: list[MergeResult] = []
    temp_owners = []

    for orientation in (Orientation.landscape, Orientation.portrait):
        files = groups.get(orientation, [])
        if not files:
            logger.info("No %s videos found; skipping that output.", orientation.value)
            continue
        canvas = choose_canvas(files)
        fps = choose_fps(files, fps_policy)
        warn_container_compatibility(output_format, codec_plan.output_video_encoder, codec_plan.output_audio_encoder, logger)
        preprocessed, owner = preprocess_group(
            files=files,
            canvas=canvas,
            fps=fps,
            codec_plan=codec_plan,
            tools=tools,
            logger=logger,
            pad_color=pad_color,
            crf=crf,
            preset=preset,
            keep_temp=keep_temp,
            dry_run=dry_run,
        )
        if owner:
            temp_owners.append(owner)
        base_name = name or auto_name(input_dir.name, orientation.value, canvas.label)
        if name and len(groups) > 1:
            base_name = f"{name}_{orientation.value}"
        output_path = unique_output_path(output_dir, base_name, output_format, overwrite)
        results.append(
            concat_copy(preprocessed, output_path, tools, logger, MergeMode.optimal, overwrite, dry_run)
        )

    _cleanup_temp_owners(temp_owners, logger)
    return results


def _run_extreme(
    media_files: list[VideoFile],
    input_dir: Path,
    output_dir: Path,
    output_format: str,
    name: str | None,
    tools,
    logger: logging.Logger,
    overwrite: bool,
    dry_run: bool,
    keep_temp: bool,
    pad_color: str,
    fps_policy: str,
    video_codec: str | None,
    audio_codec: str | None,
    crf: int,
    preset: str,
) -> list[MergeResult]:
    logger.info("Mode: extreme. All files will be normalized into one output.")
    codec_plan = _container_adjusted_plan(
        majority_codec_plan(media_files, video_codec, audio_codec),
        output_format,
        logger,
    )
    canvas = choose_canvas(media_files)
    fps = choose_fps(media_files, fps_policy)
    logger.info(
        "Extreme target: canvas=%s fps=%.3f video=%s audio=%s",
        canvas.label,
        fps,
        codec_plan.video_codec,
        codec_plan.audio_codec,
    )
    warn_container_compatibility(output_format, codec_plan.output_video_encoder, codec_plan.output_audio_encoder, logger)
    preprocessed, owner = preprocess_group(
        files=media_files,
        canvas=canvas,
        fps=fps,
        codec_plan=codec_plan,
        tools=tools,
        logger=logger,
        pad_color=pad_color,
        crf=crf,
        preset=preset,
        keep_temp=keep_temp,
        dry_run=dry_run,
    )
    base_name = name or auto_name(input_dir.name, "extreme", canvas.label)
    output_path = unique_output_path(output_dir, base_name, output_format, overwrite)
    result = concat_copy(preprocessed, output_path, tools, logger, MergeMode.extreme, overwrite, dry_run)
    _cleanup_temp_owners([owner] if owner else [], logger)
    return [result]


def _container_adjusted_plan(plan: CodecPlan, output_format: str, logger: logging.Logger) -> CodecPlan:
    if output_format == "webm":
        if plan.output_video_encoder not in {"libvpx", "libvpx-vp9", "libaom-av1"}:
            logger.warning("Switching target video encoder to VP9 for webm compatibility.")
            video_codec = "vp9"
            video_encoder = "libvpx-vp9"
        else:
            video_codec = plan.video_codec
            video_encoder = plan.output_video_encoder
        if plan.output_audio_encoder not in {"libopus", "libvorbis"}:
            logger.warning("Switching target audio encoder to Opus for webm compatibility.")
            audio_codec = "opus"
            audio_encoder = "libopus"
        else:
            audio_codec = plan.audio_codec
            audio_encoder = plan.output_audio_encoder
        return CodecPlan(video_codec, audio_codec, video_encoder, audio_encoder)
    return plan


def _cleanup_temp_owners(owners: list[object], logger: logging.Logger) -> None:
    for owner in owners:
        try:
            owner.cleanup()
            logger.debug("Temporary directory cleaned.")
        except Exception as exc:  # pragma: no cover - cleanup errors depend on OS state.
            logger.warning("Temporary cleanup failed: %s", exc)
