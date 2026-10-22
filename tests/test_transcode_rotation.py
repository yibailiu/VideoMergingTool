from __future__ import annotations

import logging
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from videomerge.errors import CommandError
from videomerge.models import Canvas, CodecPlan, Orientation, ToolPaths, VideoFile
from videomerge.transcode import (
    AudioTarget,
    PreprocessSegment,
    _build_preprocess_jobs,
    _log_size_estimate,
    build_preprocess_segments,
    build_video_filter,
    can_concat_originals,
    choose_passthrough_signature,
    choose_audio_action,
    choose_audio_target,
    choose_preprocess_action,
    choose_video_action,
    preprocess_group,
    preprocess_file,
    validate_preprocessed_output,
)


class TranscodeRotationTests(unittest.TestCase):
    def test_rotation_filter_outputs_portrait_canvas(self) -> None:
        video_filter = build_video_filter(90, Canvas(720, 1280), 30.0, "black")

        self.assertTrue(video_filter.startswith("transpose=2,"))
        self.assertIn(
            "scale=w='min(iw,720)':h='min(ih,1280)':"
            "force_original_aspect_ratio=decrease:force_divisible_by=2",
            video_filter,
        )
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

        with patch("videomerge.transcode.run_command", side_effect=fake_run_command), patch(
            "videomerge.merge.run_command", side_effect=fake_run_command
        ):
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
        self.assertLess(captured_args.index("-nostats"), captured_args.index("-i"))
        self.assertLess(captured_args.index("-nostdin"), captured_args.index("-i"))
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

    def test_group_only_uses_originals_when_all_files_have_same_concat_signature(self) -> None:
        first = _plain_video()
        second = _plain_video().__class__(**{**_plain_video().__dict__, "path": Path("second.mp4")})
        audio_target = AudioTarget("aac", "aac", 48000, 2, "128k")

        self.assertTrue(
            can_concat_originals(
                [first, second],
                Canvas(1280, 720),
                30.0,
                CodecPlan("h264", "aac", "libx264", "aac"),
                audio_target,
            )
        )

    def test_group_rejects_original_copy_when_concat_signature_differs(self) -> None:
        first = _plain_video()
        second = _plain_video().__class__(**{**_plain_video().__dict__, "path": Path("second.mp4"), "frame_rate": "30000/1001", "frame_rate_float": 29.97})
        audio_target = AudioTarget("aac", "aac", 48000, 2, "128k")

        self.assertFalse(
            can_concat_originals(
                [first, second],
                Canvas(1280, 720),
                30.0,
                CodecPlan("h264", "aac", "libx264", "aac"),
                audio_target,
            )
        )

    def test_preprocess_group_passthroughs_dominant_ready_files_when_some_need_normalization(self) -> None:
        captured_commands = []
        first = _plain_video()
        second = _plain_video().__class__(**{**_plain_video().__dict__, "path": Path("second.mp4"), "frame_rate": "30000/1001", "frame_rate_float": 29.97})

        def fake_run_command(args, logger, dry_run=False):  # type: ignore[no-untyped-def]
            captured_commands.append(list(args))

        with patch("videomerge.transcode.run_command", side_effect=fake_run_command), patch(
            "videomerge.merge.run_command", side_effect=fake_run_command
        ):
            outputs, owner = preprocess_group(
                files=[first, second],
                canvas=Canvas(1280, 720),
                fps=30.0,
                codec_plan=CodecPlan("h264", "aac", "libx264", "aac"),
                tools=ToolPaths(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe")),
                logger=logging.getLogger("test"),
                pad_color="black",
                crf=23,
                preset="medium",
                keep_temp=False,
                dry_run=True,
            )
            if owner:
                owner.cleanup()

        self.assertEqual(len(outputs), 2)
        self.assertEqual(outputs[0], first.path)
        self.assertNotEqual(outputs[1], second.path)
        self.assertEqual(len(captured_commands), 1)
        self.assertTrue(all("-vf" in command for command in captured_commands))

    def test_safe_segmentation_preserves_order_and_batches_ready_runs(self) -> None:
        first = _plain_video()
        second = _plain_video().__class__(**{**_plain_video().__dict__, "path": Path("second.mp4")})
        third = _plain_video().__class__(**{**_plain_video().__dict__, "path": Path("third.mp4"), "frame_rate": "30000/1001", "frame_rate_float": 29.97})
        fourth = _plain_video().__class__(**{**_plain_video().__dict__, "path": Path("fourth.mp4")})
        audio_target = AudioTarget("aac", "aac", 48000, 2, "128k")

        segments = build_preprocess_segments(
            [first, second, third, fourth],
            Canvas(1280, 720),
            30.0,
            CodecPlan("h264", "aac", "libx264", "aac"),
            audio_target,
        )

        self.assertEqual([segment.files for segment in segments], [[first, second], [third], [fourth]])
        self.assertEqual([segment.copy_compatible for segment in segments], [True, False, True])

    def test_choose_passthrough_signature_uses_most_common_ready_signature(self) -> None:
        first = _plain_video()
        second = _plain_video().__class__(**{**_plain_video().__dict__, "path": Path("second.mp4")})
        third = _plain_video().__class__(**{**_plain_video().__dict__, "path": Path("third.mp4"), "frame_rate": "60/2", "frame_rate_float": 30.0})
        audio_target = AudioTarget("aac", "aac", 48000, 2, "128k")
        segments = build_preprocess_segments(
            [first, second, third],
            Canvas(1280, 720),
            30.0,
            CodecPlan("h264", "aac", "libx264", "aac"),
            audio_target,
        )

        self.assertEqual(choose_passthrough_signature(segments), choose_passthrough_signature([segments[0]]))

    def test_preprocess_group_treats_equivalent_fps_fractions_as_same_signature(self) -> None:
        captured_commands = []
        first = _plain_video()
        second = _plain_video().__class__(**{**_plain_video().__dict__, "path": Path("second.mp4")})
        third = _plain_video().__class__(**{**_plain_video().__dict__, "path": Path("third.mp4"), "frame_rate": "60/2", "frame_rate_float": 30.0})

        def fake_run_command(args, logger, dry_run=False):  # type: ignore[no-untyped-def]
            captured_commands.append(list(args))

        with patch("videomerge.transcode.run_command", side_effect=fake_run_command), patch(
            "videomerge.merge.run_command", side_effect=fake_run_command
        ):
            outputs, owner = preprocess_group(
                files=[first, second, third],
                canvas=Canvas(1280, 720),
                fps=30.0,
                codec_plan=CodecPlan("h264", "aac", "libx264", "aac"),
                tools=ToolPaths(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe")),
                logger=logging.getLogger("test"),
                pad_color="black",
                crf=23,
                preset="medium",
                keep_temp=False,
                dry_run=True,
            )
            if owner:
                owner.cleanup()

        concat_commands = [command for command in captured_commands if "-f" in command and "concat" in command]
        transcode_commands = [command for command in captured_commands if "-vf" in command]
        self.assertEqual(outputs, [first.path, second.path, third.path])
        self.assertEqual(len(concat_commands), 0)
        self.assertEqual(len(transcode_commands), 0)

    def test_preprocess_group_remuxes_every_file_in_non_dominant_ready_segment(self) -> None:
        captured_commands = []
        dominant = [
            replace(_plain_video(), path=Path(f"dominant-{index}.mp4"))
            for index in range(3)
        ]
        alternate = [
            replace(
                _plain_video(),
                path=Path(f"alternate-{index}.mp4"),
                video_time_base="1/90000",
            )
            for index in range(2)
        ]

        def fake_run_command(args, logger, dry_run=False):  # type: ignore[no-untyped-def]
            captured_commands.append(list(args))

        with patch("videomerge.transcode.run_command", side_effect=fake_run_command):
            outputs, owner = preprocess_group(
                files=[*dominant, *alternate],
                canvas=Canvas(1280, 720),
                fps=30.0,
                codec_plan=CodecPlan("h264", "aac", "libx264", "aac"),
                tools=ToolPaths(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe")),
                logger=logging.getLogger("test"),
                pad_color="black",
                crf=23,
                preset="medium",
                keep_temp=False,
                dry_run=True,
            )
            if owner:
                owner.cleanup()

        self.assertEqual(len(outputs), 5)
        self.assertEqual(outputs[:3], [file.path for file in dominant])
        self.assertTrue(all(output != file.path for output, file in zip(outputs[3:], alternate)))
        self.assertEqual(len(captured_commands), 2)
        self.assertTrue(all("-vf" not in command for command in captured_commands))
        self.assertCountEqual(
            [command[command.index("-i") + 1] for command in captured_commands],
            [file.path for file in alternate],
        )

    def test_preprocess_jobs_flatten_segments_without_changing_output_order(self) -> None:
        dominant = [
            replace(_plain_video(), path=Path(f"dominant-{index}.mp4"))
            for index in range(4)
        ]
        alternate = [
            replace(
                _plain_video(),
                path=Path(f"alternate-{index}.mp4"),
                video_time_base="1/90000",
            )
            for index in range(3)
        ]
        audio_target = AudioTarget("aac", "aac", 48000, 2, "128k")
        segments = build_preprocess_segments(
            [*dominant, *alternate],
            Canvas(1280, 720),
            30.0,
            CodecPlan("h264", "aac", "libx264", "aac"),
            audio_target,
        )
        passthrough_signature = choose_passthrough_signature(segments)

        outputs, jobs, passthrough_files = _build_preprocess_jobs(
            segments,
            passthrough_signature,
            Path("temp"),
        )

        self.assertEqual(passthrough_files, dominant)
        self.assertEqual(outputs[:4], [file.path for file in dominant])
        self.assertEqual([job.file for job in jobs], alternate)
        self.assertEqual([job.output_index for job in jobs], [4, 5, 6])
        self.assertTrue(all(job.action == "remux" for job in jobs))

    def test_container_only_difference_uses_remux(self) -> None:
        file = _plain_video().__class__(**{**_plain_video().__dict__, "path": Path("clip.mkv"), "container": "matroska"})
        action = choose_preprocess_action(
            file,
            Canvas(1280, 720),
            30.0,
            CodecPlan("h264", "aac", "libx264", "aac"),
            AudioTarget("aac", "aac", 48000, 2, "128k"),
        )

        self.assertEqual(action, "remux")

    def test_audio_only_difference_does_not_request_video_transcode(self) -> None:
        file = _plain_video().__class__(**{**_plain_video().__dict__, "audio_sample_rate": 44100})
        action = choose_preprocess_action(
            file,
            Canvas(1280, 720),
            30.0,
            CodecPlan("h264", "aac", "libx264", "aac"),
            AudioTarget("aac", "aac", 48000, 2, "128k"),
        )

        self.assertEqual(action, "audio")

    def test_validation_rejects_truncated_preprocessed_output(self) -> None:
        source = _plain_video()
        truncated = source.__class__(**{**source.__dict__, "path": Path("out.mp4"), "duration": 8.0})

        with patch("videomerge.transcode.probe_file", return_value=truncated):
            with self.assertRaises(CommandError):
                validate_preprocessed_output(
                    Path("out.mp4"),
                    source,
                    Canvas(1280, 720),
                    ToolPaths(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe")),
                    logging.getLogger("test"),
                )

    def test_preflight_rejects_estimated_size_blowup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "source.mp4"
            path.write_bytes(b"x" * 1024 * 1024)
            file = replace(_plain_video(), path=path, duration=10.0, video_bitrate=100_000_000)

            with self.assertRaises(CommandError):
                _log_size_estimate(
                    [file],
                    [PreprocessSegment(files=[file], action="transcode")],
                    None,
                    100_000_000,
                    AudioTarget("aac", "aac", 48000, 2, "128k"),
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
        video_time_base="1/15360",
    )
