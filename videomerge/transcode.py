from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from .errors import CommandError, ProbeError
from .gpu import GpuPlan, gpu_encoder_quality_args
from .models import Canvas, CodecPlan, ToolPaths, VideoFile
from .probe import probe_file
from .utils import run_command


def preprocess_group(
    files: list[VideoFile],
    canvas: Canvas,
    fps: float,
    codec_plan: CodecPlan,
    tools: ToolPaths,
    logger: logging.Logger,
    pad_color: str,
    crf: int,
    preset: str,
    keep_temp: bool,
    dry_run: bool,
    gpu_plan: GpuPlan | None = None,
) -> tuple[list[Path], tempfile.TemporaryDirectory[str] | None]:
    temp_owner = None if keep_temp else tempfile.TemporaryDirectory(prefix="videomerge_preprocess_")
    temp_dir = Path(temp_owner.name) if temp_owner else Path(tempfile.mkdtemp(prefix="videomerge_preprocess_"))
    logger.info("Preprocessing temp directory: %s", temp_dir)

    outputs: list[Path] = []
    for index, file in enumerate(files, start=1):
        output_path = temp_dir / f"{index:04d}_{file.stem_safe}.mp4"
        preprocess_file(
            file=file,
            output_path=output_path,
            canvas=canvas,
            fps=fps,
            codec_plan=codec_plan,
            tools=tools,
            logger=logger,
            pad_color=pad_color,
            crf=crf,
            preset=preset,
            dry_run=dry_run,
            gpu_plan=gpu_plan,
        )
        outputs.append(output_path)

    if keep_temp:
        logger.info("Keeping temp files in %s", temp_dir)
        return outputs, None
    return outputs, temp_owner


def preprocess_file(
    file: VideoFile,
    output_path: Path,
    canvas: Canvas,
    fps: float,
    codec_plan: CodecPlan,
    tools: ToolPaths,
    logger: logging.Logger,
    pad_color: str,
    crf: int,
    preset: str,
    dry_run: bool,
    gpu_plan: GpuPlan | None = None,
) -> None:
    video_filter = build_video_filter(file.rotation, canvas, fps, pad_color)
    args: list[str | Path] = [
        tools.ffmpeg,
        "-y",
        "-hide_banner",
        "-noautorotate",
        "-display_rotation:v:0",
        "0",
        "-i",
        file.path,
    ]

    if file.has_audio:
        args.extend(
            [
                "-map",
                "0:v:0",
                "-map",
                "0:a:0",
            ]
        )
    else:
        duration = max(file.duration, 0.1)
        args.extend(
            [
                "-f",
                "lavfi",
                "-t",
                f"{duration:.3f}",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
            ]
        )
        logger.info("Adding silent audio: %s", file.path.name)

    args.extend(
        [
            "-vf",
            video_filter,
            "-map_metadata",
            "-1",
            "-metadata:s:v:0",
            "rotate=0",
            "-c:v",
            codec_plan.output_video_encoder,
            *gpu_encoder_quality_args(
                codec_plan.output_video_encoder if gpu_plan and gpu_plan.enabled else None,
                crf,
                preset,
                canvas.width,
                canvas.height,
                fps,
            ),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            codec_plan.output_audio_encoder,
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            output_path,
        ]
    )
    logger.info(
        "Preprocess %s -> %s | source=%dx%d display=%dx%d rotation=%d canvas=%s fps=%.3f v=%s a=%s",
        file.path.name,
        output_path.name,
        file.width,
        file.height,
        file.display_width,
        file.display_height,
        file.rotation,
        canvas.label,
        fps,
        codec_plan.output_video_encoder,
        codec_plan.output_audio_encoder,
    )
    run_command(args, logger, dry_run=dry_run)
    if not dry_run:
        validate_preprocessed_output(output_path, file, canvas, tools, logger)


def build_video_filter(rotation: int, canvas: Canvas, fps: float, pad_color: str) -> str:
    filters: list[str] = []
    if rotation == 90:
        filters.append("transpose=2")
    elif rotation == 270:
        filters.append("transpose=1")
    elif rotation == 180:
        filters.append("transpose=2,transpose=2")

    filters.extend(
        [
            f"scale=w={canvas.width}:h={canvas.height}:force_original_aspect_ratio=decrease",
            f"pad={canvas.width}:{canvas.height}:(ow-iw)/2:(oh-ih)/2:color={pad_color}",
            "setsar=1",
            f"fps={fps:.3f}",
        ]
    )
    return ",".join(filters)


def validate_preprocessed_output(
    output_path: Path,
    source_file: VideoFile,
    canvas: Canvas,
    tools: ToolPaths,
    logger: logging.Logger,
) -> None:
    try:
        media = probe_file(output_path, tools, logger)
    except ProbeError as exc:
        raise CommandError(f"Could not validate preprocessed file {output_path}: {exc}") from exc

    if media.rotation != 0:
        raise CommandError(
            f"Preprocessed file still has rotation metadata: {source_file.path.name} -> "
            f"{output_path} rotation={media.rotation}"
        )
    if media.display_width != canvas.width or media.display_height != canvas.height:
        raise CommandError(
            f"Preprocessed file display size mismatch: {source_file.path.name} -> {output_path} "
            f"display={media.display_width}x{media.display_height}, expected={canvas.label}"
        )

    logger.info(
        "Validated preprocessed output: %s | display=%dx%d rotation=%d",
        output_path.name,
        media.display_width,
        media.display_height,
        media.rotation,
    )
