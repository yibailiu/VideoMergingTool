from __future__ import annotations

import logging
import unittest
from pathlib import Path
from unittest.mock import patch

from videomerge.models import Canvas, CodecPlan, Orientation, ToolPaths, VideoFile
from videomerge.transcode import build_video_filter, preprocess_file, validate_preprocessed_output


class TranscodeRotationTests(unittest.TestCase):
    def test_rotation_filter_outputs_portrait_canvas(self) -> None:
        video_filter = build_video_filter(90, Canvas(720, 1280), 30.0, "black")

        self.assertTrue(video_filter.startswith("transpose=2,"))
        self.assertIn("scale=w=720:h=1280:force_original_aspect_ratio=decrease", video_filter)
        self.assertIn("pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=black", video_filter)

    def test_rotation_270_uses_opposite_transpose_direction(self) -> None:
        video_filter = build_video_filter(270, Canvas(720, 1280), 30.0, "black")

        self.assertTrue(video_filter.startswith("transpose=1,"))

    def test_preprocess_disables_ffmpeg_autorotate_and_clears_rotation_metadata(self) -> None:
        captured_args = []

        def fake_run_command(args, logger, dry_run=False):  # type: ignore[no-untyped-def]
            captured_args.extend(args)

        file = VideoFile(
            path=Path("11.MP4"),
            container="mp4",
            video_codec="h264",
            audio_codec="aac",
            width=1280,
            height=720,
            display_width=720,
            display_height=1280,
            aspect_ratio="720:1280",
            frame_rate="88830000/2959519",
            frame_rate_float=30.015,
            pixel_format="yuv420p",
            duration=32.55,
            has_audio=True,
            orientation=Orientation.portrait,
            rotation=90,
        )

        with patch("videomerge.transcode.run_command", side_effect=fake_run_command):
            preprocess_file(
                file=file,
                output_path=Path("out.mp4"),
                canvas=Canvas(720, 1280),
                fps=30.0,
                codec_plan=CodecPlan("h264", "aac", "libx264", "aac"),
                tools=ToolPaths(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe")),
                logger=logging.getLogger("test"),
                pad_color="black",
                crf=20,
                preset="medium",
                dry_run=True,
            )

        self.assertLess(captured_args.index("-noautorotate"), captured_args.index("-i"))
        self.assertLess(captured_args.index("-display_rotation:v:0"), captured_args.index("-i"))
        self.assertEqual(captured_args[captured_args.index("-display_rotation:v:0") + 1], "0")
        self.assertIn("transpose=2", captured_args[captured_args.index("-vf") + 1])
        self.assertEqual(captured_args[captured_args.index("-metadata:s:v:0") + 1], "rotate=0")
        self.assertIn("-crf", captured_args)

    def test_validation_requires_canvas_display_size_and_zero_rotation(self) -> None:
        source = _rotated_video()
        output = _rotated_video().__class__(
            path=Path("out.mp4"),
            container="mp4",
            video_codec="h264",
            audio_codec="aac",
            width=720,
            height=1280,
            display_width=720,
            display_height=1280,
            aspect_ratio="720:1280",
            frame_rate="30/1",
            frame_rate_float=30.0,
            pixel_format="yuv420p",
            duration=32.55,
            has_audio=True,
            orientation=Orientation.portrait,
            rotation=0,
        )

        with patch("videomerge.transcode.probe_file", return_value=output):
            validate_preprocessed_output(
                Path("out.mp4"),
                source,
                Canvas(720, 1280),
                ToolPaths(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe")),
                logging.getLogger("test"),
            )


if __name__ == "__main__":
    unittest.main()


def _rotated_video() -> VideoFile:
    return VideoFile(
        path=Path("11.MP4"),
        container="mp4",
        video_codec="h264",
        audio_codec="aac",
        width=1280,
        height=720,
        display_width=720,
        display_height=1280,
        aspect_ratio="720:1280",
        frame_rate="88830000/2959519",
        frame_rate_float=30.015,
        pixel_format="yuv420p",
        duration=32.55,
        has_audio=True,
        orientation=Orientation.portrait,
        rotation=90,
    )
