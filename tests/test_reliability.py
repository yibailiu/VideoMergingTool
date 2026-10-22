from __future__ import annotations

import logging
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from videomerge.errors import CommandError, VideoMergeError
from videomerge.models import ToolPaths, MergeMode, Canvas, CodecPlan
from videomerge.transcode import preprocess_group
from videomerge.gpu import GpuMode, GpuPlan
from videomerge.reliability import HealthResult, TaskRun, check_video, current_run, filter_checked_inputs
from videomerge.merge import concat_copy, _publish_no_replace
from test_merge_validation import _video

TOOLS = ToolPaths(Path("ffmpeg"), Path("ffprobe"))
LOGGER = logging.getLogger("reliability-test")


class ReliabilityTests(unittest.TestCase):
    def test_gpu_failure_retries_with_cpu_without_skipping_healthy_source(self):
        file = _video(Path("source.mp4"), 10)
        run = TaskRun("skip", "basic", LOGGER)
        token = current_run.set(run)
        gpu = GpuPlan(GpuMode.nvenc, "h264_nvenc", {"h264_nvenc"}, "test")
        encoders = []
        def process(output_path, codec_plan, gpu_plan, **kwargs):
            encoders.append(codec_plan.output_video_encoder)
            if gpu_plan:
                raise CommandError("GPU device failed to initialize")
            return output_path
        owner = None
        try:
            with patch("videomerge.transcode.preprocess_file", side_effect=process):
                outputs, owner = preprocess_group([file], Canvas(640, 360), 30, CodecPlan("h264", "aac", "h264_nvenc", "aac"), TOOLS, LOGGER, "black", 23, "medium", False, False, gpu_plan=gpu)
            self.assertEqual(encoders, ["h264_nvenc", "libx264"])
            self.assertEqual(len(outputs), 1)
            self.assertFalse(run.skipped)
        finally:
            if owner:
                owner.cleanup()
            current_run.reset(token)

    def test_fatal_parallel_failure_cancels_remaining_queue(self):
        files = [replace(_video(Path(f"{index}.mkv"), 10), container="matroska", audio_codec="mp3") for index in range(6)]
        run = TaskRun("stop", "basic", LOGGER)
        token = current_run.set(run)
        called = []
        def process(file, output_path, **kwargs):
            called.append(file.path.name)
            if file.path.name == "0.mkv":
                raise CommandError("Permission denied")
            run.abort_event.wait(2)
            return output_path
        try:
            with patch("videomerge.transcode.preprocess_file", side_effect=process):
                with self.assertRaises(CommandError):
                    preprocess_group(files, Canvas(1280, 720), 30, CodecPlan("h264", "aac", "libx264", "aac"), TOOLS, LOGGER, "black", 23, "medium", False, False)
            self.assertTrue(run.abort_event.is_set())
            self.assertLessEqual(len(called), 2)
            self.assertNotIn("5.mkv", called)
        finally:
            current_run.reset(token)

    def test_publication_never_overwrites_an_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "staged.mp4", Path(directory) / "result.mp4"
            source.write_bytes(b"new")
            target.write_bytes(b"previous")
            with self.assertRaises(FileExistsError):
                _publish_no_replace(source, target)
            self.assertEqual(target.read_bytes(), b"previous")
            self.assertEqual(source.read_bytes(), b"new")

    def test_failed_preprocess_skips_only_that_source_and_keeps_parallel_order(self):
        files = [replace(_video(Path(name), 10), container="matroska", audio_codec="mp3") for name in ("first.mkv", "bad.mkv", "last.mkv")]
        run = TaskRun("skip", "basic", LOGGER)
        token = current_run.set(run)
        def process(file, output_path, **kwargs):
            if file.path.name == "bad.mkv":
                raise CommandError("Invalid data found when processing input")
            return output_path
        def inspect(file, *args):
            return HealthResult(str(file.path), "error", "full", "corrupt input")
        owner = None
        try:
            with patch("videomerge.transcode.preprocess_file", side_effect=process), patch("videomerge.reliability.check_video", side_effect=inspect):
                outputs, owner = preprocess_group(files, Canvas(1280, 720), 30, CodecPlan("h264", "aac", "libx264", "aac"), TOOLS, LOGGER, "black", 23, "medium", False, False)
            self.assertEqual([run.sources[path].path.name for path in outputs], ["first.mkv", "last.mkv"])
            self.assertEqual(list(run.skipped), ["bad.mkv"])
        finally:
            if owner:
                owner.cleanup()
            current_run.reset(token)

    def test_quick_checks_three_intervals_and_full_has_no_sampling_limit(self):
        with patch("videomerge.reliability.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as execute:
            self.assertEqual(check_video(_video(Path("a.mp4"), 60), TOOLS).status, "passed")
            self.assertEqual(execute.call_count, 3)
            self.assertEqual([call.args[0][call.args[0].index("-ss") + 1] for call in execute.call_args_list[1:]], ["30.000", "57.000"])
            execute.reset_mock()
            check_video(_video(Path("a.mp4"), 60), TOOLS, "full")
            self.assertEqual(execute.call_count, 1)
            self.assertNotIn("-t", execute.call_args.args[0])

    def test_timeout_is_not_reported_as_confirmed_corruption(self):
        with patch("videomerge.reliability.subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 30)):
            result = check_video(_video(Path("a.mp4"), 60), TOOLS)
        self.assertEqual(result.status, "unknown")

    def test_skip_retains_healthy_input_order_and_stop_rejects_bad_input(self):
        files = [_video(Path(name), 10) for name in ("a.mp4", "bad.mp4", "b.mp4")]
        def inspect(file, *args):
            return HealthResult(str(file.path), "error" if file.path.name == "bad.mp4" else "passed", "quick", "Invalid data")
        with patch("videomerge.reliability.check_video", side_effect=inspect):
            run = TaskRun("skip", "quick", LOGGER)
            self.assertEqual([file.path.name for file in filter_checked_inputs(files, TOOLS, run)], ["a.mp4", "b.mp4"])
            self.assertEqual(len(run.skipped), 1)
            with self.assertRaises(VideoMergeError):
                filter_checked_inputs(files, TOOLS, TaskRun("stop", "quick", LOGGER))

    def test_output_permission_failure_does_not_skip_source(self):
        run = TaskRun("skip", "basic", LOGGER)
        with patch("videomerge.reliability.check_video") as inspect:
            self.assertFalse(run.recover_input(_video(Path("a.mp4"), 10), TOOLS, CommandError("Permission denied")))
        inspect.assert_not_called()
        self.assertEqual(run.skipped, {})

    def test_unknown_check_stops_even_with_skip_policy(self):
        with patch("videomerge.reliability.check_video", return_value=HealthResult("a.mp4", "unknown", "quick", "Timed out")):
            with self.assertRaises(VideoMergeError):
                filter_checked_inputs([_video(Path("a.mp4"), 10)], TOOLS, TaskRun("skip", "quick", LOGGER))

    def test_atomic_output_preserves_previous_destination_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.mp4"
            output.write_bytes(b"existing result")
            with patch("videomerge.merge._concat_copy_once", side_effect=CommandError("encoder failed")):
                with self.assertRaises(CommandError):
                    concat_copy([Path("a.mp4")], output, TOOLS, LOGGER, MergeMode.fast, True, False)
            self.assertEqual(output.read_bytes(), b"existing result")
            self.assertEqual(list(Path(directory).glob("*.partial.mp4")), [])

    def test_concat_recovery_removes_only_confirmed_bad_inputs_and_recalculates_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ("a.mp4", "bad.mp4", "b.mp4")]
            for path in paths:
                path.write_bytes(b"source")
            run = TaskRun("skip", "basic", LOGGER)
            run.sources = {path: _video(path, 10) for path in paths}
            token = current_run.set(run)
            durations = []
            def concat(inputs, staging, *args):
                durations.append(args[6])
                if len(inputs) == 3:
                    raise CommandError("Invalid data found when processing input")
                staging.write_bytes(b"complete")
            def inspect(file, *args):
                return HealthResult(str(file.path), "error" if file.path.name == "bad.mp4" else "passed", "full", "Invalid data")
            try:
                with patch("videomerge.merge._concat_copy_once", side_effect=concat), patch("videomerge.reliability.check_video", side_effect=inspect):
                    result = concat_copy(paths, Path(directory) / "result.mp4", TOOLS, LOGGER, MergeMode.fast, False, False)
                self.assertEqual(result.files, [paths[0], paths[2]])
                self.assertEqual(durations, [30, 20])
            finally:
                current_run.reset(token)


if __name__ == "__main__":
    unittest.main()
