from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from videomerge.gui import _default_display_paths, _load_gui_config, _normalize_picked_folder, _pick_folder, _save_gui_config


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
            return_value=None,
        ), patch("videomerge.gui._pick_folder_tk", return_value="C:/Videos") as pick_tk:
            selected = _pick_folder("source")

        self.assertEqual(selected, "C:/Videos")
        pick_tk.assert_called_once_with("Select source video folder")

    def test_windows_cancel_does_not_open_fallback_picker(self) -> None:
        with patch("videomerge.gui.platform.system", return_value="Windows"), patch(
            "videomerge.gui._pick_folder_windows",
            return_value="",
        ), patch("videomerge.gui._pick_folder_tk") as pick_tk:
            selected = _pick_folder("source")

        self.assertEqual(selected, "")
        pick_tk.assert_not_called()

    def test_macos_uses_osascript_folder_picker(self) -> None:
        with patch("videomerge.gui.platform.system", return_value="Darwin"), patch(
            "videomerge.gui._pick_folder_macos",
            return_value="/Users/example/Videos",
        ) as pick_macos, patch("videomerge.gui._pick_folder_tk") as pick_tk:
            selected = _pick_folder("output")

        self.assertEqual(selected, "/Users/example/Videos")
        pick_macos.assert_called_once_with("Select output folder")
        pick_tk.assert_not_called()

    def test_config_save_keeps_custom_output_and_temp_but_not_name_or_source(self) -> None:
        with patch("videomerge.gui._config_path", return_value=Path("/tmp/vmt-test-config.json")) as config_path:
            path = config_path.return_value
            try:
                _save_gui_config(
                    {
                        "lang": "zh",
                        "mode": "fast",
                        "format": "mkv",
                        "name": "DoNotRemember",
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
        self.assertEqual(loaded["outputDir"], "/private/output")
        self.assertEqual(loaded["tempDir"], "/private/temp")
        self.assertNotIn("name", loaded)
        self.assertNotIn("inputDir", loaded)

    def test_temp_folder_uses_temp_dialog_title(self) -> None:
        with patch("videomerge.gui.platform.system", return_value="Windows"), patch(
            "videomerge.gui._pick_folder_windows",
            return_value="C:/Temp",
        ) as pick_windows:
            selected = _pick_folder("temp")

        self.assertEqual(selected, "C:/Temp")
        pick_windows.assert_called_once_with("Select temp folder")

    def test_windows_picker_uses_custom_browser_with_current_folder_button(self) -> None:
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
        self.assertIn("System.Windows.Forms.ListView", commands[0])
        self.assertIn("Select This Folder", commands[0])
        self.assertIn("Get-ChildItem", commands[0])
        self.assertIn("OutputEncoding", commands[0])
        self.assertNotIn("OpenFileDialog", commands[0])

    def test_normalize_picked_folder_strips_placeholder_name(self) -> None:
        self.assertEqual(
            _normalize_picked_folder("C:/Videos/Select this folder"),
            "C:/Videos",
        )

    def test_default_display_paths_include_temp_and_source_output_folder(self) -> None:
        with patch("videomerge.gui.resolve_tools", side_effect=RuntimeError("missing")):
            defaults = _default_display_paths("/tmp")

        self.assertEqual(defaults["output_dir"], "/tmp/merged")
        self.assertTrue(defaults["temp_dir"])
        self.assertIn("ffmpeg", defaults)
        self.assertIn("ffprobe", defaults)


if __name__ == "__main__":
    unittest.main()
