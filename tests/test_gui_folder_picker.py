from __future__ import annotations

import unittest
from unittest.mock import patch

from videomerge.gui import _pick_folder


class GuiFolderPickerTests(unittest.TestCase):
    def test_windows_prefers_file_dialog_folder_picker(self) -> None:
        with patch("videomerge.gui.platform.system", return_value="Windows"), patch(
            "videomerge.gui._pick_folder_windows",
            return_value="C:/Videos",
        ) as pick_windows, patch("videomerge.gui._pick_folder_tk") as pick_tk, patch(
            "videomerge.gui._pick_folder_macos"
        ) as pick_macos:
            selected = _pick_folder("source")

        self.assertEqual(selected, "C:/Videos")
        pick_windows.assert_called_once_with("Select source video folder")
        pick_tk.assert_not_called()
        pick_macos.assert_not_called()

    def test_windows_falls_back_to_tk_folder_picker(self) -> None:
        with patch("videomerge.gui.platform.system", return_value="Windows"), patch(
            "videomerge.gui._pick_folder_windows",
            return_value="",
        ), patch("videomerge.gui._pick_folder_tk", return_value="C:/Videos") as pick_tk:
            selected = _pick_folder("source")

        self.assertEqual(selected, "C:/Videos")
        pick_tk.assert_called_once_with("Select source video folder")

    def test_macos_uses_osascript_folder_picker(self) -> None:
        with patch("videomerge.gui.platform.system", return_value="Darwin"), patch(
            "videomerge.gui._pick_folder_macos",
            return_value="/Users/example/Videos",
        ) as pick_macos, patch("videomerge.gui._pick_folder_tk") as pick_tk:
            selected = _pick_folder("output")

        self.assertEqual(selected, "/Users/example/Videos")
        pick_macos.assert_called_once_with("Select output folder")
        pick_tk.assert_not_called()


if __name__ == "__main__":
    unittest.main()
