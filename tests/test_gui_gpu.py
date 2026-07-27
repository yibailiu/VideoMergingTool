from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from videomerge.gui import (
    HTML,
    _build_gui_plan,
    _build_merge_command,
    _detect_gui_ffmpeg_encoders,
    _open_media_file,
    _serialize_files,
    _windows_notification_script,
)
from videomerge.models import Orientation, VideoFile


class GuiGpuTests(unittest.TestCase):
    def test_gui_template_keeps_orientation_group_headers(self) -> None:
        self.assertIn('class="group-row ${groupKey}"', HTML)
        self.assertIn('orientationLandscape: "Landscape Videos"', HTML)
        self.assertIn('orientationPortrait: "Portrait Videos"', HTML)
        self.assertIn("横竖分组仅用于查看；实际合并仍按所选规则统一排序。", HTML)
        self.assertIn(
            "function mergeOrderedFiles() {\n"
            "      return state.files.filter(file => state.selectedPaths.has(file.path));\n"
            "    }",
            HTML,
        )

    def test_gui_command_includes_gpu_option(self) -> None:
        command = _build_merge_command({"input_dir": "/tmp/in", "gpu": "auto"})

        self.assertIn("--gpu", command)
        self.assertEqual(command[command.index("--gpu") + 1], "auto")

    def test_gui_command_includes_gpu_worker_limit(self) -> None:
        command = _build_merge_command({"input_dir": "/tmp/in", "gpu_workers": 1})

        self.assertEqual(command[command.index("--gpu-workers") + 1], "1")

    def test_gui_command_includes_temp_dir_option(self) -> None:
        command = _build_merge_command({"input_dir": "/tmp/in", "temp_dir": "/tmp/videomerge"})

        self.assertIn("--temp-dir", command)
        self.assertEqual(command[command.index("--temp-dir") + 1], "/tmp/videomerge")

    def test_gui_command_includes_sort_option(self) -> None:
        command = _build_merge_command({"input_dir": "/tmp/in", "sort_by": "media-created-desc"})

        self.assertIn("--sort-by", command)
        self.assertEqual(command[command.index("--sort-by") + 1], "media-created-desc")

    def test_gui_command_includes_quality_profile(self) -> None:
        command = _build_merge_command({"input_dir": "/tmp/in", "quality_profile": "small", "crf": 25})

        self.assertIn("--quality-profile", command)
        self.assertEqual(command[command.index("--quality-profile") + 1], "small")
        self.assertEqual(command[command.index("--crf") + 1], "25")

    def test_gui_command_writes_selected_file_list(self) -> None:
        command = _build_merge_command({"input_dir": "/tmp/in", "selected_files": ["/tmp/in/a.mp4", "/tmp/in/b.mp4"]})
        try:
            list_path = Path(command[command.index("--selected-files") + 1])
            selected = json.loads(list_path.read_text(encoding="utf-8"))
        finally:
            if "--selected-files" in command:
                Path(command[command.index("--selected-files") + 1]).unlink(missing_ok=True)

        self.assertEqual(selected, ["/tmp/in/a.mp4", "/tmp/in/b.mp4"])

    def test_gui_command_writes_ordered_rotation_adjustments(self) -> None:
        command = _build_merge_command(
            {
                "input_dir": "/tmp/in",
                "selected_files": ["/tmp/in/b.mp4", "/tmp/in/a.mp4"],
                "rotation_overrides": {"/tmp/in/a.mp4": 90},
            }
        )
        try:
            list_path = Path(command[command.index("--selected-files") + 1])
            selected = json.loads(list_path.read_text(encoding="utf-8"))
        finally:
            if "--selected-files" in command:
                Path(command[command.index("--selected-files") + 1]).unlink(missing_ok=True)

        self.assertEqual(
            selected,
            [
                {"path": "/tmp/in/b.mp4", "rotate_clockwise": 0},
                {"path": "/tmp/in/a.mp4", "rotate_clockwise": 90},
            ],
        )

    def test_serialize_files_includes_media_creation_date_and_file_size(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "clip.mp4"
            path.write_bytes(b"x" * 1536)
            serialized = _serialize_files([_video(path, media_created_at=100.0)])[0]

        self.assertTrue(serialized["media_created_time"])
        self.assertNotIn("modified_time", serialized)
        self.assertNotIn("created_time", serialized)
        self.assertEqual(serialized["file_size"], "1.5 KB")
        self.assertEqual(serialized["file_size_bytes"], 1536)

    def test_gui_optimal_status_uses_real_execution_plan(self) -> None:
        ready = [_video(Path(f"ready_{index}.mp4")) for index in range(3)]
        outlier = _video(Path("outlier.mp4")).__class__(
            **{
                **_video(Path("outlier.mp4")).__dict__,
                "width": 3840,
                "height": 2160,
                "display_width": 3840,
                "display_height": 2160,
                "video_bitrate": 15_000_000,
            }
        )

        payload = _build_gui_plan(ready + [outlier], ready + [outlier], {"mode": "optimal"})
        actions = {item["name"]: item["planned_action"] for item in payload["files"]}

        self.assertEqual(payload["plan"]["copy_count"], 3)
        self.assertEqual(payload["plan"]["transcode_count"], 1)
        self.assertEqual(actions["outlier.mp4"], "transcode")

    def test_gui_extreme_status_uses_four_way_execution_plan(self) -> None:
        ready = _video(Path("ready.mp4"))
        remux = _video(Path("container.mkv")).__class__(
            **{**_video(Path("container.mkv")).__dict__, "container": "matroska"}
        )

        payload = _build_gui_plan([ready, remux], [ready, remux], {"mode": "extreme"})
        actions = {item["name"]: item["planned_action"] for item in payload["files"]}

        self.assertEqual(payload["plan"]["copy_count"], 1)
        self.assertEqual(payload["plan"]["remux_count"], 1)
        self.assertEqual(payload["plan"]["transcode_count"], 0)
        self.assertEqual(actions["container.mkv"], "remux")

    def test_gui_plan_applies_manual_rotation_without_reordering_files(self) -> None:
        first = _video(Path("first.mp4"))
        second = _video(Path("second.mp4"))

        payload = _build_gui_plan(
            [first, second],
            [first, second],
            {
                "mode": "optimal",
                "rotation_overrides": {"second.mp4": 90},
            },
        )

        self.assertEqual([item["name"] for item in payload["files"]], ["first.mp4", "second.mp4"])
        rotated = payload["files"][1]
        self.assertEqual(rotated["manual_rotation"], 90)
        self.assertEqual((rotated["display_width"], rotated["display_height"]), (720, 1280))
        self.assertEqual(rotated["orientation"], "portrait")
        self.assertEqual(rotated["planned_action"], "transcode")

    def test_gui_fast_plan_marks_manual_rotation_as_blocked(self) -> None:
        video = _video(Path("clip.mp4"))

        payload = _build_gui_plan(
            [video],
            [video],
            {"mode": "fast", "rotation_overrides": {"clip.mp4": 90}},
        )

        self.assertEqual(payload["files"][0]["planned_action"], "rotation_required")
        self.assertEqual(payload["plan"]["rotation_blocked_count"], 1)

    def test_open_media_file_uses_macos_default_application(self) -> None:
        with patch("videomerge.gui.platform.system", return_value="Darwin"), patch(
            "videomerge.gui.subprocess.Popen"
        ) as popen:
            _open_media_file(Path("/tmp/clip.mp4"))

        self.assertEqual(popen.call_args.args[0], ["open", "/tmp/clip.mp4"])

    def test_open_media_file_uses_windows_file_association(self) -> None:
        with patch("videomerge.gui.platform.system", return_value="Windows"), patch(
            "videomerge.gui.os.startfile",
            create=True,
        ) as startfile:
            _open_media_file(Path("C:/clips/clip.mp4"))

        startfile.assert_called_once_with("C:/clips/clip.mp4")

    def test_windows_notification_script_uses_notify_icon_and_sound(self) -> None:
        script = _windows_notification_script("A&B's", "done", True)

        self.assertIn("System.Windows.Forms.NotifyIcon", script)
        self.assertIn("[System.Media.SystemSounds]::Asterisk.Play()", script)
        self.assertIn("A&B''s", script)

    def test_macos_gui_encoder_detection_retries_until_videotoolbox_is_seen(self) -> None:
        tools = Mock()
        with patch("videomerge.gui.platform.system", return_value="Darwin"), patch(
            "videomerge.gui.detect_ffmpeg_encoders",
            side_effect=[{"libx264"}, {"libx264", "h264_videotoolbox"}],
        ) as detect, patch("videomerge.gui.time.sleep"):
            encoders = _detect_gui_ffmpeg_encoders(tools)

        self.assertIn("h264_videotoolbox", encoders)
        self.assertEqual(detect.call_count, 2)

def _video(path: Path, media_created_at: float | None = None) -> VideoFile:
    return VideoFile(
        path=path,
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
        media_created_at=media_created_at,
    )


if __name__ == "__main__":
    unittest.main()
