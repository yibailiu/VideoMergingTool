"""Inspect Mach-O headers without requiring Xcode tools on end-user machines."""
from __future__ import annotations

import struct
from pathlib import Path

from .errors import DependencyError

CPU_NAMES = {0x01000007: "x86_64", 0x0100000C: "arm64"}


def macho_architectures(path: Path) -> set[str]:
    with path.open("rb") as handle:
        header = handle.read(4096)
    magic = header[:4]
    if len(header) < 8:
        return set()
    if magic in {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"}:
        return {CPU_NAMES.get(struct.unpack_from("<I", header, 4)[0], "unknown")}
    if magic in {b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce"}:
        return {CPU_NAMES.get(struct.unpack_from(">I", header, 4)[0], "unknown")}
    fat = {b"\xca\xfe\xba\xbe": (">", 20), b"\xbe\xba\xfe\xca": ("<", 20),
           b"\xca\xfe\xba\xbf": (">", 32), b"\xbf\xba\xfe\xca": ("<", 32)}
    if magic not in fat or len(header) < 8:
        return set()
    endian, stride = fat[magic]
    count = struct.unpack_from(endian + "I", header, 4)[0]
    if count > 32 or 8 + count * stride > len(header):
        return set()
    return {CPU_NAMES.get(struct.unpack_from(endian + "I", header, 8 + index * stride)[0], "unknown") for index in range(count)}


def require_macos_architectures(path: Path, expected: set[str]) -> None:
    expected = {{"amd64": "x86_64", "aarch64": "arm64"}.get(item, item) for item in expected}
    actual = macho_architectures(path)
    if not expected.issubset(actual):
        raise DependencyError(f"Architecture mismatch: {path}: expected {sorted(expected)}, found {sorted(actual)}")
