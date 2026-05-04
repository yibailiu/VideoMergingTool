from __future__ import annotations

import logging
import unittest
from pathlib import Path
from unittest.mock import patch

from videomerge.gpu import GpuMode, gpu_encoder_quality_args, resolve_gpu_plan
from videomerge.models import ToolPaths


class GpuTests(unittest.TestCase):
    def test_windows_auto_prefers_nvenc_then_qsv_then_amf(self) -> None:
        tools = ToolPaths(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe"))
        with patch("videomerge.gpu.platform.system", return_value="Windows"), patch(
            "videomerge.gpu.detect_ffmpeg_encoders",
            return_value={"h264_qsv", "h264_amf"},
        ):
            plan = resolve_gpu_plan(tools, GpuMode.auto, "h264", logging.getLogger("test"))

        self.assertEqual(plan.mode, GpuMode.qsv)
        self.assertEqual(plan.encoder, "h264_qsv")

    def test_nvenc_quality_args_use_cq_not_crf(self) -> None:
        args = gpu_encoder_quality_args("h264_nvenc", 20, "slow")

        self.assertIn("-cq", args)
        self.assertNotIn("-crf", args)
        self.assertIn("p7", args)

    def test_macos_auto_uses_videotoolbox(self) -> None:
        tools = ToolPaths(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe"))
        with patch("videomerge.gpu.platform.system", return_value="Darwin"), patch(
            "videomerge.gpu.detect_ffmpeg_encoders",
            return_value={"h264_videotoolbox", "hevc_videotoolbox"},
        ):
            plan = resolve_gpu_plan(tools, GpuMode.auto, "h264", logging.getLogger("test"))

        self.assertEqual(plan.mode, GpuMode.videotoolbox)
        self.assertEqual(plan.encoder, "h264_videotoolbox")

    def test_videotoolbox_quality_args_use_bitrate_not_crf(self) -> None:
        args = gpu_encoder_quality_args("h264_videotoolbox", 20, "medium", 1920, 1080, 30)

        self.assertIn("-b:v", args)
        self.assertIn("-allow_sw", args)
        self.assertNotIn("-crf", args)

    def test_unsupported_codec_falls_back_to_cpu(self) -> None:
        tools = ToolPaths(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe"))
        with patch("videomerge.gpu.detect_ffmpeg_encoders", return_value={"h264_videotoolbox"}):
            plan = resolve_gpu_plan(tools, GpuMode.auto, "vp9", logging.getLogger("test"))

        self.assertFalse(plan.enabled)


if __name__ == "__main__":
    unittest.main()
