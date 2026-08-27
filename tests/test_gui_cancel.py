from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from videomerge.gui import HTML, GuiState, _cleanup_cancel_temp_dirs, _is_useful_process_log


class GuiCancelTests(unittest.TestCase):
    def test_begin_run_rejects_second_running_task(self) -> None:
        state = GuiState()

        self.assertTrue(state.begin_run())
        self.assertFalse(state.begin_run())

    def test_cancel_running_process_terminates_process(self) -> None:
        state = GuiState()
        process = Mock()
        process.poll.return_value = None

        self.assertTrue(state.begin_run())
        state.start_process(process)
        with patch("videomerge.gui._terminate_process") as terminate:
            self.assertTrue(state.cancel_running_process())

        terminate.assert_called_once_with(process)
        self.assertTrue(state.finish_process())

    def test_cancel_before_process_exists_is_remembered(self) -> None:
        state = GuiState()

        self.assertTrue(state.begin_run())
        self.assertTrue(state.cancel_running_process())

        process = Mock()
        self.assertTrue(state.start_process(process))

    def test_cancel_cleanup_removes_recorded_temp_dirs_when_keep_temp_is_disabled(self) -> None:
        state = GuiState()
        state.begin_run(cleanup_temp_on_cancel=True)
        state.record_temp_path(Path("/tmp/videomerge_preprocess_test"))

        with patch("videomerge.gui.Path.exists", return_value=True), patch("videomerge.gui.shutil.rmtree") as rmtree:
            _cleanup_cancel_temp_dirs(state)

        rmtree.assert_called_once_with(Path("/tmp/videomerge_preprocess_test"))

    def test_cancel_cleanup_skips_when_keep_temp_is_enabled(self) -> None:
        state = GuiState()
        state.begin_run(cleanup_temp_on_cancel=False)
        state.record_temp_path(Path("/tmp/videomerge_preprocess_test"))

        with patch("videomerge.gui.shutil.rmtree") as rmtree:
            _cleanup_cancel_temp_dirs(state)

        rmtree.assert_not_called()

    def test_frontend_sends_api_token_header(self) -> None:
        self.assertIn("X-VideoMergingTool-Token", HTML)
        self.assertIn("__API_TOKEN__", HTML)

    def test_gui_state_retains_complete_logs_and_supports_incremental_reads(self) -> None:
        state = GuiState()
        for index in range(450):
            state.log(f"line {index}")

        first = state.snapshot(0)
        tail = state.snapshot(445)

        self.assertEqual(len(first["logs"]), 450)
        self.assertEqual(first["log_cursor"], 450)
        self.assertEqual(len(tail["logs"]), 5)

    def test_process_console_filters_progress_and_internal_temp_paths(self) -> None:
        self.assertFalse(_is_useful_process_log("INFO: Progress: 1/3 (33%) preprocessed a.mp4"))
        self.assertFalse(_is_useful_process_log("INFO: Preprocessing temp directory: /tmp/internal"))
        self.assertTrue(_is_useful_process_log("INFO: Preprocess decision: transcode a.mp4"))

    def test_frontend_has_direct_file_picker_and_stable_visual_orientation_map(self) -> None:
        self.assertIn('id="selectFiles"', HTML)
        self.assertIn("sourceFiles: []", HTML)
        self.assertIn("state.visualOrientations.get(file.path) || file.orientation", HTML)
        self.assertIn("/status?after=${state.logCursor}", HTML)


if __name__ == "__main__":
    unittest.main()
