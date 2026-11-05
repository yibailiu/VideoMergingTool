from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from videomerge.errors import CommandError
from videomerge.models import Canvas, CodecPlan, ToolPaths
from videomerge.probe import probe_file
from videomerge.reliability import TaskRun, check_video, current_run
from videomerge.transcode import AudioTarget, is_audio_timestamp_failure, preprocess_file
from test_transcode_rotation import _plain_video


LOGGER = logging.getLogger("audio-timestamp-test")
TIMESTAMP_ERROR = ("[aac @ 123] Queue input is backward in time\n"
                   "[aost#0:1/aac @ 123] Non-monotonic DTS; previous: 5120, current: 5105; "
                   "Error submitting a packet to the muxer: Invalid argument")


class AudioTimestampTests(unittest.TestCase):
    def process(self, **kwargs):
        options = dict(file=replace(_plain_video(), audio_sample_rate=44100, audio_channels=1),
                       output_path=Path("out.mp4"), canvas=Canvas(1280, 720), fps=30,
                       codec_plan=CodecPlan("h264", "aac", "libx264", "aac"),
                       tools=ToolPaths(Path("ffmpeg"), Path("ffprobe")), logger=LOGGER,
                       pad_color="black", crf=23, preset="medium", dry_run=False,
                       audio_target=AudioTarget("aac", "aac", 48000, 2, "192k"))
        options.update(kwargs)
        return preprocess_file(**options)

    def test_only_audio_timestamp_errors_match(self):
        for message in (TIMESTAMP_ERROR, "[aost#0:1/aac @ 123] Non monotonically increasing DTS",
                        "Non-monotonous DTS in output stream 0:1; previous: 5120, current: 5105"):
            self.assertTrue(is_audio_timestamp_failure(message))
        for message in ("[vost#0:0/hevc @ 123] Non-monotonic DTS", "Non-monotonic DTS",
                        "Queue input is backward in time", "Non-monotonous DTS in output stream 0:0",
                        "Permission denied", "Invalid data found when processing input"):
            self.assertFalse(is_audio_timestamp_failure(message))

    def test_repairs_once_preserving_video_copy_and_strict_checks(self):
        with patch("videomerge.transcode.run_command", side_effect=[CommandError(TIMESTAMP_ERROR), None]) as run, \
                patch("videomerge.transcode.validate_preprocessed_output") as validate:
            self.process()
        self.assertEqual(run.call_count, 2)
        first, second = [call.args[0] for call in run.call_args_list]
        self.assertEqual(first[first.index("-af") + 1], "apad")
        self.assertEqual(second[second.index("-af") + 1],
                         "aresample=48000:async=1:first_pts=0,asetpts=N/SR/TB,apad")
        self.assertEqual(second[second.index("-c:v") + 1], "copy")
        self.assertIn("-xerror", second)
        self.assertIn("-shortest", second)
        validate.assert_called_once()

    def test_remux_failure_promotes_only_audio_to_encoding(self):
        with patch("videomerge.transcode.run_command", side_effect=[CommandError(TIMESTAMP_ERROR), None]) as run, \
                patch("videomerge.transcode.validate_preprocessed_output"):
            self.process(file=_plain_video(), force_remux=True)
        second = run.call_args_list[1].args[0]
        self.assertEqual(second[second.index("-c:v") + 1], "copy")
        self.assertEqual(second[second.index("-c:a") + 1], "aac")
        self.assertIn("-af", second)

    def test_healthy_audio_keeps_fast_path_and_gpu_encoder_is_preserved_on_repair(self):
        with patch("videomerge.transcode.run_command") as run, \
                patch("videomerge.transcode.validate_preprocessed_output"):
            self.process()
            self.assertEqual(run.call_count, 1)
        with patch("videomerge.transcode.run_command", side_effect=[CommandError(TIMESTAMP_ERROR), None]) as run, \
                patch("videomerge.transcode.validate_preprocessed_output"):
            self.process(codec_plan=CodecPlan("h264", "aac", "h264_nvenc", "aac"),
                         force_video_transcode=True)
        for call in run.call_args_list:
            args = call.args[0]
            self.assertEqual(args[args.index("-c:v") + 1], "h264_nvenc")

    def test_retry_is_bounded_and_failed_validation_is_not_hidden(self):
        with patch("videomerge.transcode.run_command", side_effect=CommandError(TIMESTAMP_ERROR)) as run:
            with self.assertRaises(CommandError):
                self.process()
            self.assertEqual(run.call_count, 2)
        with patch("videomerge.transcode.run_command", side_effect=[CommandError(TIMESTAMP_ERROR), None]), \
                patch("videomerge.transcode.validate_preprocessed_output", side_effect=CommandError("short output")):
            with self.assertRaisesRegex(CommandError, "short output"):
                self.process()

    def test_cancellation_and_system_errors_do_not_retry(self):
        task = TaskRun("stop", "basic", LOGGER)
        token = current_run.set(task)
        try:
            def cancel(*args, **kwargs):
                task.abort_event.set()
                raise CommandError(TIMESTAMP_ERROR)
            with patch("videomerge.transcode.run_command", side_effect=cancel) as run:
                with self.assertRaises(CommandError):
                    self.process()
                self.assertEqual(run.call_count, 1)
        finally:
            current_run.reset(token)
        for message in ("Permission denied", TIMESTAMP_ERROR + "\nNo space left on device"):
            with patch("videomerge.transcode.run_command", side_effect=CommandError(message)) as run:
                with self.assertRaises(CommandError):
                    self.process()
                self.assertEqual(run.call_count, 1)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools unavailable")
class AudioTimestampIntegrationTests(unittest.TestCase):
    def test_real_backward_audio_clock_recovers_without_dropping_streams(self):
        tools = ToolPaths(Path(shutil.which("ffmpeg")), Path(shutil.which("ffprobe")))
        with tempfile.TemporaryDirectory(prefix="vmt_audio_clock_") as directory:
            source, output = Path(directory) / "backward.mkv", Path(directory) / "fixed.mp4"
            # A small backwards step in PCM audio reproduces the reported AAC muxer error.
            subprocess.run([str(tools.ffmpeg), "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc2=size=160x120:rate=30:duration=3", "-f", "lavfi", "-i",
                            "sine=frequency=440:sample_rate=44100:duration=3", "-af",
                            "asetpts='PTS-if(gte(T,1),0.0235/TB,0)'", "-c:v", "mpeg4",
                            "-c:a", "pcm_s16le", "-f", "nut", str(source)], check=True, capture_output=True)
            file = probe_file(source, tools, LOGGER)
            with self.assertLogs(LOGGER, level="WARNING") as messages:
                preprocess_file(file, output, Canvas(160, 120), 30,
                                CodecPlan("mpeg4", "aac", "mpeg4", "aac"), tools, LOGGER,
                                "black", 23, "medium", False,
                                audio_target=AudioTarget("aac", "aac", 48000, 2, "192k"))
            self.assertEqual(sum("Audio timestamp discontinuity" in line for line in messages.output), 1)
            media = probe_file(output, tools, LOGGER)
            self.assertEqual((media.audio_sample_rate, media.audio_channels), (48000, 2))
            self.assertAlmostEqual(media.duration, 3, delta=0.1)
            self.assertEqual(check_video(media, tools, "full").status, "passed")
            report = subprocess.run([str(tools.ffprobe), "-v", "error", "-show_packets",
                                     "-show_streams", "-of", "json", str(output)], check=True, capture_output=True)
            data = json.loads(report.stdout)
            self.assertEqual(len(data["streams"]), 2)
            starts = [float(stream["start_time"]) for stream in data["streams"]]
            durations = [float(stream["duration"]) for stream in data["streams"]]
            self.assertLess(abs(starts[0] - starts[1]), 0.05)
            self.assertLess(abs(durations[0] - durations[1]), 0.1)
            for stream in (0, 1):
                dts = [int(p["dts"]) for p in data["packets"] if p["stream_index"] == stream]
                self.assertTrue(all(a < b for a, b in zip(dts, dts[1:])))
            # Exercise the complete task too: healthy / problematic / healthy, no skip.
            first, last = Path(directory) / "01.mp4", Path(directory) / "03.mp4"
            shutil.copyfile(output, first)
            shutil.copyfile(output, last)
            manifest, report_path = Path(directory) / "inputs.json", Path(directory) / "report.json"
            manifest.write_text(json.dumps([str(first), str(source), str(last)]), encoding="utf-8")
            merged = subprocess.run([sys.executable, "main.py", "merge", directory,
                                     "--selected-files", str(manifest), "--mode", "extreme",
                                     "--check-level", "quick", "--on-error", "stop",
                                     "--output-dir", str(Path(directory) / "merged"),
                                     "--report-file", str(report_path), "--ffmpeg-path", str(tools.ffmpeg),
                                     "--ffprobe-path", str(tools.ffprobe), "--no-auto-download-deps"],
                                    capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1])
            self.assertEqual(merged.returncode, 0, merged.stdout + merged.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["skipped"], [])
            self.assertEqual(len(report["outputs"]), 1)
            result = probe_file(Path(report["outputs"][0]), tools, LOGGER)
            self.assertAlmostEqual(result.duration, 9, delta=0.3)
