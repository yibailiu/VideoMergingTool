from __future__ import annotations

import logging
import tempfile
import concurrent.futures
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from .errors import CommandError, ProbeError
from .gpu import GpuPlan, gpu_encoder_quality_args
from .merge import concat_copy
from .models import MergeMode
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


@dataclass(frozen=True)
class PreprocessSegment:
    files: list[VideoFile]
    copy_compatible: bool


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
    reference_files: list[VideoFile] | tuple[VideoFile, ...] | None = None,
    target_video_bitrate: int = 0,
    gpu_workers: int = 1,
) -> tuple[list[Path], tempfile.TemporaryDirectory[str] | None]:
    audio_target = choose_audio_target(list(reference_files or files), codec_plan)
    logger.info(
        "Audio target: codec=%s sample_rate=%d channels=%d bitrate=%s",
        audio_target.encoder,
        audio_target.sample_rate,
        audio_target.channels,
        audio_target.bitrate,
    )
    if can_concat_originals(files, canvas, fps, codec_plan, audio_target):
        logger.info("Preprocess decision: copy originals for entire group | all streams are concat-compatible.")
        for file in files:
            if progress_callback:
                progress_callback(file)
        return [file.path for file in files], None

    segments = build_preprocess_segments(files, canvas, fps, codec_plan, audio_target)
    passthrough_signature = choose_passthrough_signature(segments)
    logger.info("Preprocess segmentation: %d segment(s) for %d file(s).", len(segments), len(files))
    if passthrough_signature:
        passthrough_count = sum(
            len(segment.files)
            for segment in segments
            if segment.copy_compatible and _concat_signature(segment.files[0]) == passthrough_signature
        )
        logger.info(
            "Preprocess passthrough: %d ready file(s) match the dominant concat signature and will skip normalization.",
            passthrough_count,
        )
    else:
        passthrough_count = 0
    transcode_files = len(files) - passthrough_count
    transcode_jobs = sum(
        1
        for segment in segments
        if not (
            segment.copy_compatible
            and passthrough_signature is not None
            and _concat_signature(segment.files[0]) == passthrough_signature
        )
    )
    logger.info(
        "Preprocess plan: copy_files=%d transcode_files=%d transcode_jobs=%d gpu_workers=%d.",
        passthrough_count,
        transcode_files,
        transcode_jobs,
        min(max(1, gpu_workers), 3),
    )
    _log_size_estimate(
        files,
        segments,
        passthrough_signature,
        target_video_bitrate
        if gpu_plan is not None and gpu_plan.encoder in {"h264_videotoolbox", "hevc_videotoolbox"}
        else 0,
        audio_target,
        logger,
    )

    temp_owner = (
        None
        if keep_temp
        else tempfile.TemporaryDirectory(prefix="videomerge_preprocess_", dir=temp_root)
    )
    temp_dir = Path(temp_owner.name) if temp_owner else Path(tempfile.mkdtemp(prefix="videomerge_preprocess_", dir=temp_root))
    logger.info("Preprocessing temp directory: %s", temp_dir)
    
    # 预分配数组以确保并发结果按照原始分段顺序插入
    outputs: list[list[Path]] = [[] for _ in segments]

    # 包装单个分段的处理逻辑
    def worker(idx: int, segment: PreprocessSegment) -> tuple[int, list[Path]]:
        output_path = temp_dir / f"{(idx + 1):04d}_{segment.files[0].stem_safe}.mp4"
        if (
            segment.copy_compatible
            and passthrough_signature is not None
            and _concat_signature(segment.files[0]) == passthrough_signature
        ):
            logger.info(
                "Preprocess decision: passthrough %d ready file(s) without temp concat/transcode.",
                len(segment.files),
            )
            processed_paths = [file.path for file in segment.files]
        elif segment.copy_compatible:
            processed_path = preprocess_copy_segment(
                segment=segment, output_path=output_path, temp_dir=temp_dir, index=idx + 1,
                canvas=canvas, fps=fps, codec_plan=codec_plan, audio_target=audio_target,
                tools=tools, logger=logger, pad_color=pad_color, crf=crf, preset=preset,
                dry_run=dry_run, gpu_plan=gpu_plan, target_video_bitrate=target_video_bitrate
            )
            processed_paths = [processed_path]
        else:
            processed_path = preprocess_file(
                file=segment.files[0], output_path=output_path, canvas=canvas, fps=fps,
                codec_plan=codec_plan, audio_target=audio_target, tools=tools, logger=logger,
                pad_color=pad_color, crf=crf, preset=preset, dry_run=dry_run, gpu_plan=gpu_plan,
                force_video_transcode=True, target_video_bitrate=target_video_bitrate
            )
            processed_paths = [processed_path]
        return idx, processed_paths

    is_gpu_enabled = gpu_plan is not None and gpu_plan.enabled
    max_workers = min(max(1, gpu_workers), 3, len(segments)) if is_gpu_enabled else 1

    if max_workers > 1 and len(segments) > 1:
        logger.info("Using parallel processing with %d workers (GPU enabled).", max_workers)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(worker, i, seg): i for i, seg in enumerate(segments)}
            for future in concurrent.futures.as_completed(futures):
                idx, paths = future.result()
                outputs[idx] = paths
                if progress_callback:
                    for file in segments[idx].files:
                        progress_callback(file)
    else:
        # 串行模式（原始逻辑）
        for i, segment in enumerate(segments):
            _, paths = worker(i, segment)
            outputs[i] = paths
            if progress_callback:
                for file in segment.files:
                    progress_callback(file)

    flattened_outputs = [path for segment_paths in outputs for path in segment_paths]
    if keep_temp:
        logger.info("Keeping temp files in %s", temp_dir)
        return flattened_outputs, None
    return flattened_outputs, temp_owner


def preprocess_copy_segment(
    segment: PreprocessSegment,
    output_path: Path,
    temp_dir: Path,
    index: int,
    canvas: Canvas,
    fps: float,
    codec_plan: CodecPlan,
    audio_target: AudioTarget,
    tools: ToolPaths,
    logger: logging.Logger,
    pad_color: str,
    crf: int,
    preset: str,
    dry_run: bool,
    gpu_plan: GpuPlan | None = None,
    target_video_bitrate: int = 0,
) -> Path:
    first = segment.files[0]
    source_path = first.path
    if len(segment.files) > 1:
        source_path = temp_dir / f"{index:04d}_copy_segment.mp4"
        logger.info(
            "Preprocess decision: stream-copy %d ready file(s) into segment before one normalization pass.",
            len(segment.files),
        )
        concat_copy(
            files=[file.path for file in segment.files],
            output_path=source_path,
            tools=tools,
            logger=logger,
            mode=MergeMode.optimal,
            overwrite=True,
            dry_run=dry_run,
            temp_root=temp_dir,
        )
    else:
        logger.info("Preprocess decision: normalize single ready file as its own safe segment: %s", first.path.name)

    segment_file = replace(first, path=source_path, duration=sum(file.duration for file in segment.files))
    return preprocess_file(
        file=segment_file,
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
        force_video_transcode=True,
        target_video_bitrate=target_video_bitrate,
    )


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
    force_video_transcode: bool = False,
    target_video_bitrate: int = 0,
) -> Path:
    audio_target = audio_target or choose_audio_target([file], codec_plan)
    video_action = choose_video_action(file, canvas, fps, codec_plan)
    if force_video_transcode:
        video_action = "transcode"
    audio_action = choose_audio_action(file, audio_target)
    if not force_video_transcode and video_action == "copy" and audio_action == "copy" and _is_concat_safe_source(file):
        logger.info(
            "Preprocess decision: copy original %s | video/audio already match target.",
            file.path.name,
        )
        return file.path

    if not force_video_transcode and video_action == "copy" and audio_action == "copy":
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
    ]

    # 【硬件解码注入】
    # 严格遵照用户设置：仅当用户启用了 GPU，且当前画面确实需要被重新解码处理时，才启用硬件解码
    if gpu_plan is not None and gpu_plan.enabled and video_action != "copy":
        args.extend(["-hwaccel", "auto"])

    args.extend(["-i", file.path])

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
                    target_video_bitrate,
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


def can_concat_originals(
    files: list[VideoFile],
    canvas: Canvas,
    fps: float,
    codec_plan: CodecPlan,
    audio_target: AudioTarget,
) -> bool:
    if not files:
        return False
    if not all(_is_concat_safe_source(file) for file in files):
        return False
    if not all(choose_video_action(file, canvas, fps, codec_plan) == "copy" for file in files):
        return False
    if not all(choose_audio_action(file, audio_target) == "copy" for file in files):
        return False
    first = _concat_signature(files[0])
    return all(_concat_signature(file) == first for file in files[1:])


def build_preprocess_segments(
    files: list[VideoFile],
    canvas: Canvas,
    fps: float,
    codec_plan: CodecPlan,
    audio_target: AudioTarget,
) -> list[PreprocessSegment]:
    segments: list[PreprocessSegment] = []
    current: list[VideoFile] = []

    def flush_current() -> None:
        nonlocal current
        if current:
            segments.append(PreprocessSegment(files=current, copy_compatible=True))
            current = []

    for file in files:
        copy_ready = (
            _is_concat_safe_source(file)
            and choose_video_action(file, canvas, fps, codec_plan) == "copy"
            and choose_audio_action(file, audio_target) == "copy"
        )
        if not copy_ready:
            flush_current()
            segments.append(PreprocessSegment(files=[file], copy_compatible=False))
            continue
        if current and _concat_signature(file) != _concat_signature(current[0]):
            flush_current()
        current.append(file)

    flush_current()
    return segments


def choose_passthrough_signature(segments: list[PreprocessSegment]) -> tuple[object, ...] | None:
    ready_signatures: list[tuple[object, ...]] = []
    for segment in segments:
        if not segment.copy_compatible:
            continue
        ready_signatures.extend(_concat_signature(file) for file in segment.files)
    if not ready_signatures:
        return None
    return Counter(ready_signatures).most_common(1)[0][0]


def plan_preprocess_actions(
    files: list[VideoFile],
    canvas: Canvas,
    fps: float,
    codec_plan: CodecPlan,
    reference_files: list[VideoFile] | tuple[VideoFile, ...] | None = None,
) -> dict[Path, str]:
    audio_target = choose_audio_target(list(reference_files or files), codec_plan)
    segments = build_preprocess_segments(files, canvas, fps, codec_plan, audio_target)
    passthrough_signature = choose_passthrough_signature(segments)
    actions: dict[Path, str] = {}
    for segment in segments:
        passthrough = (
            segment.copy_compatible
            and passthrough_signature is not None
            and _concat_signature(segment.files[0]) == passthrough_signature
        )
        for file in segment.files:
            actions[file.path] = "copy" if passthrough else "transcode"
    return actions


def _concat_signature(file: VideoFile) -> tuple[object, ...]:
    return (
        _normalize_video_codec(file.video_codec),
        _normalize_audio_codec(file.audio_codec or ""),
        file.display_width,
        file.display_height,
        file.frame_rate,
        file.pixel_format,
        file.rotation,
        file.audio_sample_rate,
        file.audio_channels,
    )


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


def _log_size_estimate(
    files: list[VideoFile],
    segments: list[PreprocessSegment],
    passthrough_signature: tuple[object, ...] | None,
    target_video_bitrate: int,
    audio_target: AudioTarget,
    logger: logging.Logger,
) -> None:
    if target_video_bitrate <= 0:
        return
    source_sizes: dict[Path, int] = {}
    for file in files:
        try:
            source_sizes[file.path] = file.path.stat().st_size
        except OSError:
            return
    source_total = sum(source_sizes.values())
    if source_total <= 0:
        return

    audio_bitrate = int(audio_target.bitrate.removesuffix("k")) * 1000
    estimated_total = 0
    for segment in segments:
        passthrough = (
            segment.copy_compatible
            and passthrough_signature is not None
            and _concat_signature(segment.files[0]) == passthrough_signature
        )
        for file in segment.files:
            if passthrough:
                estimated_total += source_sizes[file.path]
            else:
                estimated_total += int(max(file.duration, 0.1) * (target_video_bitrate + audio_bitrate) / 8)

    ratio = estimated_total / source_total
    logger.info(
        "Estimated output size: %.2f GiB (source %.2f GiB, ratio %.2fx).",
        estimated_total / (1024**3),
        source_total / (1024**3),
        ratio,
    )
    if ratio > 1.5:
        logger.warning(
            "Estimated output exceeds source size by %.2fx. Consider dominant resolution or a smaller quality profile.",
            ratio,
        )


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
