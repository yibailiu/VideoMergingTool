from __future__ import annotations

import logging
import unittest
from pathlib import Path

from videomerge.cli import _container_adjusted_plan, _default_transcode_video_codec
from videomerge.grouping import majority_codec_plan
from videomerge.models import Orientation, VideoFile


class CodecPlanTests(unittest.TestCase):
    def test_auto_transcode_defaults_to_h264_for_mp4_even_when_mpeg4_is_majority(self) -> None:
        files = [_video("one.mp4", "h264"), _video("two.mp4", "mpeg4"), _video("three.mp4", "mpeg4")]

        plan = majority_codec_plan(
            files,
            requested_video_codec=None,
            requested_audio_codec=None,
            default_video_codec=_default_transcode_video_codec("mp4"),
        )

        self.assertEqual(plan.video_codec, "h264")
        self.assertEqual(plan.output_video_encoder, "libx264")

    def test_requested_video_codec_is_respected(self) -> None:
        files = [_video("one.mp4", "h264")]

        plan = majority_codec_plan(
            files,
            requested_video_codec="hevc",
            requested_audio_codec=None,
            default_video_codec=_default_transcode_video_codec("mp4"),
        )

        self.assertEqual(plan.video_codec, "hevc")
        self.assertEqual(plan.output_video_encoder, "libx265")

    def test_webm_auto_transcode_defaults_to_vp9_and_opus(self) -> None:
        files = [_video("one.mp4", "mpeg4")]

        plan = majority_codec_plan(
            files,
            requested_video_codec=None,
            requested_audio_codec=None,
            default_video_codec=_default_transcode_video_codec("webm"),
        )
        adjusted = _container_adjusted_plan(plan, "webm", logging.getLogger("test"))

        self.assertEqual(adjusted.video_codec, "vp9")
        self.assertEqual(adjusted.output_video_encoder, "libvpx-vp9")
        self.assertEqual(adjusted.audio_codec, "opus")
        self.assertEqual(adjusted.output_audio_encoder, "libopus")


def _video(name: str, codec: str) -> VideoFile:
    return VideoFile(
        path=Path(name),
        container="mp4",
        video_codec=codec,
        audio_codec="aac",
        width=1280,
        height=720,
        display_width=1280,
        display_height=720,
        aspect_ratio="1280:720",
        frame_rate="30/1",
        frame_rate_float=30.0,
        pixel_format="yuv420p",
        duration=10.0,
        has_audio=True,
        orientation=Orientation.landscape,
        rotation=0,
    )


if __name__ == "__main__":
    unittest.main()
