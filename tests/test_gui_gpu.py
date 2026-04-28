from __future__ import annotations

import unittest

from videomerge.gui import _build_merge_command


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


if __name__ == "__main__":
    unittest.main()
