from __future__ import annotations

import unittest
import json
import tempfile
import sys
import threading
from pathlib import Path
from unittest.mock import Mock, patch

from videomerge.gui import GuiState, _cleanup_cancel_temp_dirs, _is_useful_process_log, _run_merge, _make_handler


class GuiCancelTests(unittest.TestCase):
    def test_cancellation_terminates_a_real_child_process_and_saves_cancelled_report(self):
        state = GuiState()
        state.begin_run()
        ready = threading.Event()
        original_start = state.start_process
        def started(process):
            result = original_start(process)
            ready.set()
            return result
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "result.json"
            command = [sys.executable, "-u", "-c", "import time; print('ready', flush=True); time.sleep(30)", "--report-file", str(report)]
            with patch.object(state, "start_process", side_effect=started):
                worker = threading.Thread(target=_run_merge, args=(command, state), daemon=True)
                worker.start()
                try:
                    self.assertTrue(ready.wait(3))
                    self.assertTrue(state.cancel_running_process())
                    worker.join(5)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["status"], "cancelled")
                finally:
                    state.cancel_running_process()
                    worker.join(3)

    def test_api_authentication_and_static_path_traversal_are_rejected(self):
        handler_type = _make_handler(GuiState(), "test-secret")
        handler = object.__new__(handler_type)
        handler.headers = {}
        handler._send_json = Mock()
        self.assertFalse(handler._authorized())
        self.assertEqual(handler._send_json.call_args.args[1], 403)
        handler.headers = {"X-VideoMergingTool-Token": "test-secret"}
        self.assertTrue(handler._authorized())
        handler.path = "/assets/../../cli.py"
        handler.send_error = Mock()
        handler.do_GET()
        handler.send_error.assert_called_once_with(404)

    def test_incremental_task_events_are_merged_and_saved_without_polluting_logs(self):
        events = [
            {"incremental": True, "status": "running", "checks": [{"path": "a", "status": "passed"}], "skipped": []},
            {"incremental": True, "status": "running", "checks": [{"path": "b", "status": "error"}], "skipped": [{"path": "b", "reason": "corrupt"}]},
        ]
        state = GuiState()
        state.begin_run()
        process = Mock()
        process.stdout = ["INFO: TASK_EVENT:" + json.dumps(event) for event in events]
        process.wait.return_value = 1
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "result.json"
            with patch("videomerge.gui.subprocess.Popen", return_value=process):
                _run_merge(["test", "--report-file", str(report)], state)
            result = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual([item["path"] for item in result["checks"]], ["a", "b"])
        self.assertEqual(result["skipped"][0]["path"], "b")
        self.assertEqual(result["status"], "failed")
        self.assertFalse(any("TASK_EVENT" in line for line in state.logs))

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


if __name__ == "__main__":
    unittest.main()
