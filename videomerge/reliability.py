"""Input health checks and per-run failure accounting shared by CLI and desktop."""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .errors import CommandError, VideoMergeError
from .models import ToolPaths, VideoFile
from .utils import subprocess_window_kwargs


@dataclass
class HealthResult:
    path: str
    status: str
    level: str
    reason: str = ""
    elapsed: float = 0.0


def check_video(file: VideoFile, tools: ToolPaths, level: str = "quick") -> HealthResult:
    """A sampled pass is deliberately not a claim of complete file integrity."""
    started = time.monotonic()
    if level == "basic":
        return HealthResult(str(file.path), "passed", level)
    duration = file.duration
    if duration <= 0:
        return HealthResult(str(file.path), "unknown", level, "No reliable duration is available for a bounded integrity check.")
    positions = [0.0] if level == "full" or duration <= 9 else [0.0, duration / 2, max(0, duration - 3)]
    for position in positions:
        args = [str(tools.ffmpeg), "-hide_banner", "-v", "error", "-nostdin", "-xerror", "-threads", "2"]
        if position:
            args += ["-ss", f"{position:.3f}"]
        args += ["-i", str(file.path), "-map", "0:v:0", "-map", "0:a:0?"]
        if level == "quick" and duration > 9:
            args += ["-t", "3"]
        args += ["-threads", "2", "-progress", "pipe:1", "-nostats", "-f", "null", "-"]
        try:
            # A temporary diagnostic stream prevents unbounded stderr accumulation.
            import tempfile
            with tempfile.TemporaryFile() as diagnostics, tempfile.TemporaryFile() as progress:
                process = subprocess.run(args, stdout=progress, stderr=diagnostics,
                                         timeout=30 if level == "quick" else max(120, duration * 3),
                                         **subprocess_window_kwargs())
                diagnostics.seek(0)
                reason = diagnostics.read(8192).decode("utf-8", errors="replace").strip()
                progress.seek(0)
                times = [line.partition(b"=")[2].strip() for line in progress if line.startswith(b"out_time_us=")]
            if process.returncode or reason:
                status = "error" if is_input_failure(reason) else "unknown"
                return HealthResult(str(file.path), status, level, reason or f"Decoder exit {process.returncode}", time.monotonic() - started)
            decoded = max((int(value) / 1_000_000 for value in times if value.lstrip(b"-").isdigit()), default=None)
            expected = min(3, duration - position) if level == "quick" and duration > 9 else duration
            if decoded is not None and decoded + max(1.0, expected * 0.001) < expected:
                return HealthResult(str(file.path), "error", level, f"Truncated input: decoded {decoded:.2f}s, expected {expected:.2f}s in checked interval.", time.monotonic() - started)
        except subprocess.TimeoutExpired:
            return HealthResult(str(file.path), "unknown", level, "Check timed out; integrity could not be determined.", time.monotonic() - started)
    return HealthResult(str(file.path), "passed", level, elapsed=time.monotonic() - started)


@dataclass
class TaskRun:
    policy: str
    check_level: str
    logger: logging.Logger
    checks: dict[str, HealthResult] = field(default_factory=dict)
    skipped: dict[str, dict[str, str]] = field(default_factory=dict)
    sources: dict[Path, VideoFile] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    abort_event: threading.Event = field(default_factory=threading.Event)
    processes: set = field(default_factory=set)
    temp_owners: list = field(default_factory=list)

    def cleanup(self) -> None:
        for owner in self.temp_owners:
            try:
                owner.cleanup()
            except OSError as exc:
                self.logger.warning("Temporary cleanup failed: %s", exc)
        self.temp_owners.clear()

    def track_process(self, process) -> None:
        with self.lock:
            self.processes.add(process)
            if self.abort_event.is_set() and process.poll() is None:
                process.terminate()

    def untrack_process(self, process) -> None:
        with self.lock:
            self.processes.discard(process)

    def abort(self) -> None:
        with self.lock:
            self.abort_event.set()
            for process in self.processes:
                if process.poll() is None:
                    try:
                        process.terminate()
                    except OSError:
                        pass

    def emit(self, check: HealthResult | None = None, issue: dict[str, str] | None = None) -> None:
        if check or issue:
            event = {"status": "running", "policy": self.policy, "check_level": self.check_level,
                     "incremental": True, "checks": [asdict(check)] if check else [],
                     "skipped": [issue] if issue else [], "outputs": [], "error": ""}
        else:
            event = self.snapshot()
        self.logger.info("TASK_EVENT:%s", json.dumps(event, ensure_ascii=False))

    def snapshot(self, status: str = "running", error: str = "") -> dict:
        with self.lock:
            return {"status": status, "policy": self.policy, "check_level": self.check_level,
                    "checks": [asdict(value) for value in self.checks.values()],
                    "skipped": list(self.skipped.values()), "outputs": list(self.outputs), "error": error}

    def skip(self, path: Path, stage: str, reason: str) -> None:
        with self.lock:
            self.skipped[str(path)] = {"path": str(path), "stage": stage, "reason": reason}
        self.logger.warning("Skipping %s [%s]: %s", path, stage, reason)
        self.emit(issue={"path": str(path), "stage": stage, "reason": reason})

    def inspect(self, file: VideoFile, tools: ToolPaths, level: str | None = None) -> HealthResult:
        result = check_video(file, tools, level or self.check_level)
        with self.lock:
            self.checks[str(file.path)] = result
            self.sources[file.path] = file
        self.emit(check=result)
        return result

    def recover_input(self, file: VideoFile, tools: ToolPaths, exc: CommandError) -> bool:
        if self.abort_event.is_set() or self.policy != "skip" or is_system_failure(str(exc)):
            return False
        result = self.inspect(file, tools, "full")
        if result.status != "error":
            return False
        self.skip(file.path, "processing", result.reason)
        return True


def is_system_failure(message: str) -> bool:
    text = message.lower()
    return any(part in text for part in ("no space left", "permission denied", "read-only file system", "out of memory", "cannot allocate memory", "unknown encoder", "encoder not found"))


def is_input_failure(message: str) -> bool:
    if is_system_failure(message):
        return False
    return any(part in message.lower() for part in (
        "invalid data", "corrupt", "error while decoding", "error submitting packet",
        "moov atom not found", "invalid nal", "invalid packet", "damaged", "truncated",
        "invalid frame", "header damaged", "error decoding", "decode_slice_header error",
        "missing picture", "end of file", "invalid buffer size",
    ))


current_run: ContextVar[TaskRun | None] = ContextVar("videomerge_task", default=None)


def filter_checked_inputs(files: list[VideoFile], tools: ToolPaths, run: TaskRun) -> list[VideoFile]:
    healthy = []
    for file in files:
        result = run.inspect(file, tools)
        if result.status == "passed":
            healthy.append(file)
        elif run.policy == "skip" and result.status == "error" and not is_system_failure(result.reason):
            run.skip(file.path, "check", result.reason)
        else:
            raise VideoMergeError(f"Input check {result.status}: {file.path}: {result.reason}")
    return healthy
