"""Fail early if the build interpreter cannot produce Universal 2 bundles."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from videomerge.architecture import require_macos_architectures

if __name__ == "__main__":
    require_macos_architectures(Path(sys.executable), {"x86_64", "arm64"})
    print("Build Python contains x86_64 and arm64")
