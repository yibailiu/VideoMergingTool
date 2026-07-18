from __future__ import annotations

import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import ProbeError
from .models import Orientation, ToolPaths, VideoFile
from .utils import parse_fraction, subprocess_window_kwargs


def probe_file(path: Path, tools: ToolPaths, logger: logging.Logger) -> VideoFile:
    args = [
        str(tools.ffprobe),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    process = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **subprocess_window_kwargs(),
    )
    if process.returncode != 0:
        raise ProbeError(process.stderr.strip() or f"ffprobe failed for {path}")
    if not process.stdout:
        raise ProbeError(f"ffprobe returned no JSON for {path}")

    try:
        payload = json.loads(process.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProbeError(f"Invalid ffprobe JSON for {path}: {exc}") from exc

    streams = payload.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video_stream:
        raise ProbeError(f"No video stream found in {path}")

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ProbeError(f"Invalid video dimensions for {path}: {width}x{height}")

    rotation = _read_rotation(video_stream)
    display_width, display_height = (height, width) if abs(rotation) in {90, 270} else (width, height)
    orientation = _orientation(display_width, display_height)
    frame_rate = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "0/0"
    duration = _read_duration(payload, video_stream)
    audio_bitrate = _read_int(audio_stream.get("bit_rate")) if audio_stream else 0
    video_bitrate = _read_int(video_stream.get("bit_rate"))
    if video_bitrate <= 0:
        video_bitrate = max(0, _read_int(payload.get("format", {}).get("bit_rate")) - audio_bitrate)
    audio_sample_rate = _read_int(audio_stream.get("sample_rate")) if audio_stream else 0
    audio_channels = _read_int(audio_stream.get("channels")) if audio_stream else 0
    media_created_at = _read_media_created_at(payload, video_stream)

    file = VideoFile(
        path=path,
        container=(payload.get("format", {}).get("format_name") or "unknown").split(",")[0],
        video_codec=video_stream.get("codec_name") or "unknown",
        audio_codec=audio_stream.get("codec_name") if audio_stream else None,
        width=width,
        height=height,
        display_width=display_width,
        display_height=display_height,
        aspect_ratio=f"{display_width}:{display_height}",
        frame_rate=frame_rate,
        frame_rate_float=parse_fraction(frame_rate, 0.0),
        pixel_format=video_stream.get("pix_fmt") or "unknown",
        duration=duration,
        has_audio=audio_stream is not None,
        orientation=orientation,
        rotation=rotation,
        video_bitrate=video_bitrate,
        audio_bitrate=audio_bitrate,
        audio_sample_rate=audio_sample_rate,
        audio_channels=audio_channels,
        media_created_at=media_created_at,
        video_time_base=str(video_stream.get("time_base") or ""),
    )
    logger.debug("Probed %s: %s", path, file)
    return file


def probe_files(paths: list[Path], tools: ToolPaths, logger: logging.Logger) -> tuple[list[VideoFile], dict[Path, str]]:
    ordered_results: list[VideoFile | None] = [None] * len(paths)
    failures: dict[Path, str] = {}

    def worker(index: int, path: Path) -> tuple[int, VideoFile | None, str | None]:
        try:
            return index, probe_file(path, tools, logger), None
        except ProbeError as exc:
            return index, None, str(exc)

    max_workers = min(4, len(paths))
    if max_workers > 1:
        logger.info("Analyzing %d media files with %d parallel probes.", len(paths), max_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(worker, index, path) for index, path in enumerate(paths)]
            completed = (future.result() for future in as_completed(futures))
            for index, file, error in completed:
                if file is not None:
                    ordered_results[index] = file
                elif error is not None:
                    failures[paths[index]] = error
    else:
        for index, path in enumerate(paths):
            _, file, error = worker(index, path)
            if file is not None:
                ordered_results[index] = file
            elif error is not None:
                failures[path] = error

    results: list[VideoFile] = []
    for path, file in zip(paths, ordered_results):
        if file is not None:
            results.append(file)
            logger.info(
                "Media: %s | %s %dx%d display=%dx%d fps=%s pix=%s audio=%s/%sHz/%sch bitrate=%dk/%dk duration=%.2fs rotation=%d",
                path.name,
                file.video_codec,
                file.width,
                file.height,
                file.display_width,
                file.display_height,
                file.frame_rate,
                file.pixel_format,
                file.audio_codec or "none",
                file.audio_sample_rate or "-",
                file.audio_channels or "-",
                round(file.video_bitrate / 1000),
                round(file.audio_bitrate / 1000),
                file.duration,
                file.rotation,
            )
        else:
            logger.warning("Skipping unreadable file %s: %s", path, failures[path])
    return results, failures


def _read_duration(payload: dict[str, Any], video_stream: dict[str, Any]) -> float:
    raw = video_stream.get("duration") or payload.get("format", {}).get("duration")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _read_int(value: object) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _read_media_created_at(payload: dict[str, Any], video_stream: dict[str, Any]) -> float | None:
    format_tags = payload.get("format", {}).get("tags") or {}
    stream_tags = video_stream.get("tags") or {}
    for key in ("creation_time", "com.apple.quicktime.creationdate"):
        for tags in (format_tags, stream_tags):
            value = next((tag_value for tag_name, tag_value in tags.items() if tag_name.casefold() == key), None)
            timestamp = _parse_media_timestamp(value)
            if timestamp is not None:
                return timestamp
    return None


def _parse_media_timestamp(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _read_rotation(video_stream: dict[str, Any]) -> int:
    tags = video_stream.get("tags") or {}
    for key in ("rotate", "rotation"):
        if key in tags:
            return _normalize_rotation(tags[key])

    for side_data in video_stream.get("side_data_list") or []:
        if "rotation" in side_data:
            return _normalize_rotation(side_data["rotation"])
    return 0


def _normalize_rotation(value: object) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    number %= 360
    return number if number in {0, 90, 180, 270} else 0


def _orientation(width: int, height: int) -> Orientation:
    if width > height:
        return Orientation.landscape
    if height > width:
        return Orientation.portrait
    return Orientation.square
