from __future__ import annotations

from pathlib import Path


SUPPORTED_OUTPUT_FORMATS = {"mp4", "mkv", "mov", "avi", "ts", "webm"}


def prepare_output_dir(input_dir: Path, output_dir: Path | None) -> Path:
    target = output_dir if output_dir else input_dir / "merged"
    target.mkdir(parents=True, exist_ok=True)
    return target


def unique_output_path(output_dir: Path, base_name: str, extension: str, overwrite: bool) -> Path:
    clean_base = sanitize_filename(base_name)
    ext = extension.lower().lstrip(".")
    path = output_dir / f"{clean_base}.{ext}"
    if overwrite or not path.exists():
        return path

    index = 1
    while True:
        candidate = output_dir / f"{clean_base}_{index}.{ext}"
        if not candidate.exists():
            return candidate
        index += 1


def sanitize_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value.strip())
    return cleaned.strip("._") or "merged"


def auto_name(folder_name: str, label: str, resolution: str | None = None) -> str:
    parts = [folder_name, label, "merge"]
    if resolution:
        parts.append(resolution)
    return "_".join(parts)
