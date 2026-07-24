from __future__ import annotations

from dataclasses import replace
from math import gcd

from .models import Orientation, VideoFile


MANUAL_ROTATIONS = {0, 90, 180, 270}


def validate_clockwise_rotation(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Manual rotation must be one of 0, 90, 180, or 270 degrees.")
    try:
        rotation = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Manual rotation must be one of 0, 90, 180, or 270 degrees.") from exc
    if rotation not in MANUAL_ROTATIONS:
        raise ValueError("Manual rotation must be one of 0, 90, 180, or 270 degrees.")
    return rotation


def apply_clockwise_rotation(file: VideoFile, clockwise_rotation: int) -> VideoFile:
    rotation = validate_clockwise_rotation(clockwise_rotation)
    if rotation == 0:
        return file

    # FFprobe reports the display-matrix transform. The existing FFmpeg filter
    # maps 270 to a clockwise transpose, so a user-requested clockwise turn is
    # subtracted from the probed display transform.
    effective_rotation = (file.rotation - rotation) % 360
    if effective_rotation in {90, 270}:
        display_width, display_height = file.height, file.width
    else:
        display_width, display_height = file.width, file.height

    return replace(
        file,
        display_width=display_width,
        display_height=display_height,
        aspect_ratio=_aspect_ratio(display_width, display_height),
        orientation=_orientation(display_width, display_height),
        rotation=effective_rotation,
        manual_rotation=rotation,
    )


def _aspect_ratio(width: int, height: int) -> str:
    divisor = gcd(width, height) or 1
    return f"{width // divisor}:{height // divisor}"


def _orientation(width: int, height: int) -> Orientation:
    if width > height:
        return Orientation.landscape
    if height > width:
        return Orientation.portrait
    return Orientation.square
