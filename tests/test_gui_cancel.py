from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from videomerge.gui import HTML, GuiState, _cleanup_cancel_temp_dirs


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


if __name__ == "__main__":
    unittest.main()
