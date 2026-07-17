from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from videomerge.models import Orientation, VideoFile
from videomerge.scanner import scan_video_files, sort_probed_files


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

    def test_sort_probed_files_supports_media_creation_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            older = _video(root / "clip2.mp4", 100.0)
            newer = _video(root / "clip1.mp4", 200.0)
            undated = _video(root / "clip3.mp4", None)

            files = sort_probed_files([newer, undated, older], root, "media-created-asc")
            reverse_files = sort_probed_files([newer, undated, older], root, "media-created-desc")

        self.assertEqual([file.path.name for file in files], ["clip2.mp4", "clip1.mp4", "clip3.mp4"])
        self.assertEqual([file.path.name for file in reverse_files], ["clip1.mp4", "clip2.mp4", "clip3.mp4"])

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


def _video(path: Path, media_created_at: float | None) -> VideoFile:
    return VideoFile(
        path=path,
        container="mp4",
        video_codec="h264",
        audio_codec="aac",
        width=1280,
        height=720,
        display_width=1280,
        display_height=720,
        aspect_ratio="1280:720",
        frame_rate="30/1",
        frame_rate_float=30.0,
        pixel_format="yuv420p",
        duration=10.0,
        has_audio=True,
        orientation=Orientation.landscape,
        rotation=0,
        media_created_at=media_created_at,
    )


if __name__ == "__main__":
    unittest.main()
