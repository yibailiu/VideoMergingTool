from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from videomerge import __version__


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    numeric = _numeric_version(__version__)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({numeric[0]}, {numeric[1]}, {numeric[2]}, {numeric[3]}),
    prodvers=({numeric[0]}, {numeric[1]}, {numeric[2]}, {numeric[3]}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'VideoMergingTool'),
          StringStruct('FileDescription', 'VideoMergingTool'),
          StringStruct('FileVersion', '{__version__}'),
          StringStruct('InternalName', 'VideoMergingTool'),
          StringStruct('OriginalFilename', 'VideoMergingTool.exe'),
          StringStruct('ProductName', 'VideoMergingTool'),
          StringStruct('ProductVersion', '{__version__}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


def _numeric_version(version: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in re.findall(r"\d+", version)[:4]]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


if __name__ == "__main__":
    main()
