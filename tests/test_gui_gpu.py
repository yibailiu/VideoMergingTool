from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from videomerge.gui import _build_merge_command, _detect_gui_ffmpeg_encoders, _serialize_files, _windows_notification_script
from videomerge.models import Orientation, VideoFile


class GuiGpuTests(unittest.TestCase):
    def test_gui_command_includes_gpu_option(self) -> None:
        command = _build_merge_command({"input_dir": "/tmp/in", "gpu": "auto"})

        self.assertIn("--gpu", command)
        self.assertEqual(command[command.index("--gpu") + 1], "auto")

    def test_gui_command_includes_temp_dir_option(self) -> None:
        command = _build_merge_command({"input_dir": "/tmp/in", "temp_dir": "/tmp/videomerge"})

        self.assertIn("--temp-dir", command)
        self.assertEqual(command[command.index("--temp-dir") + 1], "/tmp/videomerge")

    def test_gui_command_includes_sort_option(self) -> None:
        command = _build_merge_command({"input_dir": "/tmp/in", "sort_by": "modified-desc"})

        self.assertIn("--sort-by", command)
        self.assertEqual(command[command.index("--sort-by") + 1], "modified-desc")

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

    def test_serialize_files_includes_filesystem_time_and_size(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "clip.mp4"
            path.write_bytes(b"x" * 1536)
            serialized = _serialize_files([_video(path)])[0]

        self.assertIn("modified_time", serialized)
        self.assertIn("file_time", serialized)
        self.assertEqual(serialized["file_size"], "1.5 KB")
        self.assertEqual(serialized["file_size_bytes"], 1536)

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

def _video(path: Path) -> VideoFile:
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
    )


if __name__ == "__main__":
    unittest.main()
