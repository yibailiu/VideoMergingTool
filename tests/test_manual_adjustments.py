from __future__ import annotations

import unittest
from pathlib import Path

from videomerge.adjustments import apply_clockwise_rotation, validate_clockwise_rotation
from videomerge.models import Canvas, CodecPlan, Orientation, VideoFile
from videomerge.transcode import build_video_filter, choose_video_action


class ManualAdjustmentTests(unittest.TestCase):
    def test_clockwise_rotation_changes_effective_display_geometry(self) -> None:
        adjusted = apply_clockwise_rotation(_video(), 90)

        self.assertEqual(adjusted.rotation, 270)
        self.assertEqual(adjusted.manual_rotation, 90)
        self.assertEqual((adjusted.display_width, adjusted.display_height), (720, 1280))
        self.assertEqual(adjusted.aspect_ratio, "9:16")
        self.assertEqual(adjusted.orientation, Orientation.portrait)
        self.assertTrue(
            build_video_filter(adjusted.rotation, Canvas(720, 1280), 30.0, "black").startswith("transpose=1,")
        )

    def test_manual_rotation_that_cancels_metadata_still_forces_transcode(self) -> None:
        source = _video().__class__(
            **{
                **_video().__dict__,
                "display_width": 720,
                "display_height": 1280,
                "aspect_ratio": "9:16",
                "orientation": Orientation.portrait,
                "rotation": 90,
            }
        )

        adjusted = apply_clockwise_rotation(source, 90)
        action = choose_video_action(
            adjusted,
            Canvas(1280, 720),
            30.0,
            CodecPlan("h264", "aac", "libx264", "aac"),
        )

        self.assertEqual(adjusted.rotation, 0)
        self.assertEqual(adjusted.orientation, Orientation.landscape)
        self.assertEqual(action, "transcode")

    def test_manual_rotation_rejects_non_quarter_turn(self) -> None:
        with self.assertRaises(ValueError):
            validate_clockwise_rotation(45)


def _video() -> VideoFile:
    return VideoFile(
        path=Path("clip.mp4"),
        container="mp4",
        video_codec="h264",
        audio_codec="aac",
        width=1280,
        height=720,
        display_width=1280,
        display_height=720,
        aspect_ratio="16:9",
        frame_rate="30/1",
        frame_rate_float=30.0,
        pixel_format="yuv420p",
        duration=10.0,
        has_audio=True,
        orientation=Orientation.landscape,
        rotation=0,
        video_bitrate=2_000_000,
        audio_bitrate=128_000,
        audio_sample_rate=48000,
        audio_channels=2,
    )


if __name__ == "__main__":
    unittest.main()
