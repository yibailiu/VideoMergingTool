from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videomerge.env_check import _find_binary, _sha256, _verify_download_checksum
from videomerge.errors import DependencyError


class EnvCheckTests(unittest.TestCase):
    def test_find_binary_uses_candidate_paths_when_path_lookup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            binary = Path(temp_dir) / "ffmpeg"
            binary.touch()

            with patch("videomerge.env_check.shutil.which", return_value=None), patch(
                "videomerge.env_check._system_binary_candidates",
                return_value=[binary],
            ):
                found = _find_binary("ffmpeg", Path(temp_dir) / "missing-tools")

        self.assertEqual(found, binary)

    def test_find_binary_prefers_bundled_binary_in_frozen_app(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled = Path(temp_dir) / "ffmpeg" / "ffmpeg"
            bundled.parent.mkdir()
            bundled.touch()

            with patch("videomerge.env_check.sys.frozen", True, create=True), patch(
                "videomerge.env_check.sys._MEIPASS",
                temp_dir,
                create=True,
            ), patch("videomerge.env_check.shutil.which", return_value=None), patch(
                "videomerge.env_check._system_binary_candidates",
                return_value=[],
            ):
                found = _find_binary("ffmpeg", Path(temp_dir) / "missing-tools")

        self.assertEqual(found, bundled)

    def test_verify_download_checksum_accepts_matching_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "ffmpeg.zip"
            archive.write_bytes(b"archive")
            with patch.dict("videomerge.env_check.os.environ", {"TEST_SHA256": _sha256(archive)}):
                _verify_download_checksum(archive, "TEST_SHA256", logging.getLogger("test"))
            self.assertTrue(archive.exists())

    def test_verify_download_checksum_rejects_mismatch_and_removes_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "ffmpeg.zip"
            archive.write_bytes(b"archive")
            with patch.dict("videomerge.env_check.os.environ", {"TEST_SHA256": "0" * 64}):
                with self.assertRaises(DependencyError):
                    _verify_download_checksum(archive, "TEST_SHA256", logging.getLogger("test"))
            self.assertFalse(archive.exists())


if __name__ == "__main__":
    unittest.main()
