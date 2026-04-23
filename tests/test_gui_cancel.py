from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from videomerge.gui import GuiState


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


if __name__ == "__main__":
    unittest.main()
