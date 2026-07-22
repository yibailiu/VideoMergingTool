from __future__ import annotations

import logging
import platform
import subprocess
from dataclasses import dataclass
from enum import Enum

from .models import ToolPaths
from .utils import subprocess_window_kwargs


class GpuMode(str, Enum):
    off = "off"
    auto = "auto"
    nvenc = "nvenc"
    qsv = "qsv"
    amf = "amf"
    videotoolbox = "videotoolbox"


@dataclass(frozen=True)
class GpuPlan:
    mode: GpuMode
    encoder: str | None
    available_encoders: set[str]
    reason: str

    @property
    def enabled(self) -> bool:
        return self.encoder is not None


WINDOWS_PRIORITY = (GpuMode.nvenc, GpuMode.qsv, GpuMode.amf)
MAC_PRIORITY = (GpuMode.videotoolbox,)
LINUX_PRIORITY = (GpuMode.nvenc, GpuMode.qsv)


def resolve_gpu_plan(
    tools: ToolPaths,
    gpu_mode: GpuMode,
    target_video_codec: str,
    logger: logging.Logger,
) -> GpuPlan:
    if gpu_mode == GpuMode.off:
        return GpuPlan(gpu_mode, None, set(), "GPU acceleration disabled.")

    available = detect_ffmpeg_encoders(tools)
    normalized_codec = _normalize_codec(target_video_codec)
    if normalized_codec is None:
        reason = (
            f"GPU acceleration is only supported for H.264/HEVC targets; "
            f"codec={target_video_codec} will use CPU encoding."
        )
        logger.warning(reason)
        return GpuPlan(gpu_mode, None, available, reason)

    candidates = _candidate_modes(gpu_mode)
    for mode in candidates:
        encoder = _encoder_for(mode, normalized_codec)
        if encoder and encoder in available:
            logger.info("GPU acceleration enabled: mode=%s encoder=%s", mode.value, encoder)
            return GpuPlan(mode, encoder, available, f"Using {encoder}.")

    reason = (
        f"No compatible GPU encoder found for codec={normalized_codec}, requested={gpu_mode.value}. "
        "Falling back to CPU encoder."
    )
    logger.warning(reason)
    return GpuPlan(gpu_mode, None, available, reason)


def detect_ffmpeg_encoders(tools: ToolPaths, timeout: int = 5) -> set[str]:
    try:
        process = subprocess.run(
            [str(tools.ffmpeg), "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **subprocess_window_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    output = f"{process.stdout}\n{process.stderr}"
    encoders: set[str] = set()
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-"):
            continue
        parts = stripped.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            encoders.add(parts[1])
    return encoders


def apply_gpu_encoder(codec_plan, gpu_plan: GpuPlan):
    if not gpu_plan.enabled:
        return codec_plan
    return codec_plan.__class__(
        video_codec=codec_plan.video_codec,
        audio_codec=codec_plan.audio_codec,
        output_video_encoder=gpu_plan.encoder,
        output_audio_encoder=codec_plan.output_audio_encoder,
    )


def gpu_encoder_quality_args(
    encoder: str | None,
    crf: int,
    preset: str,
    width: int | None = None,
    height: int | None = None,
    fps: float | None = None,
    source_bitrate: int | None = None,
) -> list[str]:
    if not encoder:
        return _with_bitrate_limit(_cpu_encoder_quality_args("libx264", crf, preset), source_bitrate)
    if encoder in {"libx264", "libx265"}:
        return _with_bitrate_limit(_cpu_encoder_quality_args(encoder, crf, preset), source_bitrate)
    if encoder in {"h264_nvenc", "hevc_nvenc"}:
        return _with_bitrate_limit(
            ["-cq", str(crf), "-preset", _nvenc_preset(preset), "-rc", "vbr"],
            source_bitrate,
        )
    if encoder in {"h264_qsv", "hevc_qsv"}:
        if source_bitrate and source_bitrate > 0:
            return _with_bitrate_limit([], source_bitrate)
        return ["-global_quality", str(crf)]
    if encoder in {"h264_amf", "hevc_amf"}:
        if source_bitrate and source_bitrate > 0:
            return _with_bitrate_limit(["-quality", "balanced"], source_bitrate)
        return ["-quality", "balanced", "-qp_i", str(crf), "-qp_p", str(crf), "-qp_b", str(crf)]
    if encoder in {"h264_videotoolbox", "hevc_videotoolbox"}:
        bitrate = _videotoolbox_bitrate(
            crf,
            width,
            height,
            fps,
            source_bitrate=source_bitrate,
            hevc=encoder == "hevc_videotoolbox",
        )
        maxrate = bitrate
        bufsize = int(bitrate * 2)
        args = ["-b:v", f"{bitrate}k", "-maxrate", f"{maxrate}k", "-bufsize", f"{bufsize}k", "-allow_sw", "1"]
        if encoder == "h264_videotoolbox":
            args.extend(["-profile:v", "high"])
        return args
    if encoder == "mpeg4":
        return _with_bitrate_limit(["-q:v", str(_mpeg4_quality(crf))], source_bitrate)
    return _with_bitrate_limit(["-crf", str(crf), "-preset", preset], source_bitrate)


def _cpu_encoder_quality_args(encoder: str, crf: int, preset: str) -> list[str]:
    args = ["-crf", str(crf), "-preset", preset]
    if encoder == "libx264":
        args.extend(["-profile:v", "high"])
    return args


def _with_bitrate_limit(args: list[str], source_bitrate: int | None) -> list[str]:
    if not source_bitrate or source_bitrate <= 0:
        return args
    bitrate_kbps = max(400, source_bitrate // 1000)
    return [
        *args,
        "-b:v",
        f"{bitrate_kbps}k",
        "-maxrate",
        f"{bitrate_kbps}k",
        "-bufsize",
        f"{bitrate_kbps * 2}k",
    ]


def _candidate_modes(gpu_mode: GpuMode) -> tuple[GpuMode, ...]:
    if gpu_mode != GpuMode.auto:
        return (gpu_mode,)
    system = platform.system()
    if system == "Windows":
        return WINDOWS_PRIORITY
    if system == "Darwin":
        return MAC_PRIORITY
    return LINUX_PRIORITY


def _normalize_codec(codec: str) -> str | None:
    normalized = codec.lower()
    if normalized in {"h265", "hevc", "libx265", "hevc_nvenc", "hevc_qsv", "hevc_amf", "hevc_videotoolbox"}:
        return "hevc"
    if normalized in {"h264", "avc", "libx264", "h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox"}:
        return "h264"
    return None


def _encoder_for(mode: GpuMode, codec: str) -> str | None:
    mapping = {
        (GpuMode.nvenc, "h264"): "h264_nvenc",
        (GpuMode.nvenc, "hevc"): "hevc_nvenc",
        (GpuMode.qsv, "h264"): "h264_qsv",
        (GpuMode.qsv, "hevc"): "hevc_qsv",
        (GpuMode.amf, "h264"): "h264_amf",
        (GpuMode.amf, "hevc"): "hevc_amf",
        (GpuMode.videotoolbox, "h264"): "h264_videotoolbox",
        (GpuMode.videotoolbox, "hevc"): "hevc_videotoolbox",
    }
    return mapping.get((mode, codec))


def _nvenc_preset(preset: str) -> str:
    if preset in {"slow", "slower", "veryslow"}:
        return "p7"
    if preset in {"fast", "faster", "veryfast"}:
        return "p3"
    if preset in {"superfast", "ultrafast"}:
        return "p1"
    return "p5"


def _videotoolbox_bitrate(
    crf: int,
    width: int | None,
    height: int | None,
    fps: float | None,
    source_bitrate: int | None = None,
    hevc: bool = False,
) -> int:
    safe_width = width or 1920
    safe_height = height or 1080
    safe_fps = fps or 30.0
    if source_bitrate and source_bitrate > 0:
        baseline_kbps = source_bitrate / 1000
        quality_factor = 1.0
    else:
        quality_factor = max(0.5, min(2.0, 2 ** ((23 - crf) / 6)))
        bits_per_pixel = 0.065 if hevc else 0.1
        baseline_kbps = (safe_width * safe_height * safe_fps * bits_per_pixel) / 1000
    bitrate = int(baseline_kbps * quality_factor)
    return max(400, min(40_000, bitrate))


def _mpeg4_quality(crf: int) -> int:
    return max(1, min(31, round((max(0, min(51, crf)) / 51) * 30 + 1)))
