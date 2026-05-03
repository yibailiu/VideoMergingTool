from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from videomerge.gui import _build_merge_command, _detect_gui_ffmpeg_encoders


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

    def test_macos_gui_encoder_detection_retries_until_videotoolbox_is_seen(self) -> None:
        tools = Mock()
        with patch("videomerge.gui.platform.system", return_value="Darwin"), patch(
            "videomerge.gui.detect_ffmpeg_encoders",
            side_effect=[{"libx264"}, {"libx264", "h264_videotoolbox"}],
        ) as detect, patch("videomerge.gui.time.sleep"):
            encoders = _detect_gui_ffmpeg_encoders(tools)

        self.assertIn("h264_videotoolbox", encoders)
        self.assertEqual(detect.call_count, 2)


if __name__ == "__main__":
    unittest.main()
