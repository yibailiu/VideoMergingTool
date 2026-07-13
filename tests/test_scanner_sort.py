from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videomerge.scanner import scan_video_files


class ScannerSortTests(unittest.TestCase):
    def test_scan_uses_natural_filename_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in ["眼镜10.mp4", "眼镜2.mp4", "眼镜.mp4", "眼镜1.mp4"]:
                (root / name).touch()

            files = scan_video_files(root, recursive=False)

        self.assertEqual([file.name for file in files], ["眼镜.mp4", "眼镜1.mp4", "眼镜2.mp4", "眼镜10.mp4"])

    def test_scan_uses_natural_order_inside_recursive_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for folder in ["part10", "part2"]:
                (root / folder).mkdir()
                (root / folder / "clip1.mp4").touch()
            (root / "part1").mkdir()
            (root / "part1" / "clip10.mp4").touch()
            (root / "part1" / "clip2.mp4").touch()

            files = scan_video_files(root, recursive=True)

        self.assertEqual(
            [str(file.relative_to(root)) for file in files],
            ["part1/clip2.mp4", "part1/clip10.mp4", "part2/clip1.mp4", "part10/clip1.mp4"],
        )

    def test_scan_supports_sorting_by_modified_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            older = root / "clip2.mp4"
            newer = root / "clip1.mp4"
            older.touch()
            newer.touch()
            os.utime(older, (100, 100))
            os.utime(newer, (200, 200))

            files = scan_video_files(root, recursive=False, sort_by="modified-asc")
            reverse_files = scan_video_files(root, recursive=False, sort_by="modified-desc")

        self.assertEqual([file.name for file in files], ["clip2.mp4", "clip1.mp4"])
        self.assertEqual([file.name for file in reverse_files], ["clip1.mp4", "clip2.mp4"])

    def test_scan_supports_sorting_by_created_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            older = root / "clip2.mp4"
            newer = root / "clip1.mp4"
            older.touch()
            newer.touch()

            with patch("videomerge.scanner._created_time_key", side_effect=lambda path: {"clip2.mp4": 100.0, "clip1.mp4": 200.0}[path.name]):
                files = scan_video_files(root, recursive=False, sort_by="created-asc")
                reverse_files = scan_video_files(root, recursive=False, sort_by="created-desc")

        self.assertEqual([file.name for file in files], ["clip2.mp4", "clip1.mp4"])
        self.assertEqual([file.name for file in reverse_files], ["clip1.mp4", "clip2.mp4"])

    def test_scan_supports_sorting_by_size(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            small = root / "clip2.mp4"
            large = root / "clip1.mp4"
            small.write_bytes(b"1")
            large.write_bytes(b"123")

            files = scan_video_files(root, recursive=False, sort_by="size-asc")
            reverse_files = scan_video_files(root, recursive=False, sort_by="size-desc")

        self.assertEqual([file.name for file in files], ["clip2.mp4", "clip1.mp4"])
        self.assertEqual([file.name for file in reverse_files], ["clip1.mp4", "clip2.mp4"])


if __name__ == "__main__":
    unittest.main()
