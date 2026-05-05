from __future__ import annotations

import io
import logging
import sys
import unittest
from unittest.mock import patch

from videomerge.logger import setup_logging


class LoggerEncodingTests(unittest.TestCase):
    def test_console_logging_replaces_characters_not_supported_by_windows_gbk(self) -> None:
        stream = _FakeStdout("gbk")

        with patch.object(sys, "stdout", stream):
            logger = setup_logging()
            logger.info("Media: %s", "⭐ Bin.mp4")

        for handler in logger.handlers:
            handler.flush()

        self.assertIn("⭐ Bin.mp4", stream.buffer.getvalue().decode("utf-8"))


class _FakeStdout:
    def __init__(self, encoding: str) -> None:
        self.encoding = encoding
        self.buffer = io.BytesIO()

    def write(self, text: str) -> int:
        data = text.encode(self.encoding)
        self.buffer.write(data)
        return len(text)

    def flush(self) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
