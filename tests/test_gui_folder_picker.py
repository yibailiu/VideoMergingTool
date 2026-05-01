from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from videomerge.gui import _load_gui_config, _pick_folder, _save_gui_config


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

    def test_config_save_excludes_selected_folders(self) -> None:
        with patch("videomerge.gui._config_path", return_value=Path("/tmp/vmt-test-config.json")) as config_path:
            path = config_path.return_value
            try:
                _save_gui_config(
                    {
                        "lang": "zh",
                        "mode": "fast",
                        "format": "mkv",
                        "inputDir": "/private/source",
                        "outputDir": "/private/output",
                        "tempDir": "/private/temp",
                    }
                )
                loaded = _load_gui_config()
            finally:
                path.unlink(missing_ok=True)

        self.assertEqual(loaded["lang"], "zh")
        self.assertEqual(loaded["mode"], "fast")
        self.assertEqual(loaded["format"], "mkv")
        self.assertNotIn("inputDir", loaded)
        self.assertNotIn("outputDir", loaded)
        self.assertNotIn("tempDir", loaded)

    def test_windows_picker_does_not_hide_files_with_folder_filter(self) -> None:
        commands = []

        def fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
            commands.append(args[-1])
            return type("Result", (), {"returncode": 0, "stdout": "C:/Videos\n"})()

        with patch("videomerge.gui.platform.system", return_value="Windows"), patch(
            "videomerge.gui.subprocess.run",
            side_effect=fake_run,
        ):
            selected = _pick_folder("source")

        self.assertEqual(selected, "C:/Videos")
        self.assertIn("All files (*.*)|*.*", commands[0])
        self.assertNotIn("*.folder", commands[0])


if __name__ == "__main__":
    unittest.main()
