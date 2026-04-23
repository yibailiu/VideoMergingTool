from __future__ import annotations

import logging
import unittest

from videomerge.cli import _log_merge_summary


class SummaryLogTests(unittest.TestCase):
    def test_summary_reports_total_merged_and_unmerged_counts(self) -> None:
        logger = logging.getLogger("summary-test")

        with self.assertLogs(logger, level="INFO") as captured:
            _log_merge_summary(total_video_count=12, merged_video_count=9, logger=logger)

        self.assertIn(
            "directory contains 12 video(s), 9 video(s) were merged, 3 video(s) were not merged",
            captured.output[0],
        )


if __name__ == "__main__":
    unittest.main()
