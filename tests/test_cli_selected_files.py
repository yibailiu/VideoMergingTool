from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from videomerge.cli import _load_selected_video_files
from videomerge.errors import VideoMergeError


class CliSelectedFilesTests(unittest.TestCase):
    def test_load_selected_video_files_preserves_order_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "b.mp4"
            second = root / "a.mov"
            first.write_text("", encoding="utf-8")
            second.write_text("", encoding="utf-8")
            selected_file = root / "selected.json"
            selected_file.write_text(json.dumps([str(first), str(second), str(first)]), encoding="utf-8")

            selected = _load_selected_video_files(selected_file, root)

        self.assertEqual(selected, [first.resolve(), second.resolve()])

    def test_load_selected_video_files_rejects_paths_outside_input_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            root = Path(tmp)
            outside = Path(other) / "outside.mp4"
            outside.write_text("", encoding="utf-8")
            selected_file = root / "selected.json"
            selected_file.write_text(json.dumps([str(outside)]), encoding="utf-8")

            with self.assertRaises(VideoMergeError):
                _load_selected_video_files(selected_file, root)


if __name__ == "__main__":
    unittest.main()
