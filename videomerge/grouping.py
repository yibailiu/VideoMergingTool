from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from .models import Canvas, CodecPlan, FastGroupKey, Orientation, VideoFile
from .utils import ensure_even


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
) -> CodecPlan:
    file_list = list(files)
    video_codec = requested_video_codec or _most_common([file.video_codec for file in file_list], "h264")
    audio_codec = requested_audio_codec or _most_common(
        [file.audio_codec for file in file_list if file.audio_codec],
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
