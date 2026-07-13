from __future__ import annotations

import re
from pathlib import Path


VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".ts",
    ".m4v",
    ".flv",
    ".webm",
    ".wmv"
}

SORT_OPTIONS = {
    "name-natural-asc",
    "name-natural-desc",
    "name-asc",
    "name-desc",
    "created-asc",
    "created-desc",
    "modified-asc",
    "modified-desc",
    "size-asc",
    "size-desc",
}


def scan_video_files(input_dir: Path, recursive: bool, sort_by: str = "name-natural-asc") -> list[Path]:
    pattern = "**/*" if recursive else "*"
    files = [
        path
        for path in input_dir.glob(pattern)
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    ]
    return _sort_video_files(files, input_dir, sort_by)


def _sort_video_files(files: list[Path], input_dir: Path, sort_by: str) -> list[Path]:
    if sort_by not in SORT_OPTIONS:
        raise ValueError(f"Unsupported sort option: {sort_by}")

    reverse = sort_by.endswith("-desc")
    if sort_by.startswith("name-natural"):
        return sorted(files, key=lambda path: _natural_path_key(path, input_dir), reverse=reverse)
    if sort_by.startswith("name-"):
        return sorted(files, key=lambda path: _casefold_path_key(path, input_dir), reverse=reverse)
    if sort_by.startswith("created-"):
        natural_sorted = sorted(files, key=lambda path: _natural_path_key(path, input_dir))
        return sorted(natural_sorted, key=_created_time_key, reverse=reverse)
    if sort_by.startswith("modified-"):
        natural_sorted = sorted(files, key=lambda path: _natural_path_key(path, input_dir))
        return sorted(natural_sorted, key=lambda path: path.stat().st_mtime, reverse=reverse)
    if sort_by.startswith("size-"):
        natural_sorted = sorted(files, key=lambda path: _natural_path_key(path, input_dir))
        return sorted(natural_sorted, key=lambda path: path.stat().st_size, reverse=reverse)
    return files


def _casefold_path_key(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path
    return str(relative).casefold()


def _created_time_key(path: Path) -> float:
    stat = path.stat()
    return float(getattr(stat, "st_birthtime", stat.st_ctime))


def _natural_path_key(path: Path, root: Path) -> tuple[tuple[int, object], ...]:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path

    key: list[tuple[int, object]] = []
    parts = relative.parts
    for index, part in enumerate(parts):
        if index == len(parts) - 1:
            file_part = Path(part)
            key.extend(_natural_text_key(file_part.stem))
            key.append((0, file_part.suffix.casefold()))
        else:
            key.extend(_natural_text_key(part))
        key.append((0, "/"))
    return tuple(key)


def _natural_text_key(value: str) -> list[tuple[int, object]]:
    tokens: list[tuple[int, object]] = []
    for token in re.split(r"(\d+)", value.casefold()):
        if not token:
            continue
        if token.isdigit():
            tokens.append((1, int(token)))
        else:
            tokens.append((0, token))
    return tokens
