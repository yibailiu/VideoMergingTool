from __future__ import annotations

import logging
import io
import tarfile
import urllib.error
import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videomerge.env_check import _download, _find_binary, _sha256, _verify_download_checksum
from videomerge.errors import DependencyError


class EnvCheckTests(unittest.TestCase):
    @staticmethod
    def response(data: bytes, content_type="application/x-xz", length=None):
        response = io.BytesIO(data)
        response.status = 200
        response.headers = {"Content-Type": content_type, "Content-Length": str(len(data) if length is None else length)}
        return response

    @staticmethod
    def archive() -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:xz") as archive:
            member = tarfile.TarInfo("ffmpeg/ffmpeg")
            member.size = 6
            archive.addfile(member, io.BytesIO(b"binary"))
        return buffer.getvalue()

    def test_download_retries_html_then_publishes_only_valid_archive(self):
        data = self.archive()
        for content_type in ("text/html", "application/octet-stream"):
            with self.subTest(content_type=content_type), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "ffmpeg.tar.xz"
                with patch("videomerge.env_check.urllib.request.urlopen", side_effect=[self.response(b"<html>upstream failure</html>", content_type), self.response(data)]) as fetch, patch("videomerge.env_check.time.sleep"):
                    _download("https://example.invalid/ffmpeg.tar.xz", output, logging.getLogger("test"))
                self.assertEqual(fetch.call_count, 2)
                self.assertEqual(output.read_bytes(), data)
                self.assertFalse(output.with_name(output.name + ".part").exists())

    def test_download_rejects_truncation_and_preserves_previous_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "ffmpeg.tar.xz"
            output.write_bytes(b"previous archive")
            responses = [self.response(b"short", length=100) for _ in range(3)]
            with patch("videomerge.env_check.urllib.request.urlopen", side_effect=responses) as fetch, patch("videomerge.env_check.time.sleep"):
                with self.assertRaisesRegex(DependencyError, "Incomplete download"):
                    _download("https://example.invalid/ffmpeg.tar.xz", output, logging.getLogger("test"))
            self.assertEqual(fetch.call_count, 3)
            self.assertEqual(output.read_bytes(), b"previous archive")
            self.assertFalse(output.with_name(output.name + ".part").exists())

    def test_download_retries_network_failure_and_enforces_pinned_hash(self):
        data = self.archive()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "ffmpeg.tar.xz"
            with patch("videomerge.env_check.urllib.request.urlopen", side_effect=[urllib.error.URLError("network"), self.response(data)]), patch("videomerge.env_check.time.sleep"):
                _download("https://example.invalid/ffmpeg.tar.xz", output, logging.getLogger("test"))
            output.unlink()
            with patch("videomerge.env_check.urllib.request.urlopen", side_effect=[self.response(data) for _ in range(3)]), patch("videomerge.env_check.time.sleep"):
                with self.assertRaisesRegex(DependencyError, "Checksum mismatch"):
                    _download("https://example.invalid/ffmpeg.tar.xz", output, logging.getLogger("test"), expected_sha256="0" * 64)
            self.assertFalse(output.exists())

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
            bundled = Path(temp_dir) / "ffmpeg" / ("ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg")
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
