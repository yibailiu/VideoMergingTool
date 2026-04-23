from __future__ import annotations

import unittest

from videomerge.gui import _build_merge_command


class GuiGpuTests(unittest.TestCase):
    def test_gui_command_includes_gpu_option(self) -> None:
        command = _build_merge_command({"input_dir": "/tmp/in", "gpu": "auto"})

        self.assertIn("--gpu", command)
        self.assertEqual(command[command.index("--gpu") + 1], "auto")


if __name__ == "__main__":
    unittest.main()
