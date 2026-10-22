from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videomerge.errors import CommandError
from videomerge.merge import validate_merged_output
from videomerge.models import Orientation, ToolPaths, VideoFile


class MergeValidationTests(unittest.TestCase):
    def test_complete_output_passes_fast_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "merged.mp4"
            output.write_bytes(b"x" * 1024)
            with patch("videomerge.merge.probe_file", return_value=_video(output, duration=100.0)):
                validate_merged_output(
                    output,
                    ToolPaths(Path("ffmpeg"), Path("ffprobe")),
                    logging.getLogger("test"),
                    expected_duration=100.0,
                    expected_source_size=1000,
                    expected_file_count=10,
                )

    def test_truncated_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "merged.mp4"
            output.write_bytes(b"x" * 1024)
            with patch("videomerge.merge.probe_file", return_value=_video(output, duration=90.0)):
                with self.assertRaises(CommandError):
                    validate_merged_output(
                        output,
                        ToolPaths(Path("ffmpeg"), Path("ffprobe")),
                        logging.getLogger("test"),
                        expected_duration=100.0,
                        expected_file_count=10,
                    )
                self.assertFalse(output.exists())

    def test_oversized_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "merged.mp4"
            output.write_bytes(b"x" * (17 * 1024 * 1024))
            with patch("videomerge.merge.probe_file", return_value=_video(output, duration=100.0)):
                with self.assertRaises(CommandError):
                    validate_merged_output(
                        output,
                        ToolPaths(Path("ffmpeg"), Path("ffprobe")),
                        logging.getLogger("test"),
                        expected_duration=100.0,
                        expected_source_size=1024,
                        expected_file_count=10,
                    )
                self.assertFalse(output.exists())


def _video(path: Path, duration: float) -> VideoFile:
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
        duration=duration,
        has_audio=True,
        orientation=Orientation.landscape,
        rotation=0,
        audio_sample_rate=48000,
        audio_channels=2,
    )


if __name__ == "__main__":
    unittest.main()
