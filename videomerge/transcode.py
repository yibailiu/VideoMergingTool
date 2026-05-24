from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .errors import CommandError, ProbeError
from .gpu import GpuPlan, gpu_encoder_quality_args
from .models import Canvas, CodecPlan, ToolPaths, VideoFile
from .probe import probe_file
from .utils import run_command


@dataclass(frozen=True)
class AudioTarget:
    codec: str
    encoder: str
    sample_rate: int
    channels: int
    bitrate: str


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
    temp_root: Path | None = None,
    progress_callback: Callable[[VideoFile], None] | None = None,
) -> tuple[list[Path], tempfile.TemporaryDirectory[str] | None]:
    temp_owner = (
        None
        if keep_temp
        else tempfile.TemporaryDirectory(prefix="videomerge_preprocess_", dir=temp_root)
    )
    temp_dir = Path(temp_owner.name) if temp_owner else Path(tempfile.mkdtemp(prefix="videomerge_preprocess_", dir=temp_root))
    logger.info("Preprocessing temp directory: %s", temp_dir)
    audio_target = choose_audio_target(files, codec_plan)
    logger.info(
        "Audio target: codec=%s sample_rate=%d channels=%d bitrate=%s",
        audio_target.encoder,
        audio_target.sample_rate,
        audio_target.channels,
        audio_target.bitrate,
    )

    outputs: list[Path] = []
    for index, file in enumerate(files, start=1):
        output_path = temp_dir / f"{index:04d}_{file.stem_safe}.mp4"
        processed_path = preprocess_file(
            file=file,
            output_path=output_path,
            canvas=canvas,
            fps=fps,
            codec_plan=codec_plan,
            audio_target=audio_target,
            tools=tools,
            logger=logger,
            pad_color=pad_color,
            crf=crf,
            preset=preset,
            dry_run=dry_run,
            gpu_plan=gpu_plan,
        )
        outputs.append(processed_path)
        if progress_callback:
            progress_callback(file)

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
    audio_target: AudioTarget | None = None,
) -> Path:
    audio_target = audio_target or choose_audio_target([file], codec_plan)
    video_action = choose_video_action(file, canvas, fps, codec_plan)
    audio_action = choose_audio_action(file, audio_target)
    if video_action == "copy" and audio_action == "copy" and _is_concat_safe_source(file):
        logger.info(
            "Preprocess decision: copy original %s | video/audio already match target.",
            file.path.name,
        )
        return file.path

    if video_action == "copy" and audio_action == "copy":
        logger.info("Preprocess decision: remux %s -> %s | codecs already match.", file.path.name, output_path.name)
        remux_copy(file, output_path, tools, logger, dry_run)
        return output_path

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
                f"anullsrc=channel_layout={'mono' if audio_target.channels == 1 else 'stereo'}:sample_rate={audio_target.sample_rate}",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
            ]
        )
        logger.info("Adding silent audio: %s", file.path.name)

    if video_action == "copy":
        args.extend(["-map_metadata", "-1", "-metadata:s:v:0", "rotate=0", "-c:v", "copy"])
    else:
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
                    codec_plan.output_video_encoder,
                    crf,
                    preset,
                    canvas.width,
                    canvas.height,
                    fps,
                ),
                "-pix_fmt",
                "yuv420p",
            ]
        )

    if audio_action == "copy":
        args.extend(["-c:a", "copy"])
    else:
        args.extend(["-c:a", audio_target.encoder, "-b:a", audio_target.bitrate, "-ar", str(audio_target.sample_rate), "-ac", str(audio_target.channels)])
    args.extend(["-shortest", output_path])
    logger.info(
        "Preprocess decision: %s %s -> %s | source=%dx%d display=%dx%d rotation=%d canvas=%s fps=%.3f v=%s a=%s",
        "audio-only" if video_action == "copy" and audio_action != "copy" else "transcode",
        file.path.name,
        output_path.name,
        file.width,
        file.height,
        file.display_width,
        file.display_height,
        file.rotation,
        canvas.label,
        fps,
        "copy" if video_action == "copy" else codec_plan.output_video_encoder,
        "copy" if audio_action == "copy" else f"{audio_target.encoder}/{audio_target.bitrate}",
    )
    run_command(args, logger, dry_run=dry_run)
    if not dry_run:
        validate_preprocessed_output(output_path, file, canvas, tools, logger)
    return output_path


def remux_copy(file: VideoFile, output_path: Path, tools: ToolPaths, logger: logging.Logger, dry_run: bool) -> None:
    args: list[str | Path] = [
        tools.ffmpeg,
        "-y",
        "-hide_banner",
        "-noautorotate",
        "-display_rotation:v:0",
        "0",
        "-i",
        file.path,
        "-map",
        "0:v:0",
    ]
    if file.has_audio:
        args.extend(["-map", "0:a:0"])
    args.extend(["-map_metadata", "-1", "-metadata:s:v:0", "rotate=0", "-c", "copy", output_path])
    run_command(args, logger, dry_run=dry_run)


def choose_video_action(file: VideoFile, canvas: Canvas, fps: float, codec_plan: CodecPlan) -> str:
    if file.rotation != 0:
        return "transcode"
    if file.display_width != canvas.width or file.display_height != canvas.height:
        return "transcode"
    if not _fps_matches(file.frame_rate_float, fps):
        return "transcode"
    if file.pixel_format != "yuv420p":
        return "transcode"
    if _normalize_video_codec(file.video_codec) != _normalize_video_codec(codec_plan.video_codec):
        return "transcode"
    return "copy"


def choose_audio_action(file: VideoFile, audio_target: AudioTarget) -> str:
    if not file.has_audio:
        return "encode"
    if _normalize_audio_codec(file.audio_codec or "") != _normalize_audio_codec(audio_target.codec):
        return "encode"
    if file.audio_sample_rate and file.audio_sample_rate != audio_target.sample_rate:
        return "encode"
    if file.audio_channels and file.audio_channels != audio_target.channels:
        return "encode"
    return "copy"


def choose_audio_target(files: list[VideoFile], codec_plan: CodecPlan) -> AudioTarget:
    with_audio = [file for file in files if file.has_audio]
    sample_rate = _most_common_int([file.audio_sample_rate for file in with_audio if file.audio_sample_rate], 48000)
    channels = _most_common_int([file.audio_channels for file in with_audio if file.audio_channels], 2)
    bitrate = _audio_bitrate(with_audio, channels)
    return AudioTarget(
        codec=codec_plan.audio_codec,
        encoder=codec_plan.output_audio_encoder,
        sample_rate=sample_rate,
        channels=channels,
        bitrate=bitrate,
    )


def _audio_bitrate(files: list[VideoFile], channels: int) -> str:
    bitrates = [file.audio_bitrate for file in files if file.audio_bitrate > 0]
    if bitrates:
        average = int(sum(bitrates) / len(bitrates))
        capped = max(64_000, min(192_000, average))
    else:
        capped = 128_000 if channels <= 2 else 192_000
    if channels == 1:
        capped = min(capped, 96_000)
    return f"{round(capped / 1000)}k"


def _most_common_int(values: list[int], default: int) -> int:
    if not values:
        return default
    return max(sorted(set(values)), key=values.count)


def _fps_matches(source_fps: float, target_fps: float) -> bool:
    if source_fps <= 0 or target_fps <= 0:
        return False
    return abs(source_fps - target_fps) < 0.02


def _is_concat_safe_source(file: VideoFile) -> bool:
    return file.path.suffix.lower() in {".mp4", ".m4v", ".mov"}


def _normalize_video_codec(codec: str) -> str:
    normalized = codec.lower()
    if normalized in {"h264", "avc", "avc1", "libx264"}:
        return "h264"
    if normalized in {"hevc", "h265", "libx265"}:
        return "hevc"
    return normalized


def _normalize_audio_codec(codec: str) -> str:
    normalized = codec.lower()
    if normalized in {"aac", "mp4a"}:
        return "aac"
    if normalized in {"mp3", "libmp3lame"}:
        return "mp3"
    if normalized in {"opus", "libopus"}:
        return "opus"
    if normalized in {"vorbis", "libvorbis"}:
        return "vorbis"
    return normalized


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
