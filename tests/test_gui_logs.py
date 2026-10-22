import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from videomerge.gui import GuiState, _copy_text_to_clipboard, _make_handler, _open_desktop_window


class GuiLogTests(unittest.TestCase):
    def test_scan_uses_canonical_paths_matching_cli_check_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "child").mkdir()
            source = root / "clip.mp4"
            source.touch()
            handler = object.__new__(_make_handler(GuiState(), "secret"))
            handler._send_json = Mock()
            with patch("videomerge.gui.resolve_tools"), patch("videomerge.gui.probe_files", return_value=([], {})) as probe:
                handler._scan({"input_dir": str(root / "child" / "..")})
            self.assertEqual(probe.call_args.args[0], [source.resolve()])

    def test_full_logs_include_gui_errors_and_entire_process_file(self):
        state = GuiState()
        state.log("启动错误：中文 'quotes' $text")
        with tempfile.TemporaryDirectory() as directory:
            state.log_path = Path(directory) / "process.log"
            state.log_path.write_text("媒体诊断\n" * 5000 + "last error", encoding="utf-8")
            text = state.full_log_text()
        self.assertIn("启动错误", text)
        self.assertIn("last error", text)
        self.assertEqual(text.count("媒体诊断"), 5000)

    def test_new_run_does_not_reuse_previous_log_file(self):
        state = GuiState()
        state.log_path = Path("previous.log")
        state.begin_run()
        self.assertIsNone(state.log_path)

    def test_windows_clipboard_uses_unicode_stdin_not_script_interpolation(self):
        text = "中文\n'quoted' $variable `tick`"
        with patch("videomerge.gui.platform.system", return_value="Windows"), patch("videomerge.gui.subprocess.run") as execute:
            _copy_text_to_clipboard(text)
        self.assertEqual(execute.call_args.kwargs["input"], text)
        self.assertEqual(execute.call_args.kwargs["encoding"], "utf-8")
        self.assertIn("-STA", execute.call_args.args[0])
        self.assertNotIn(text, execute.call_args.args[0][-1])

    def test_copy_endpoint_returns_all_text_on_clipboard_failure(self):
        state = GuiState()
        state.log("完整错误日志")
        handler = object.__new__(_make_handler(state, "secret"))
        handler.headers = {"X-VideoMergingTool-Token": "secret"}
        handler.path = "/copy-logs"
        handler._read_json = Mock(return_value={})
        handler._send_json = Mock()
        with patch("videomerge.gui._copy_text_to_clipboard", side_effect=RuntimeError("denied")):
            handler.do_POST()
        result = handler._send_json.call_args.args[0]
        self.assertFalse(result["copied"])
        self.assertIn("完整错误日志", result["text"])

    def test_copy_endpoint_requires_authentication(self):
        handler = object.__new__(_make_handler(GuiState(), "secret"))
        handler.headers = {}
        handler.path = "/copy-logs"
        handler._send_json = Mock()
        with patch("videomerge.gui._copy_text_to_clipboard") as copy:
            handler.do_POST()
        copy.assert_not_called()
        self.assertEqual(handler._send_json.call_args.args[1], 403)

    def test_macos_clipboard_preserves_unicode(self):
        with patch("videomerge.gui.platform.system", return_value="Darwin"), patch("videomerge.gui.subprocess.run") as execute:
            _copy_text_to_clipboard("完整日志\n最后一行")
        self.assertEqual(execute.call_args.args[0], ["pbcopy"])
        self.assertEqual(execute.call_args.kwargs["input"], "完整日志\n最后一行")

    def test_linux_clipboard_unavailable_raises_for_manual_fallback(self):
        with patch("videomerge.gui.platform.system", return_value="Linux"), patch("videomerge.gui.shutil.which", return_value=None):
            with self.assertRaises(RuntimeError):
                _copy_text_to_clipboard("full log")

    def test_copy_endpoint_passes_complete_text_to_native_clipboard(self):
        state = GuiState()
        state.log("完整错误日志")
        handler = object.__new__(_make_handler(state, "secret"))
        handler.headers = {"X-VideoMergingTool-Token": "secret"}
        handler.path = "/copy-logs"
        handler._read_json = Mock(return_value={})
        handler._send_json = Mock()
        with patch("videomerge.gui._copy_text_to_clipboard") as copy:
            handler.do_POST()
        copy.assert_called_once_with(state.full_log_text())
        self.assertEqual(handler._send_json.call_args.args[0], {"copied": True})

    def test_desktop_window_allows_text_selection(self):
        webview = types.SimpleNamespace(create_window=Mock(), start=Mock())
        with patch.dict(sys.modules, {"webview": webview}):
            _open_desktop_window("http://127.0.0.1:1")
        self.assertTrue(webview.create_window.call_args.kwargs["text_select"])
