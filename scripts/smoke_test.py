from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--expected-arch")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="vmt_artifact_check_") as directory:
        report = Path(directory) / "report.json"
        subprocess.run([str(args.executable.resolve()), "self-check", "--report-file", str(report)], check=True, timeout=180)
        result = json.loads(report.read_text(encoding="utf-8"))
        if result.get("status") != "passed" or not result.get("frozen"):
            raise RuntimeError(f"Packaged self-check failed: {result}")
        if args.expected_arch and result["architecture"] != args.expected_arch:
            raise RuntimeError(f"App ran with wrong architecture: {result}")
        print(json.dumps(result, indent=2))
