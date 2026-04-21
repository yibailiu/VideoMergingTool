from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path
from typing import Iterable, Sequence

from .errors import CommandError


def run_command(args: Sequence[str | Path], logger: logging.Logger, dry_run: bool = False) -> None:
    printable = " ".join(shlex.quote(str(arg)) for arg in args)
    logger.debug("Running command: %s", printable)
    if dry_run:
        logger.info("[dry-run] %s", printable)
        return

    process = subprocess.run(
        [str(arg) for arg in args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode != 0:
        if process.stdout.strip():
            logger.debug("Command stdout:\n%s", process.stdout.strip())
        if process.stderr.strip():
            logger.error("Command stderr:\n%s", process.stderr.strip())
        raise CommandError(f"Command failed with exit code {process.returncode}: {printable}")


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
