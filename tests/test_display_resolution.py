from __future__ import annotations

import unittest
from pathlib import Path

from videomerge.grouping import choose_canvas, split_by_orientation
from videomerge.models import Orientation, VideoFile


class DisplayResolutionTests(unittest.TestCase):
    def test_canvas_uses_display_dimensions_after_rotation(self) -> None:
        files = [
            _video("plain_portrait.mp4", 750, 1334, 750, 1334, 0),
            _video("rotated_portrait.mp4", 1280, 720, 720, 1280, 90),
        ]

        groups = split_by_orientation(files)
        canvas = choose_canvas(groups[Orientation.portrait])

        self.assertEqual(canvas.width, 750)
        self.assertEqual(canvas.height, 1334)


def _video(
    name: str,
    width: int,
    height: int,
    display_width: int,
    display_height: int,
    rotation: int,
) -> VideoFile:
    return VideoFile(
        path=Path(name),
        container="mp4",
        video_codec="h264",
        audio_codec="aac",
        width=width,
        height=height,
        display_width=display_width,
        display_height=display_height,
        aspect_ratio=f"{display_width}:{display_height}",
        frame_rate="30000/1001",
        frame_rate_float=29.97,
        pixel_format="yuv420p",
        duration=1.0,
        has_audio=True,
        orientation=Orientation.portrait,
        rotation=rotation,
    )


if __name__ == "__main__":
    unittest.main()
