from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videomerge.env_check import _find_binary


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


if __name__ == "__main__":
    unittest.main()
