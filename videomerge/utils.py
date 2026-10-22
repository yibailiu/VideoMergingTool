from __future__ import annotations

import logging
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, Sequence

from .errors import CommandError


FFMPEG_RUNTIME_ARGS = ("-hide_banner", "-loglevel", "warning", "-nostats", "-nostdin")


def subprocess_window_kwargs() -> dict[str, int]:
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def run_command(args: Sequence[str | Path], logger: logging.Logger, dry_run: bool = False) -> None:
    printable = " ".join(shlex.quote(str(arg)) for arg in args)
    logger.debug("Running command: %s", printable)
    if dry_run:
        logger.info("[dry-run] %s", printable)
        return

    from .reliability import current_run
    task_run = current_run.get()
    if task_run and task_run.abort_event.is_set():
        raise CommandError("Task stopped after another processing failure.")
    with tempfile.TemporaryFile() as diagnostics:
        with subprocess.Popen([str(arg) for arg in args], stdout=subprocess.DEVNULL,
                              stderr=diagnostics, **subprocess_window_kwargs()) as process:
            if task_run:
                task_run.track_process(process)
            try:
                code = process.wait()
            finally:
                if task_run:
                    task_run.untrack_process(process)
        diagnostics.seek(0)
        # Stream diagnostics to the detailed log without retaining them in memory.
        for line in diagnostics:
            logger.debug("FFmpeg: %s", line.decode("utf-8", errors="replace").rstrip())
        diagnostics.seek(0, os.SEEK_END)
        diagnostics.seek(max(0, diagnostics.tell() - 8192))
        reason = diagnostics.read().decode("utf-8", errors="replace").strip()
    if code != 0:
        if reason:
            logger.error("Command stderr:\n%s", reason)
        raise CommandError(f"Media processing failed with exit code {code}:\n{reason}")


def write_concat_list(paths: Iterable[Path], list_path: Path) -> None:
    lines = []
    for path in paths:
        escaped = str(path.resolve()).replace("'", r"'\''")
        lines.append(f"file '{escaped}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_even(value: int) -> int:
    return value if value % 2 == 0 else value + 1


def parse_fraction(value: str | None, default: float = 0.0) -> float:
    if not value or value == "0/0":
        return default
    if "/" not in value:
        try:
            return float(value)
        except ValueError:
            return default
    numerator, denominator = value.split("/", 1)
    try:
        den = float(denominator)
        if den == 0:
            return default
        return float(numerator) / den
    except ValueError:
        return default
