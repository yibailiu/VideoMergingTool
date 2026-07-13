from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Iterable

from .models import Canvas, CodecPlan, FastGroupKey, Orientation, VideoFile
from .utils import ensure_even


@dataclass(frozen=True)
class DominantSourceProfile:
    files: tuple[VideoFile, ...]
    canvas: Canvas
    fps: float
    video_codec: str
    audio_codec: str | None
    video_bitrate: int


def group_fast(files: Iterable[VideoFile]) -> dict[FastGroupKey, list[VideoFile]]:
    grouped: dict[FastGroupKey, list[VideoFile]] = defaultdict(list)
    for file in files:
        key = FastGroupKey(
            video_codec=file.video_codec,
            audio_codec=file.audio_codec,
            width=file.display_width,
            height=file.display_height,
            frame_rate=file.frame_rate,
            pixel_format=file.pixel_format,
            orientation=file.orientation,
            rotation=file.rotation,
        )
        grouped[key].append(file)
    return dict(grouped)


def split_by_orientation(files: Iterable[VideoFile]) -> dict[Orientation, list[VideoFile]]:
    groups: dict[Orientation, list[VideoFile]] = defaultdict(list)
    for file in files:
        orientation = file.orientation
        if orientation == Orientation.square:
            orientation = Orientation.landscape
        groups[orientation].append(file)
    return {
        orientation: group
        for orientation, group in groups.items()
        if orientation in {Orientation.landscape, Orientation.portrait} and group
    }


def majority_codec_plan(
    files: Iterable[VideoFile],
    requested_video_codec: str | None,
    requested_audio_codec: str | None,
    default_video_codec: str = "h264",
) -> CodecPlan:
    file_list = list(files)
    source_video_codec = _most_common(
        [_normalize_video_codec(file.video_codec) for file in file_list if file.video_codec],
        default_video_codec,
    )
    video_codec = requested_video_codec or (
        source_video_codec
        if source_video_codec in {"h264", "hevc", "vp8", "vp9", "av1"}
        else default_video_codec
    )
    audio_codec = requested_audio_codec or _most_common(
        [_normalize_audio_codec(file.audio_codec) for file in file_list if file.audio_codec],
        "aac",
    )
    return CodecPlan(
        video_codec=video_codec,
        audio_codec=audio_codec,
        output_video_encoder=ffmpeg_video_encoder(video_codec),
        output_audio_encoder=ffmpeg_audio_encoder(audio_codec),
    )


def choose_canvas(files: Iterable[VideoFile]) -> Canvas:
    file_list = list(files)
    width = max(file.display_width for file in file_list)
    height = max(file.display_height for file in file_list)
    return Canvas(width=ensure_even(width), height=ensure_even(height))


def choose_dominant_source_profile(files: Iterable[VideoFile]) -> DominantSourceProfile:
    file_list = list(files)
    if not file_list:
        raise ValueError("Cannot choose a source profile from an empty file list.")

    copy_candidates = [
        file
        for file in file_list
        if file.path.suffix.lower() in {".mp4", ".m4v", ".mov"}
        and file.rotation == 0
        and file.pixel_format == "yuv420p"
        and file.has_audio
    ]
    candidate_pool = copy_candidates or file_list
    grouped: dict[tuple[object, ...], list[VideoFile]] = defaultdict(list)
    for file in candidate_pool:
        grouped[_source_profile_key(file)].append(file)

    def candidate_score(item: tuple[tuple[object, ...], list[VideoFile]]) -> tuple[float, int, float, int]:
        key, members = item
        width = int(key[2])
        height = int(key[3])
        target_pixels = max(width * height, 1)
        member_paths = {file.path for file in members}
        transcode_cost = sum(
            max(file.duration, 0.1) * target_pixels
            for file in file_list
            if file.path not in member_paths
        )
        matching_duration = sum(max(file.duration, 0.1) for file in members)
        return transcode_cost, -len(members), -matching_duration, target_pixels

    selected_key, selected_files = min(grouped.items(), key=candidate_score)
    bitrates = [file.video_bitrate for file in selected_files if file.video_bitrate > 0]
    if not bitrates:
        bitrates = [file.video_bitrate for file in file_list if file.video_bitrate > 0]
    if not bitrates:
        bitrates = [bitrate for bitrate in (_estimated_video_bitrate(file) for file in selected_files) if bitrate > 0]
    fps = selected_files[0].frame_rate_float
    if fps <= 0:
        fps = choose_fps(selected_files, "majority")
    return DominantSourceProfile(
        files=tuple(selected_files),
        canvas=Canvas(width=ensure_even(int(selected_key[2])), height=ensure_even(int(selected_key[3]))),
        fps=fps,
        video_codec=str(selected_key[0]),
        audio_codec=str(selected_key[1]) or None,
        video_bitrate=int(median(bitrates)) if bitrates else 0,
    )


def choose_fps(files: Iterable[VideoFile], policy: str) -> float:
    fps_values = [file.frame_rate_float for file in files if file.frame_rate_float > 0]
    if not fps_values:
        return 30.0
    if policy == "max":
        return max(fps_values)
    if policy == "min":
        return min(fps_values)
    counter = Counter(round(value, 3) for value in fps_values)
    return counter.most_common(1)[0][0]


def ffmpeg_video_encoder(codec: str) -> str:
    normalized = codec.lower()
    mapping = {
        "h264": "libx264",
        "avc1": "libx264",
        "hevc": "libx265",
        "h265": "libx265",
        "vp8": "libvpx",
        "vp9": "libvpx-vp9",
        "av1": "libaom-av1",
        "mpeg4": "mpeg4",
    }
    return mapping.get(normalized, "libx264")


def ffmpeg_audio_encoder(codec: str) -> str:
    normalized = codec.lower()
    mapping = {
        "aac": "aac",
        "mp3": "libmp3lame",
        "opus": "libopus",
        "vorbis": "libvorbis",
        "pcm_s16le": "pcm_s16le",
    }
    return mapping.get(normalized, "aac")


def _most_common(values: list[str], default: str) -> str:
    if not values:
        return default
    return Counter(values).most_common(1)[0][0]


def _source_profile_key(file: VideoFile) -> tuple[object, ...]:
    return (
        _normalize_video_codec(file.video_codec),
        _normalize_audio_codec(file.audio_codec),
        file.display_width,
        file.display_height,
        file.frame_rate,
        file.pixel_format,
        file.rotation,
        file.audio_sample_rate,
        file.audio_channels,
    )


def _normalize_video_codec(codec: str | None) -> str:
    normalized = (codec or "").lower()
    if normalized in {"h264", "avc", "avc1", "libx264"}:
        return "h264"
    if normalized in {"hevc", "h265", "libx265"}:
        return "hevc"
    return normalized


def _normalize_audio_codec(codec: str | None) -> str:
    normalized = (codec or "").lower()
    if normalized in {"aac", "mp4a"}:
        return "aac"
    if normalized in {"mp3", "libmp3lame"}:
        return "mp3"
    if normalized in {"opus", "libopus"}:
        return "opus"
    if normalized in {"vorbis", "libvorbis"}:
        return "vorbis"
    return normalized


def _estimated_video_bitrate(file: VideoFile) -> int:
    if file.duration <= 0:
        return 0
    try:
        total_bitrate = int((file.path.stat().st_size * 8) / file.duration)
    except OSError:
        return 0
    return max(0, total_bitrate - max(file.audio_bitrate, 0))
