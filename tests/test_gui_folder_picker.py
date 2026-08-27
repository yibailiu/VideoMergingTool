from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from videomerge.gui import (
    _default_display_paths,
    _last_picker_dir,
    _load_gui_config,
    _normalize_picked_folder,
    _normalize_picked_video_files,
    _common_input_dir,
    _pick_folder,
    _pick_video_files,
    _pick_video_files_windows,
    _save_gui_config,
    _validate_selected_source_files,
)


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
        pick_windows.assert_called_once_with("Select source video folder", "")
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
        pick_windows.assert_called_once_with("Select temp folder", "")

    def test_windows_picker_uses_native_file_explorer_dialog(self) -> None:
        commands = []

        def fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
            commands.append(args[-1])
            return type("Result", (), {"returncode": 0, "stdout": "C:/Videos/Select this folder\n"})()

        with patch("videomerge.gui.platform.system", return_value="Windows"), patch(
            "videomerge.gui.subprocess.run",
            side_effect=fake_run,
        ):
            selected = _pick_folder("source")

        self.assertEqual(selected, "C:/Videos")
        self.assertIn("System.Windows.Forms.OpenFileDialog", commands[0])
        self.assertIn("CheckFileExists = $false", commands[0])
        self.assertIn("ValidateNames = $false", commands[0])
        self.assertIn("FileName = 'Select this folder'", commands[0])
        self.assertIn("All files (*.*)|*.*", commands[0])
        self.assertIn("OutputEncoding", commands[0])
        self.assertNotIn("System.Windows.Forms.ListView", commands[0])

    def test_windows_picker_uses_remembered_existing_folder(self) -> None:
        with patch("videomerge.gui._config_path", return_value=Path("/tmp/vmt-picker-config.json")) as config_path:
            path = config_path.return_value
            try:
                _save_gui_config({"lastPickerDirs": {"source": "/tmp"}})
                with patch("videomerge.gui.platform.system", return_value="Windows"), patch(
                    "videomerge.gui._pick_folder_windows",
                    return_value="C:/Videos",
                ) as pick_windows:
                    selected = _pick_folder("source")
            finally:
                path.unlink(missing_ok=True)

        self.assertEqual(selected, "C:/Videos")
        pick_windows.assert_called_once_with("Select source video folder", "/tmp")

    def test_last_picker_dir_falls_back_to_existing_parent(self) -> None:
        with patch("videomerge.gui._config_path", return_value=Path("/tmp/vmt-picker-config.json")) as config_path:
            path = config_path.return_value
            try:
                _save_gui_config({"lastPickerDirs": {"source": "/tmp/vmt-missing/child"}})
                selected = _last_picker_dir("source")
            finally:
                path.unlink(missing_ok=True)

        self.assertEqual(selected, "/tmp")

    def test_windows_picker_cancel_returns_empty_without_fallback(self) -> None:
        def fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
            return type("Result", (), {"returncode": 0, "stdout": ""})()

        with patch("videomerge.gui.platform.system", return_value="Windows"), patch(
            "videomerge.gui.subprocess.run",
            side_effect=fake_run,
        ), patch("videomerge.gui._pick_folder_tk") as pick_tk:
            selected = _pick_folder("source")

        self.assertEqual(selected, "")
        pick_tk.assert_not_called()

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

    def test_video_file_picker_supports_multiple_files_and_filters_non_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "clip10.mp4"
            second = root / "clip2.mov"
            ignored = root / "notes.txt"
            for path in (first, second, ignored):
                path.touch()
            with patch("videomerge.gui.platform.system", return_value="Darwin"), patch(
                "videomerge.gui._pick_video_files_macos",
                return_value=[str(first), str(second), str(ignored), str(first)],
            ), patch("videomerge.gui._remember_picker_dir"):
                selected = _pick_video_files()

        self.assertEqual(selected, [str(first.resolve()), str(second.resolve())])

    def test_windows_video_picker_enables_multi_select(self) -> None:
        captured_script = []

        def fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
            captured_script.append(args[-1])
            return type("Result", (), {"returncode": 0, "stdout": "C:/Videos/a.mp4\nC:/Videos/b.mkv\n"})()

        with patch("videomerge.gui.subprocess.run", side_effect=fake_run):
            selected = _pick_video_files_windows("Select videos", "C:/Videos")

        self.assertEqual(selected, ["C:/Videos/a.mp4", "C:/Videos/b.mkv"])
        self.assertIn("Multiselect = $true", captured_script[0])
        self.assertIn("*.mp4;*.mkv", captured_script[0])

    def test_selected_source_files_are_validated_and_sorted_without_directory_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            later = root / "clip10.mp4"
            earlier = root / "clip2.mp4"
            later.touch()
            earlier.touch()

            selected = _validate_selected_source_files(
                [str(later), str(earlier)],
                root,
                "name-natural-asc",
            )

        self.assertEqual(selected, [earlier.resolve(), later.resolve()])
        self.assertEqual(_common_input_dir([str(earlier), str(later)]), str(root))

    def test_normalize_picked_video_files_rejects_missing_and_duplicate_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "clip.mp4"
            source.touch()
            normalized = _normalize_picked_video_files(
                [str(source), str(source), str(Path(temp_dir) / "missing.mp4")]
            )

        self.assertEqual(normalized, [str(source.resolve())])


if __name__ == "__main__":
    unittest.main()
