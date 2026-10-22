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

    def test_windows_gpu_encoders_apply_source_bitrate_limit(self) -> None:
        for encoder in ("h264_nvenc", "h264_qsv", "h264_amf"):
            with self.subTest(encoder=encoder):
                args = gpu_encoder_quality_args(
                    encoder, 20, "medium", 1920, 1080, 30, source_bitrate=4_000_000
                )

                self.assertEqual(args[args.index("-b:v") + 1], "4000k")
                self.assertEqual(args[args.index("-maxrate") + 1], "4000k")
                self.assertEqual(args[args.index("-bufsize") + 1], "8000k")

    def test_cpu_h264_quality_args_use_crf(self) -> None:
        args = gpu_encoder_quality_args("libx264", 18, "slow")

        self.assertEqual(args, ["-crf", "18", "-preset", "slow", "-profile:v", "high"])

    def test_mpeg4_quality_args_use_qscale_not_crf(self) -> None:
        args = gpu_encoder_quality_args("mpeg4", 10, "medium")

        self.assertIn("-q:v", args)
        self.assertNotIn("-crf", args)
        self.assertLess(int(args[args.index("-q:v") + 1]), 10)

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

    def test_videotoolbox_balanced_quality_uses_dominant_source_bitrate(self) -> None:
        args = gpu_encoder_quality_args(
            "h264_videotoolbox",
            23,
            "medium",
            3840,
            2160,
            30,
            source_bitrate=4_000_000,
        )

        self.assertEqual(args[args.index("-b:v") + 1], "4000k")
        self.assertEqual(args[args.index("-maxrate") + 1], "4000k")

    def test_videotoolbox_high_quality_does_not_exceed_source_bitrate(self) -> None:
        args = gpu_encoder_quality_args(
            "h264_videotoolbox", 20, "medium", 1920, 1080, 30, source_bitrate=2_000_000
        )

        self.assertEqual(args[args.index("-b:v") + 1], "2000k")

    def test_videotoolbox_4k_fallback_no_longer_uses_60_mbps(self) -> None:
        args = gpu_encoder_quality_args("h264_videotoolbox", 23, "medium", 3840, 2160, 30)

        self.assertLess(int(args[args.index("-b:v") + 1].removesuffix("k")), 30_000)

    def test_unsupported_codec_falls_back_to_cpu(self) -> None:
        tools = ToolPaths(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe"))
        with patch("videomerge.gpu.detect_ffmpeg_encoders", return_value={"h264_videotoolbox"}):
            plan = resolve_gpu_plan(tools, GpuMode.auto, "vp9", logging.getLogger("test"))

        self.assertFalse(plan.enabled)


if __name__ == "__main__":
    unittest.main()
