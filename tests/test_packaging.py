import hashlib
import logging
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videomerge.architecture import macho_architectures, require_macos_architectures
from videomerge.env_check import macos_download_config, _verify_download_checksum
from videomerge.errors import DependencyError
from videomerge.self_check import verify_web_assets


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_thin_and_universal_headers(self):
        file = self.root / "binary"
        for cpu, name in [(0x01000007, "x86_64"), (0x0100000C, "arm64")]:
            file.write_bytes(bytes.fromhex("cffaedfe") + struct.pack("<I", cpu))
            self.assertEqual(macho_architectures(file), {name})
            require_macos_architectures(file, {name})
            with self.assertRaises(DependencyError):
                require_macos_architectures(file, {"arm64", "x86_64"})
        for magic, endian, stride in [("cafebabe", ">", 20), ("bfbafeca", "<", 32)]:
            file.write_bytes(bytes.fromhex(magic) + struct.pack(endian + "I", 2) +
                             b"".join(struct.pack(endian + "I", cpu) + bytes(stride - 4)
                                      for cpu in (0x01000007, 0x0100000C)))
            require_macos_architectures(file, {"arm64", "x86_64"})

    def test_truncated_and_non_macho_files(self):
        file = self.root / "binary"
        for data in (b"", b"not macho", bytes.fromhex("cafebabe") + struct.pack(">I", 33)):
            file.write_bytes(data)
            self.assertEqual(macho_architectures(file), set())

    def test_downloads_are_native_and_pinned(self):
        for arch in ("arm64", "x86_64"):
            config = macos_download_config(arch)
            for key in ("sha256", "ffprobe_sha256"):
                self.assertEqual(len(bytes.fromhex(config[key])), 32)
            self.assertIn("9.0.2", config["url"])
        self.assertEqual(macos_download_config("aarch64"), macos_download_config("arm64"))
        with patch("videomerge.env_check.platform.machine", return_value="arm64"):
            self.assertEqual(macos_download_config(), macos_download_config("arm64"))
        with self.assertRaises(DependencyError):
            macos_download_config("unsupported")

    def test_pinned_checksum_is_mandatory(self):
        file = self.root / "archive"
        file.write_bytes(b"content")
        logger = logging.getLogger("test")
        _verify_download_checksum(file, None, logger, hashlib.sha256(b"content").hexdigest())
        with self.assertRaises(DependencyError):
            _verify_download_checksum(file, None, logger, "0" * 64)

    def test_assets_must_be_complete_and_safe(self):
        assets = self.root / "assets"
        assets.mkdir()
        (assets / "app.js").write_text("js")
        (assets / "app.css").write_text("css")
        index = self.root / "index.html"
        index.write_text('<script src="/assets/app.js"></script><link href="/assets/app.css">')
        self.assertEqual(len(verify_web_assets(self.root)), 2)
        (assets / "app.css").unlink()
        with self.assertRaises(RuntimeError):
            verify_web_assets(self.root)
        index.write_text('<script src="/assets/../../outside.js"></script><link href="/assets/app.css">')
        with self.assertRaises(RuntimeError):
            verify_web_assets(self.root)
