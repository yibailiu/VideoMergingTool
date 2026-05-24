from __future__ import annotations

import logging
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from videomerge.models import Orientation, ToolPaths
from videomerge.probe import probe_file


class ProbeEncodingTests(unittest.TestCase):
    def test_probe_uses_utf8_with_replacement_errors(self) -> None:
        payload = (
            '{"streams":[{"codec_type":"video","codec_name":"h264","width":1920,'
            '"height":1080,"avg_frame_rate":"30000/1001","pix_fmt":"yuv420p","bit_rate":"2500000"},'
            '{"codec_type":"audio","codec_name":"aac","sample_rate":"48000","channels":2,"bit_rate":"128000"}],'
            '"format":{"format_name":"mov,mp4,m4a,3gp,3g2,mj2","duration":"1.0","bit_rate":"2700000"}}'
        )

        def fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
            self.assertEqual(kwargs["encoding"], "utf-8")
            self.assertEqual(kwargs["errors"], "replace")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=payload, stderr="")

        tools = ToolPaths(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe"))
        with patch("videomerge.probe.subprocess.run", side_effect=fake_run):
            media = probe_file(Path("视频.mp4"), tools, logging.getLogger("test"))

        self.assertEqual(media.video_codec, "h264")
        self.assertEqual(media.orientation, Orientation.landscape)
        self.assertEqual(media.display_width, 1920)
        self.assertEqual(media.display_height, 1080)
        self.assertEqual(media.video_bitrate, 2500000)
        self.assertEqual(media.audio_bitrate, 128000)
        self.assertEqual(media.audio_sample_rate, 48000)
        self.assertEqual(media.audio_channels, 2)


if __name__ == "__main__":
    unittest.main()
