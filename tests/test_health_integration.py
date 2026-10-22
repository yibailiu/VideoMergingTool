"""Real decoder regressions. Skipped on machines without FFmpeg/FFprobe."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from videomerge.models import ToolPaths
from videomerge.probe import probe_file
from videomerge.reliability import check_video


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg integration tools unavailable")
class HealthIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="vmt_health_")
        cls.root = Path(cls.directory.name)
        cls.tools = ToolPaths(Path(shutil.which("ffmpeg")), Path(shutil.which("ffprobe")))
        cls.logger = logging.getLogger("health-integration")
        for name in ("01.mp4", "03.mp4"):
            subprocess.run([str(cls.tools.ffmpeg), "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=25:duration=2", "-c:v", "mpeg4", "-q:v", "5", "-movflags", "+faststart", str(cls.root / name)], check=True, capture_output=True)
        (cls.root / "02.mp4").write_bytes(b"damaged video container")
        original = (cls.root / "01.mp4").read_bytes()
        (cls.root / "truncated.mp4").write_bytes(original[:len(original) // 2])

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_metadata_readable_truncated_body_is_rejected_by_decoder(self):
        file = probe_file(self.root / "truncated.mp4", self.tools, self.logger)
        result = check_video(file, self.tools, "full")
        self.assertEqual(result.status, "error", result.reason)

    def test_healthy_video_passes_full_check(self):
        file = probe_file(self.root / "01.mp4", self.tools, self.logger)
        self.assertEqual(check_video(file, self.tools, "full").status, "passed")

    def test_skip_and_stop_cli_policies(self):
        manifest = self.root / "sources.json"
        manifest.write_text(json.dumps([str(self.root / name) for name in ("01.mp4", "02.mp4", "03.mp4")]), encoding="utf-8")
        for policy in ("stop", "skip"):
            report = self.root / f"{policy}.json"
            process = subprocess.run([sys.executable, "main.py", "merge", str(self.root), "--mode", "extreme", "--selected-files", str(manifest), "--on-error", policy, "--check-level", "quick", "--output-dir", str(self.root / policy), "--report-file", str(report), "--no-auto-download-deps"], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1])
            result = json.loads(report.read_text(encoding="utf-8"))
            if policy == "stop":
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["outputs"], [])
            else:
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertEqual(result["status"], "partial")
                self.assertEqual(len(result["skipped"]), 1)
                self.assertEqual(len(result["outputs"]), 1)
                output = probe_file(Path(result["outputs"][0]), self.tools, self.logger)
                self.assertGreaterEqual(output.duration, 3.9)
