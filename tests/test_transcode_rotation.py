from __future__ import annotations

import logging
import unittest
from pathlib import Path
from unittest.mock import patch

from videomerge.models import Canvas, CodecPlan, Orientation, ToolPaths, VideoFile
from videomerge.transcode import (
    AudioTarget,
    build_video_filter,
    choose_audio_action,
    choose_audio_target,
    choose_video_action,
    preprocess_file,
    validate_preprocessed_output,
)


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

    def test_compatible_file_skips_transcode_and_uses_original_path(self) -> None:
        file = _plain_video()

        with patch("videomerge.transcode.run_command") as run:
            output = preprocess_file(
                file=file,
                output_path=Path("out.mp4"),
                canvas=Canvas(1280, 720),
                fps=30.0,
                codec_plan=CodecPlan("h264", "aac", "libx264", "aac"),
                tools=ToolPaths(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe")),
                logger=logging.getLogger("test"),
                pad_color="black",
                crf=23,
                preset="medium",
                dry_run=True,
                audio_target=AudioTarget("aac", "aac", 48000, 2, "128k"),
            )

        self.assertEqual(output, file.path)
        run.assert_not_called()

    def test_audio_only_reencode_copies_video(self) -> None:
        captured_args = []
        file = _plain_video().__class__(**{**_plain_video().__dict__, "audio_sample_rate": 44100})

        def fake_run_command(args, logger, dry_run=False):  # type: ignore[no-untyped-def]
            captured_args.extend(args)

        with patch("videomerge.transcode.run_command", side_effect=fake_run_command):
            preprocess_file(
                file=file,
                output_path=Path("out.mp4"),
                canvas=Canvas(1280, 720),
                fps=30.0,
                codec_plan=CodecPlan("h264", "aac", "libx264", "aac"),
                tools=ToolPaths(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe")),
                logger=logging.getLogger("test"),
                pad_color="black",
                crf=23,
                preset="medium",
                dry_run=True,
                audio_target=AudioTarget("aac", "aac", 48000, 2, "128k"),
            )

        self.assertEqual(captured_args[captured_args.index("-c:v") + 1], "copy")
        self.assertEqual(captured_args[captured_args.index("-c:a") + 1], "aac")
        self.assertNotIn("-vf", captured_args)

    def test_choose_audio_target_uses_source_shape_and_caps_mono_bitrate(self) -> None:
        file = _plain_video().__class__(**{**_plain_video().__dict__, "audio_channels": 1, "audio_bitrate": 160000})

        target = choose_audio_target([file], CodecPlan("h264", "aac", "libx264", "aac"))

        self.assertEqual(target.channels, 1)
        self.assertEqual(target.sample_rate, 48000)
        self.assertEqual(target.bitrate, "96k")

    def test_action_helpers_detect_video_and_audio_copy(self) -> None:
        file = _plain_video()
        audio_target = AudioTarget("aac", "aac", 48000, 2, "128k")

        self.assertEqual(choose_video_action(file, Canvas(1280, 720), 30.0, CodecPlan("h264", "aac", "libx264", "aac")), "copy")
        self.assertEqual(choose_audio_action(file, audio_target), "copy")


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


def _plain_video() -> VideoFile:
    return VideoFile(
        path=Path("plain.mp4"),
        container="mp4",
        video_codec="h264",
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
        video_bitrate=2_000_000,
        audio_bitrate=128_000,
        audio_sample_rate=48000,
        audio_channels=2,
    )
