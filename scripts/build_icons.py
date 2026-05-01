from __future__ import annotations

import struct
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/icons/VideoMergingTool.png"
ICNS = ROOT / "assets/icons/VideoMergingTool.icns"
ICO = ROOT / "assets/icons/VideoMergingTool.ico"


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        icns_chunks = []
        for size, chunk_type in (
            (16, b"icp4"),
            (32, b"icp5"),
            (64, b"icp6"),
            (128, b"ic07"),
            (256, b"ic08"),
            (512, b"ic09"),
            (1024, b"ic10"),
        ):
            data = _png_at(size, temp / f"icns_{size}.png")
            icns_chunks.append(chunk_type + struct.pack(">I", len(data) + 8) + data)
        ICNS.write_bytes(b"icns" + struct.pack(">I", 8 + sum(len(chunk) for chunk in icns_chunks)) + b"".join(icns_chunks))

        ico_blobs = [(size, _png_at(size, temp / f"ico_{size}.png")) for size in (16, 24, 32, 48, 64, 128, 256)]
        entries = []
        offset = 6 + 16 * len(ico_blobs)
        for size, data in ico_blobs:
            width = 0 if size >= 256 else size
            height = 0 if size >= 256 else size
            entries.append(struct.pack("<BBBBHHII", width, height, 0, 0, 1, 32, len(data), offset))
            offset += len(data)
        with ICO.open("wb") as file:
            file.write(struct.pack("<HHH", 0, 1, len(ico_blobs)))
            for entry in entries:
                file.write(entry)
            for _, data in ico_blobs:
                file.write(data)


def _png_at(size: int, output: Path) -> bytes:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(SOURCE),
            "-vf",
            f"scale={size}:{size}",
            "-pix_fmt",
            "rgba",
            str(output),
        ],
        check=True,
    )
    return output.read_bytes()


if __name__ == "__main__":
    main()
