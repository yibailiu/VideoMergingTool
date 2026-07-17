from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class MergeMode(str, Enum):
    fast = "fast"
    optimal = "optimal"
    extreme = "extreme"


class Orientation(str, Enum):
    landscape = "landscape"
    portrait = "portrait"
    square = "square"
    unknown = "unknown"


@dataclass(frozen=True)
class ToolPaths:
    ffmpeg: Path
    ffprobe: Path


@dataclass(frozen=True)
class VideoFile:
    path: Path
    container: str
    video_codec: str
    audio_codec: Optional[str]
    width: int
    height: int
    display_width: int
    display_height: int
    aspect_ratio: str
    frame_rate: str
    frame_rate_float: float
    pixel_format: str
    duration: float
    has_audio: bool
    orientation: Orientation
    rotation: int
    video_bitrate: int = 0
    audio_bitrate: int = 0
    audio_sample_rate: int = 0
    audio_channels: int = 0
    media_created_at: Optional[float] = None

    @property
    def stem_safe(self) -> str:
        return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in self.path.stem)


@dataclass(frozen=True)
class FastGroupKey:
    video_codec: str
    audio_codec: Optional[str]
    width: int
    height: int
    frame_rate: str
    pixel_format: str
    orientation: Orientation
    rotation: int


@dataclass(frozen=True)
class Canvas:
    width: int
    height: int

    @property
    def label(self) -> str:
        return f"{self.width}x{self.height}"


@dataclass(frozen=True)
class CodecPlan:
    video_codec: str
    audio_codec: str
    output_video_encoder: str
    output_audio_encoder: str


@dataclass
class MergeResult:
    output_path: Path
    files: list[Path]
    mode: MergeMode
    note: str = ""
