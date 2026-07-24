from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

import typer

from .adjustments import apply_clockwise_rotation, validate_clockwise_rotation
from .env_check import default_tools_dir, resolve_tools
from .errors import CommandError, DependencyError, VideoMergeError
from .grouping import group_fast, split_by_orientation
from .gpu import GpuMode, apply_gpu_encoder, resolve_gpu_plan
from .logger import setup_logging
from .merge import concat_copy, warn_container_compatibility
from .models import CodecPlan, MergeMode, MergeResult, Orientation, VideoFile
from .naming import SUPPORTED_OUTPUT_FORMATS, auto_name, prepare_output_dir, unique_output_path
from .planning import build_extreme_group_plan, build_optimal_group_plan
from .probe import probe_files
from .scanner import SORT_OPTIONS, VIDEO_EXTENSIONS, scan_video_files, sort_probed_files
from .transcode import preprocess_group

app = typer.Typer(help="Local batch video merging tool powered by FFmpeg.", no_args_is_help=True)


@app.callback()
def root() -> None:
    """Local batch video merging tool powered by FFmpeg."""


@app.command()
def gui() -> None:
    """Launch the desktop GUI."""
    try:
        from .gui import launch_gui

        launch_gui()
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def merge(
    input_dir: Path = typer.Argument(..., help="Directory containing videos to merge."),
    mode: MergeMode = typer.Option(MergeMode.fast, "--mode", "-m", help="Merge mode."),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", "-o", help="Output directory."),
    output_format: str = typer.Option("mp4", "--output-format", help="mp4, mkv, mov, avi, ts, webm."),
    name: Optional[str] = typer.Option(None, "--name", help="Custom output filename without extension."),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive", help="Scan subdirectories."),
    sort_by: str = typer.Option("name-natural-asc", "--sort-by", help="Merge order: name-natural-asc, name-natural-desc, name-asc, name-desc, media-created-asc, media-created-desc, size-asc, size-desc."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing output files."),
    keep_temp: bool = typer.Option(False, "--keep-temp", help="Keep temporary preprocessed files."),
    temp_dir: Optional[Path] = typer.Option(None, "--temp-dir", help="Directory used for temporary preprocessing and concat files."),
    log_file: Optional[Path] = typer.Option(None, "--log-file", help="Write detailed logs to this file."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print actions without running FFmpeg."),
    pad_color: str = typer.Option("black", "--pad-color", help="Padding color used for transcode modes."),
    fps_policy: str = typer.Option("majority", "--fps-policy", help="majority, max, or min."),
    resolution_policy: str = typer.Option("dominant", "--resolution-policy", help="dominant or largest."),
    video_codec: Optional[str] = typer.Option(None, "--video-codec", help="Override target video codec."),
    audio_codec: Optional[str] = typer.Option(None, "--audio-codec", help="Override target audio codec."),
    quality_profile: str = typer.Option("balanced", "--quality-profile", help="Quality profile: balanced, high, or small."),
    crf: Optional[int] = typer.Option(None, "--crf", min=0, max=51, help="Video CRF for transcode modes. Overrides --quality-profile."),
    preset: Optional[str] = typer.Option(None, "--preset", help="FFmpeg encoder preset. Overrides --quality-profile."),
    gpu: GpuMode = typer.Option(GpuMode.off, "--gpu", help="GPU acceleration: off, auto, nvenc, qsv, amf, videotoolbox."),
    gpu_workers: int = typer.Option(1, "--gpu-workers", min=1, max=3, help="Concurrent GPU transcode jobs (1-3)."),
    ffmpeg_path: Optional[Path] = typer.Option(None, "--ffmpeg-path", help="Explicit ffmpeg path."),
    ffprobe_path: Optional[Path] = typer.Option(None, "--ffprobe-path", help="Explicit ffprobe path."),
    selected_files: Optional[Path] = typer.Option(
        None,
        "--selected-files",
        help="JSON file containing the selected source video paths. Used by the GUI.",
    ),
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
        _validate_cli(input_dir, output_format, fps_policy, resolution_policy, sort_by, quality_profile, temp_dir)
        quality = _resolve_quality_settings(quality_profile, crf, preset)
        logger.info("Quality profile: %s | crf=%d preset=%s", quality_profile, quality["crf"], quality["preset"])
        out_dir = prepare_output_dir(input_dir, output_dir)
        if temp_dir:
            temp_dir.mkdir(parents=True, exist_ok=True)
        tools = resolve_tools(
            logger=logger,
            auto_download=auto_download_deps,
            tools_dir=default_tools_dir(),
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
        )

        manual_rotations: dict[Path, int] = {}
        if selected_files:
            paths, manual_rotations = _load_selected_video_manifest(selected_files, input_dir)
            logger.info("Loaded %d selected video file(s) from %s", len(paths), selected_files)
        else:
            paths = scan_video_files(input_dir, recursive=recursive, sort_by=sort_by)
            logger.info("Scanned %d candidate video files from %s using sort=%s", len(paths), input_dir, sort_by)
        if not paths:
            raise VideoMergeError("No recognized video files found.")

        media_files, failures = probe_files(paths, tools, logger)
        if not selected_files:
            media_files = sort_probed_files(media_files, input_dir, sort_by)
        elif manual_rotations:
            media_files = [
                apply_clockwise_rotation(file, manual_rotations.get(file.path.resolve(), 0))
                for file in media_files
            ]
            for file in media_files:
                clockwise_rotation = manual_rotations.get(file.path.resolve(), 0)
                if clockwise_rotation:
                    logger.info(
                        "Manual adjustment: %s | clockwise=%d effective_rotation=%d display=%dx%d orientation=%s",
                        file.path.name,
                        clockwise_rotation,
                        file.rotation,
                        file.display_width,
                        file.display_height,
                        file.orientation.value,
                    )
        if failures:
            for path, reason in failures.items():
                logger.warning("Probe failure: %s | %s", path, reason)
        if not media_files:
            raise VideoMergeError("No readable video files found.")
        if mode == MergeMode.fast and any(manual_rotations.values()):
            raise VideoMergeError(
                "Manual rotation requires Optimal or Extreme mode; Fast mode only performs stream copy."
            )
        progress = ProgressReporter(total_units=_estimate_progress_units(mode, media_files), logger=logger)
        progress.advance(0, "analysis complete")

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
                temp_dir=temp_dir,
                progress=progress,
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
                resolution_policy=resolution_policy,
                video_codec=video_codec,
                audio_codec=audio_codec,
                crf=int(quality["crf"]),
                preset=str(quality["preset"]),
                gpu=gpu,
                gpu_workers=gpu_workers,
                temp_dir=temp_dir,
                progress=progress,
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
                crf=int(quality["crf"]),
                preset=str(quality["preset"]),
                gpu=gpu,
                gpu_workers=gpu_workers,
                temp_dir=temp_dir,
                progress=progress,
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


class ProgressReporter:
    def __init__(self, total_units: int, logger: logging.Logger) -> None:
        self.total_units = max(total_units, 1)
        self.completed_units = 0
        self.logger = logger

    def advance(self, units: int, message: str) -> None:
        self.completed_units = min(self.total_units, self.completed_units + max(units, 0))
        percent = int(round((self.completed_units / self.total_units) * 100))
        self.logger.info("Progress: %d/%d (%d%%) %s", self.completed_units, self.total_units, percent, message)


def _estimate_progress_units(mode: MergeMode, media_files: list[VideoFile]) -> int:
    if mode == MergeMode.fast:
        return sum(len(files) for files in group_fast(media_files).values() if len(files) > 1)
    if mode == MergeMode.optimal:
        groups = split_by_orientation(media_files)
        output_count = sum(1 for orientation in (Orientation.landscape, Orientation.portrait) if groups.get(orientation))
        return len(media_files) + output_count
    return len(media_files) + 1


def _validate_cli(
    input_dir: Path,
    output_format: str,
    fps_policy: str,
    resolution_policy: str,
    sort_by: str,
    quality_profile: str,
    temp_dir: Path | None = None,
) -> None:
    if not input_dir.exists():
        raise VideoMergeError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise VideoMergeError(f"Input path is not a directory: {input_dir}")
    if output_format not in SUPPORTED_OUTPUT_FORMATS:
        raise VideoMergeError(f"Unsupported output format: {output_format}")
    if fps_policy not in {"majority", "max", "min"}:
        raise VideoMergeError("Invalid --fps-policy. Use majority, max, or min.")
    if resolution_policy not in {"dominant", "largest"}:
        raise VideoMergeError("Invalid --resolution-policy. Use dominant or largest.")
    if sort_by not in SORT_OPTIONS:
        raise VideoMergeError(f"Invalid --sort-by. Use one of: {', '.join(sorted(SORT_OPTIONS))}.")
    if quality_profile not in {"balanced", "high", "small"}:
        raise VideoMergeError("Invalid --quality-profile. Use balanced, high, or small.")
    if temp_dir and temp_dir.exists() and not temp_dir.is_dir():
        raise VideoMergeError(f"Temp path is not a directory: {temp_dir}")


def _resolve_quality_settings(quality_profile: str, crf: int | None, preset: str | None) -> dict[str, object]:
    defaults = {
        "high": {"crf": 20, "preset": "slow"},
        "balanced": {"crf": 23, "preset": "medium"},
        "small": {"crf": 25, "preset": "medium"},
    }
    selected = defaults[quality_profile].copy()
    if crf is not None:
        selected["crf"] = crf
    if preset is not None:
        selected["preset"] = preset
    return selected


def _load_selected_video_files(selected_files: Path, input_dir: Path) -> list[Path]:
    paths, _manual_rotations = _load_selected_video_manifest(selected_files, input_dir)
    return paths


def _load_selected_video_manifest(
    selected_files: Path,
    input_dir: Path,
) -> tuple[list[Path], dict[Path, int]]:
    if not selected_files.exists():
        raise VideoMergeError(f"Selected file list does not exist: {selected_files}")
    try:
        payload = json.loads(selected_files.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VideoMergeError(f"Selected file list is not readable JSON: {selected_files}") from exc
    if not isinstance(payload, list):
        raise VideoMergeError("Selected file list must be a JSON array.")

    root = input_dir.resolve()
    paths: list[Path] = []
    manual_rotations: dict[Path, int] = {}
    seen: set[Path] = set()
    for item in payload:
        if isinstance(item, str):
            raw_path = item
            clockwise_rotation = 0
        elif isinstance(item, dict):
            raw_path = item.get("path")
            if not isinstance(raw_path, str):
                raise VideoMergeError("Selected file entry must contain a string path.")
            try:
                clockwise_rotation = validate_clockwise_rotation(item.get("rotate_clockwise", 0))
            except ValueError as exc:
                raise VideoMergeError(f"Invalid manual rotation for selected file: {raw_path}") from exc
        else:
            raise VideoMergeError("Selected file list entries must be paths or adjustment objects.")
        path = Path(raw_path).expanduser().resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise VideoMergeError(f"Selected file is outside the input directory: {path}") from exc
        if path in seen:
            continue
        if not path.is_file():
            raise VideoMergeError(f"Selected video file does not exist: {path}")
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            raise VideoMergeError(f"Selected file is not a supported video format: {path}")
        seen.add(path)
        paths.append(path)
        if clockwise_rotation:
            manual_rotations[path] = clockwise_rotation
    return paths, manual_rotations


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
    temp_dir: Path | None,
    progress: ProgressReporter,
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
        result = concat_copy(
            files=[file.path for file in files],
            output_path=output_path,
            tools=tools,
            logger=logger,
            mode=MergeMode.fast,
            overwrite=overwrite,
            dry_run=dry_run,
            temp_root=temp_dir,
            expected_duration=sum(file.duration for file in files),
            expected_source_size=_source_total_size(files),
            expected_file_count=len(files),
        )
        results.append(result)
        progress.advance(len(files), f"merged fast group {index}")
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
    resolution_policy: str,
    video_codec: str | None,
    audio_codec: str | None,
    crf: int,
    preset: str,
    gpu: GpuMode,
    gpu_workers: int,
    temp_dir: Path | None,
    progress: ProgressReporter,
) -> list[MergeResult]:
    logger.info("Mode: optimal. Files will be split into landscape and portrait outputs.")
    groups = split_by_orientation(media_files)
    results: list[MergeResult] = []
    temp_owners = []

    for orientation in (Orientation.landscape, Orientation.portrait):
        files = groups.get(orientation, [])
        if not files:
            logger.info("No %s videos found; skipping that output.", orientation.value)
            continue
        plan = build_optimal_group_plan(
            files,
            output_format=output_format,
            requested_video_codec=video_codec,
            requested_audio_codec=audio_codec,
            fps_policy=fps_policy,
            resolution_policy=resolution_policy,
        )
        profile = plan.profile
        codec_plan = plan.codec_plan
        gpu_plan = resolve_gpu_plan(tools, gpu, codec_plan.video_codec, logger)
        codec_plan = apply_gpu_encoder(codec_plan, gpu_plan)
        canvas = plan.canvas
        fps = plan.fps
        logger.info(
            "Optimal target: orientation=%s canvas=%s fps=%.3f video=%s audio=%s "
            "reference_files=%d reference_bitrate=%dkbps resolution_policy=%s",
            orientation.value,
            canvas.label,
            fps,
            codec_plan.video_codec,
            codec_plan.audio_codec,
            len(profile.files),
            round(profile.video_bitrate / 1000),
            resolution_policy,
        )
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
            gpu_plan=gpu_plan,
            temp_root=temp_dir,
            progress_callback=lambda file: progress.advance(1, f"preprocessed {file.path.name}"),
            reference_files=profile.files,
            target_video_bitrate=profile.video_bitrate,
            gpu_workers=gpu_workers,
        )
        if owner:
            temp_owners.append(owner)
        base_name = name or auto_name(input_dir.name, orientation.value, canvas.label)
        if name and len(groups) > 1:
            base_name = f"{name}_{orientation.value}"
        output_path = unique_output_path(output_dir, base_name, output_format, overwrite)
        results.append(
            concat_copy(
                preprocessed,
                output_path,
                tools,
                logger,
                MergeMode.optimal,
                overwrite,
                dry_run,
                temp_dir,
                expected_duration=sum(file.duration for file in files),
                expected_source_size=_source_total_size(files),
                expected_file_count=len(files),
            )
        )
        progress.advance(1, f"merged {orientation.value} output")

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
    gpu: GpuMode,
    gpu_workers: int,
    temp_dir: Path | None,
    progress: ProgressReporter,
) -> list[MergeResult]:
    logger.info("Mode: extreme. All files will be normalized into one output.")
    plan = build_extreme_group_plan(
        media_files,
        output_format=output_format,
        requested_video_codec=video_codec,
        requested_audio_codec=audio_codec,
        fps_policy=fps_policy,
    )
    codec_plan = plan.codec_plan
    gpu_plan = resolve_gpu_plan(tools, gpu, codec_plan.video_codec, logger)
    codec_plan = apply_gpu_encoder(codec_plan, gpu_plan)
    canvas = plan.canvas
    fps = plan.fps
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
        gpu_plan=gpu_plan,
        temp_root=temp_dir,
        progress_callback=lambda file: progress.advance(1, f"preprocessed {file.path.name}"),
        target_video_bitrate=plan.profile.video_bitrate,
        gpu_workers=gpu_workers,
    )
    base_name = name or auto_name(input_dir.name, "extreme", canvas.label)
    output_path = unique_output_path(output_dir, base_name, output_format, overwrite)
    result = concat_copy(
        preprocessed,
        output_path,
        tools,
        logger,
        MergeMode.extreme,
        overwrite,
        dry_run,
        temp_dir,
        expected_duration=sum(file.duration for file in media_files),
        expected_source_size=_source_total_size(media_files),
        expected_file_count=len(media_files),
    )
    progress.advance(1, "merged extreme output")
    _cleanup_temp_owners([owner] if owner else [], logger)
    return [result]


def _source_total_size(files: list[VideoFile]) -> int:
    total = 0
    for file in files:
        try:
            total += file.path.stat().st_size
        except OSError:
            return 0
    return total


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


def _default_transcode_video_codec(output_format: str) -> str:
    if output_format == "webm":
        return "vp9"
    return "h264"


def _cleanup_temp_owners(owners: list[object], logger: logging.Logger) -> None:
    for owner in owners:
        try:
            owner.cleanup()
            logger.debug("Temporary directory cleaned.")
        except Exception as exc:  # pragma: no cover - cleanup errors depend on OS state.
            logger.warning("Temporary cleanup failed: %s", exc)
