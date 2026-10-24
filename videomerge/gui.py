from __future__ import annotations

import json
import locale
import logging
import mimetypes
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from collections import Counter
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .adjustments import apply_clockwise_rotation, validate_clockwise_rotation
from .env_check import default_tools_dir, resolve_tools
from .grouping import group_fast, split_by_orientation
from .gpu import detect_ffmpeg_encoders
from .models import MergeMode, Orientation, VideoFile
from .planning import build_extreme_group_plan, build_optimal_group_plan
from .probe import probe_files
from .scanner import VIDEO_EXTENSIONS, scan_video_files, sort_probed_files, sort_video_paths
from .utils import subprocess_window_kwargs
from . import __version__


REPOSITORY_URL = "https://github.com/yibailiu/VideoMergingTool"


CONFIG_FIELD_IDS = [
    "outputDir",
    "tempDir",
    "format",
    "sortBy",
    "codec",
    "gpu",
    "gpuWorkers",
    "audioCodec",
    "qualityProfile",
    "crf",
    "preset",
    "fpsPolicy",
    "resolutionPolicy",
    "padColor",
    "ffmpegPath",
    "ffprobePath",
    "recursive",
    "overwrite",
    "dryRun",
    "keepTemp",
    "autoDownloadDeps",
    "notifyOnComplete",
    "playSoundOnComplete",
    "columnWidths",
    "checkLevel",
    "onError",
]

PICKER_TEXT = {
    "en": {
        "source": "Select source video folder",
        "output": "Select output folder",
        "temp": "Select temp folder",
        "folder": "Select folder",
        "files": "Select one or more source video files",
        "video_filter": "Video files",
        "all_filter": "All files (*.*)",
        "folder_placeholder": "Select this folder",
    },
    "zh": {
        "source": "选择源视频文件夹",
        "output": "选择输出文件夹",
        "temp": "选择临时文件夹",
        "folder": "选择文件夹",
        "files": "选择一个或多个源视频文件",
        "video_filter": "视频文件",
        "all_filter": "所有文件 (*.*)",
        "folder_placeholder": "选择此文件夹",
    },
}


class GuiState:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.progress = 0
        self.running = False
        self.cancel_requested = False
        self.process: subprocess.Popen[str] | None = None
        self.cleanup_temp_on_cancel = True
        self.temp_paths: list[Path] = []
        self.media_files: list[VideoFile] = []
        self.result: dict[str, object] | None = None
        self.log_path: Path | None = None
        self.lock = threading.Lock()

    def log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        with self.lock:
            self.logs.extend(f"[{stamp}] {line}" for line in message.splitlines() or [""])

    def set_progress(self, value: int) -> None:
        with self.lock:
            self.progress = max(0, min(100, value))

    def snapshot(self, after: int = 0) -> dict[str, object]:
        with self.lock:
            cursor = max(0, min(after, len(self.logs)))
            return {
                "logs": list(self.logs[cursor:]),
                "log_cursor": len(self.logs),
                "progress": self.progress,
                "running": self.running,
                "result": self.result,
            }

    def full_log_text(self) -> str:
        with self.lock:
            console = "\n".join(self.logs)
            path = self.log_path
        if path and path.is_file():
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                return console + f"\n[Log file could not be read: {exc}]"
            if raw:
                return console + "\n\n--- Complete process log ---\n" + raw
        return console

    def set_media_files(self, files: list[VideoFile]) -> None:
        with self.lock:
            self.media_files = list(files)

    def get_media_files(self) -> list[VideoFile]:
        with self.lock:
            return list(self.media_files)

    def begin_run(self, cleanup_temp_on_cancel: bool = True) -> bool:
        with self.lock:
            if self.running:
                return False
            self.logs.clear()
            self.log_path = None
            self.result = None
            self.progress = 4
            self.running = True
            self.cancel_requested = False
            self.process = None
            self.cleanup_temp_on_cancel = cleanup_temp_on_cancel
            self.temp_paths.clear()
            return True

    def start_process(self, process: subprocess.Popen[str]) -> bool:
        with self.lock:
            self.process = process
            return self.cancel_requested

    def cancel_running_process(self) -> bool:
        with self.lock:
            process = self.process
            if not self.running:
                return False
            self.cancel_requested = True
            if process is None or process.poll() is not None:
                return True
        _terminate_process(process)
        return True

    def finish_process(self) -> bool:
        with self.lock:
            was_cancelled = self.cancel_requested
            self.process = None
            self.running = False
            self.cancel_requested = False
            return was_cancelled

    def record_temp_path(self, path: Path) -> None:
        with self.lock:
            if path not in self.temp_paths:
                self.temp_paths.append(path)

    def consume_cancel_cleanup_paths(self) -> list[Path]:
        with self.lock:
            paths = list(self.temp_paths) if self.cleanup_temp_on_cancel else []
            self.temp_paths.clear()
            self.cleanup_temp_on_cancel = True
            return paths


class QueueLogHandler(logging.Handler):
    def __init__(self, state: GuiState) -> None:
        super().__init__()
        self.state = state

    def emit(self, record: logging.LogRecord) -> None:
        self.state.log(self.format(record))


def launch_gui(host: str = "127.0.0.1", port: int | None = None) -> None:
    if not (Path(__file__).parent / "web" / "index.html").is_file():
        raise RuntimeError("Desktop UI is not built. Run `npm --prefix frontend ci` and `npm --prefix frontend run build`.")
    port = port or _free_port()
    state = GuiState()
    api_token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer((host, port), _make_handler(state, api_token))
    url = f"http://{host}:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"VideoMergingTool GUI running at {url}")
    try:
        _open_desktop_window(url)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


def _open_desktop_window(url: str) -> None:
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "Desktop GUI requires pywebview. Install dependencies with `pip install -r requirements.txt`."
        ) from exc

    webview.create_window(f"VideoMergingTool {__version__}", url, width=1280, height=820, min_size=(900, 620), text_select=True)
    webview.start()


def _copy_text_to_clipboard(text: str) -> None:
    if not text:
        raise ValueError("No log messages are available yet.")
    system = platform.system()
    if system == "Windows":
        script = ("[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false); "
                  "Add-Type -AssemblyName System.Windows.Forms; "
                  "[System.Windows.Forms.Clipboard]::SetText([Console]::In.ReadToEnd())")
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-Command", script]
    elif system == "Darwin":
        command = ["pbcopy"]
    elif os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        command = ["wl-copy"]
    elif shutil.which("xclip"):
        command = ["xclip", "-selection", "clipboard"]
    elif shutil.which("xsel"):
        command = ["xsel", "--clipboard", "--input"]
    else:
        raise RuntimeError("No system clipboard utility is available. Copy from the full log view instead.")
    subprocess.run(command, input=text, encoding="utf-8", capture_output=True,
                   check=True, timeout=10, **subprocess_window_kwargs())


def _make_handler(state: GuiState, api_token: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                index = Path(__file__).parent / "web" / "index.html"
                if index.is_file():
                    self._send_html(index.read_text(encoding="utf-8"))
                else:
                    self._send_html("<h1>Build the desktop UI first</h1><p>Run npm ci and npm run build in frontend/.</p>")
                return
            if parsed.path.startswith("/assets/"):
                root = (Path(__file__).parent / "web" / "assets").resolve()
                asset = (root / parsed.path.removeprefix("/assets/")).resolve()
                if root not in asset.parents or not asset.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                data = asset.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if not self._authorized():
                return
            if parsed.path == "/pick-folder":
                kind = parse_qs(parsed.query).get("kind", ["source"])[0]
                lang = _dialog_language(parse_qs(parsed.query).get("lang", [""])[0])
                self._send_json({"path": _pick_folder(kind, lang)})
                return
            if parsed.path == "/pick-files":
                lang = _dialog_language(parse_qs(parsed.query).get("lang", [""])[0])
                paths = _pick_video_files(lang)
                self._send_json(
                    {
                        "paths": paths,
                        "input_dir": _common_input_dir(paths) if paths else "",
                    }
                )
                return
            if parsed.path == "/deps":
                self._deps()
                return
            if parsed.path == "/status":
                after_value = parse_qs(parsed.query).get("after", ["0"])[0]
                try:
                    after = int(after_value)
                except ValueError:
                    after = 0
                self._send_json(state.snapshot(after))
                return
            if parsed.path == "/logs":
                text = state.full_log_text()
                self._send_json({"logs": text.splitlines(), "text": text})
                return
            if parsed.path == "/config":
                self._send_json(_load_gui_config())
                return
            if parsed.path == "/defaults":
                self._send_json(_default_display_paths())
                return
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if not self._authorized():
                return
            payload = self._read_json()
            if parsed.path == "/copy-logs":
                text = state.full_log_text()
                try:
                    _copy_text_to_clipboard(text)
                    self._send_json({"copied": True})
                except Exception as exc:
                    self._send_json({"copied": False, "text": text, "message": str(exc)})
                return
            if parsed.path == "/scan":
                self._scan(payload)
                return
            if parsed.path == "/plan":
                self._plan(payload)
                return
            if parsed.path == "/merge":
                self._merge(payload)
                return
            if parsed.path == "/cancel":
                self._cancel()
                return
            if parsed.path == "/config":
                _save_gui_config(payload)
                self._send_json({"ok": True})
                return
            if parsed.path == "/defaults":
                self._send_json(_default_display_paths(str(payload.get("input_dir") or "")))
                return
            if parsed.path == "/open-url":
                self._open_url(payload)
                return
            if parsed.path == "/open-media":
                self._open_media(payload)
                return
            if parsed.path == "/notify":
                self._notify(payload)
                return
            if parsed.path == "/notify-permission":
                self._notify_permission()
                return
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

        def _deps(self) -> None:
            try:
                logger = _gui_logger(state)
                tools = resolve_tools(logger, True, default_tools_dir())
                encoders = _detect_gui_ffmpeg_encoders(tools)
                gpu_encoders = sorted(
                    encoder
                    for encoder in encoders
                    if encoder.endswith(("_nvenc", "_qsv", "_amf", "_videotoolbox"))
                )
                recommended_gpu = _recommended_gpu_mode(gpu_encoders)
                self._send_json(
                    {
                        "ok": True,
                        "message": f"FFmpeg ready: {tools.ffmpeg}. GPU encoders: {', '.join(gpu_encoders) if gpu_encoders else 'none detected'}. Recommended GPU mode: {recommended_gpu}.",
                        "ffmpeg": str(tools.ffmpeg),
                        "ffprobe": str(tools.ffprobe),
                        "gpu_encoders": gpu_encoders,
                        "gpu_recommended": recommended_gpu,
                        "platform": platform.system(),
                    }
                )
            except Exception as exc:
                self._send_json({"ok": False, "message": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def _open_url(self, payload: dict[str, object]) -> None:
            url = str(payload.get("url") or "")
            if url != REPOSITORY_URL:
                self._send_json({"error": "Unsupported URL"}, HTTPStatus.BAD_REQUEST)
                return
            webbrowser.open(url)
            self._send_json({"ok": True})

        def _open_media(self, payload: dict[str, object]) -> None:
            requested_path = str(payload.get("path") or "")
            media_file = next(
                (file for file in state.get_media_files() if str(file.path) == requested_path),
                None,
            )
            if media_file is None:
                self._send_json({"error": "The requested video is not part of the current scan."}, HTTPStatus.BAD_REQUEST)
                return
            if not media_file.path.is_file():
                self._send_json({"error": "The requested video no longer exists."}, HTTPStatus.NOT_FOUND)
                return
            try:
                _open_media_file(media_file.path)
            except OSError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._send_json({"ok": True})

        def _notify(self, payload: dict[str, object]) -> None:
            title = str(payload.get("title") or "VideoMergingTool")
            body = str(payload.get("body") or "")
            sound = bool(payload.get("sound"))
            ok, message = _show_system_notification(title, body, sound)
            self._send_json({"ok": ok, "message": message})

        def _notify_permission(self) -> None:
            ok, message = _request_notification_permission()
            self._send_json({"ok": ok, "message": message})

        def _scan(self, payload: dict[str, object]) -> None:
            try:
                logger = _gui_logger(state)
                state.set_progress(8)
                tools = resolve_tools(logger, True, default_tools_dir())
                input_dir = Path(str(payload["input_dir"])).expanduser().resolve()
                if not input_dir.is_dir():
                    raise ValueError(f"Selected path is not a folder: {input_dir}")
                output_value = str(payload.get("output_dir") or "").strip()
                output_dir = Path(output_value).expanduser() if output_value else input_dir / "merged"
                sort_by = str(payload.get("sort_by") or "name-natural-asc")
                source_values = payload.get("source_files")
                if isinstance(source_values, list) and source_values:
                    paths = _validate_selected_source_files(source_values, input_dir, sort_by)
                else:
                    paths = scan_video_files(
                        input_dir,
                        bool(payload.get("recursive", True)),
                        sort_by,
                        excluded_dirs=(output_dir,),
                    )
                state.set_progress(25)
                media_files, failures = probe_files(paths, tools, logger)
                media_files = sort_probed_files(
                    media_files,
                    input_dir,
                    sort_by,
                )
                if failures:
                    state.log(f"{len(failures)} file(s) could not be analyzed.")
                state.set_media_files(media_files)
                plan = _build_gui_plan(media_files, media_files, payload)
                plan["failures"] = [{"path": str(path), "stage": "probe", "reason": reason} for path, reason in failures.items()]
                state.set_progress(100)
                self._send_json(plan)
            except Exception as exc:
                state.set_progress(0)
                self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def _plan(self, payload: dict[str, object]) -> None:
            try:
                media_files = state.get_media_files()
                selected_values = payload.get("selected_files", [])
                if not isinstance(selected_values, list):
                    selected_values = []
                selected_paths = {
                    str(path)
                    for path in selected_values
                    if isinstance(path, str)
                }
                selected = [file for file in media_files if str(file.path) in selected_paths]
                self._send_json(_build_gui_plan(media_files, selected, payload))
            except Exception as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def _merge(self, payload: dict[str, object]) -> None:
            selected_files = payload.get("selected_files")
            if isinstance(selected_files, list) and not selected_files:
                self._send_json({"error": "No source files were selected."}, HTTPStatus.BAD_REQUEST)
                return
            if not state.begin_run(cleanup_temp_on_cancel=not bool(payload.get("keep_temp"))):
                self._send_json({"error": "A merge is already running."}, HTTPStatus.CONFLICT)
                return
            try:
                run_dir = _config_dir() / "runs" / secrets.token_hex(8)
                run_dir.mkdir(parents=True, exist_ok=True)
                state.log_path = run_dir / "process.log"
                payload = {**payload, "report_file": str(run_dir / "result.json"), "log_file": str(state.log_path)}
                command = _build_merge_command(payload)
            except Exception as exc:
                state.finish_process()
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            threading.Thread(target=_run_merge, args=(command, state), daemon=True).start()
            self._send_json({"command": command})

        def _cancel(self) -> None:
            if state.cancel_running_process():
                self._send_json({"ok": True, "message": "Stop requested."})
            else:
                self._send_json({"ok": False, "message": "No merge task is running."})

        def _read_json(self) -> dict[str, object]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def _authorized(self) -> bool:
            if self.headers.get("X-VideoMergingTool-Token") == api_token:
                return True
            self._send_json({"error": "Unauthorized"}, HTTPStatus.FORBIDDEN)
            return False

        def _send_html(self, content: str) -> None:
            content = (
                content.replace("__APP_VERSION__", __version__)
                .replace("__DEFAULT_LANG__", _system_ui_language())
                .replace("__REPOSITORY_URL__", REPOSITORY_URL)
                .replace("__API_TOKEN__", api_token)
            )
            data = content.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def _serialize_files(
    files: list[VideoFile],
    planned_actions: dict[Path, str] | None = None,
    manual_rotations: dict[Path, int] | None = None,
) -> list[dict[str, object]]:
    fast_groups = group_fast(files)
    output = []
    for file in files:
        fast_ready = any(file in members and len(members) > 1 for members in fast_groups.values())
        file_size_info = _file_size_info(file.path)
        output.append(
            {
                "path": str(file.path),
                "name": file.path.name,
                "display_width": file.display_width,
                "display_height": file.display_height,
                "video_codec": file.video_codec,
                "audio_codec": file.audio_codec,
                "fps": f"{file.frame_rate_float:.2f}" if file.frame_rate_float else file.frame_rate,
                "duration": _format_duration(file.duration),
                "media_created_time": _format_media_created_time(file.media_created_at),
                "orientation": file.orientation.value,
                "manual_rotation": (manual_rotations or {}).get(file.path, file.manual_rotation),
                "fast_ready": fast_ready,
                "planned_action": (planned_actions or {}).get(file.path, "unknown"),
                **file_size_info,
            }
        )
    return output


def _build_gui_plan(
    all_files: list[VideoFile],
    selected_files: list[VideoFile],
    payload: dict[str, object],
) -> dict[str, object]:
    manual_rotations = _parse_rotation_overrides(payload, all_files)
    adjusted_all_files = [
        apply_clockwise_rotation(file, manual_rotations.get(file.path, 0))
        for file in all_files
    ]
    selected_paths = {file.path for file in selected_files}
    adjusted_selected_files = [
        file for file in adjusted_all_files if file.path in selected_paths
    ]
    mode = str(payload.get("mode") or MergeMode.optimal.value)
    actions = {file.path: "excluded" for file in adjusted_all_files}
    targets: list[dict[str, object]] = []

    if mode == MergeMode.fast.value:
        for members in group_fast(adjusted_selected_files).values():
            action = "copy" if len(members) > 1 else "skipped"
            for file in members:
                actions[file.path] = action
        for file in adjusted_selected_files:
            if manual_rotations.get(file.path, 0):
                actions[file.path] = "rotation_required"
    elif mode == MergeMode.extreme.value:
        if adjusted_selected_files:
            plan = build_extreme_group_plan(
                adjusted_selected_files,
                output_format=str(payload.get("output_format") or "mp4"),
                requested_video_codec=str(payload.get("video_codec") or "") or None,
                requested_audio_codec=str(payload.get("audio_codec") or "") or None,
                fps_policy=str(payload.get("fps_policy") or "majority"),
            )
            actions.update(plan.actions)
            targets.append(
                {
                    "orientation": "all",
                    "canvas": plan.canvas.label,
                    "fps": round(plan.fps, 3),
                    "video_codec": plan.codec_plan.video_codec,
                    "audio_codec": plan.codec_plan.audio_codec,
                    "copy_count": plan.copy_count,
                    "remux_count": plan.remux_count,
                    "audio_count": plan.audio_count,
                    "transcode_count": plan.transcode_count,
                }
            )
    else:
        groups = split_by_orientation(adjusted_selected_files)
        for orientation in (Orientation.landscape, Orientation.portrait):
            files = groups.get(orientation, [])
            if not files:
                continue
            plan = build_optimal_group_plan(
                files,
                output_format=str(payload.get("output_format") or "mp4"),
                requested_video_codec=str(payload.get("video_codec") or "") or None,
                requested_audio_codec=str(payload.get("audio_codec") or "") or None,
                fps_policy=str(payload.get("fps_policy") or "majority"),
                resolution_policy=str(payload.get("resolution_policy") or "dominant"),
            )
            actions.update(plan.actions)
            targets.append(
                {
                    "orientation": orientation.value,
                    "canvas": plan.canvas.label,
                    "fps": round(plan.fps, 3),
                    "video_codec": plan.codec_plan.video_codec,
                    "audio_codec": plan.codec_plan.audio_codec,
                    "copy_count": plan.copy_count,
                    "remux_count": plan.remux_count,
                    "audio_count": plan.audio_count,
                    "transcode_count": plan.transcode_count,
                }
            )

    counts = Counter(actions[file.path] for file in adjusted_selected_files)
    return {
        "files": _serialize_files(adjusted_all_files, actions, manual_rotations),
        "plan": {
            "mode": mode,
            "copy_count": counts["copy"],
            "remux_count": counts["remux"],
            "audio_count": counts["audio"],
            "transcode_count": counts["transcode"],
            "skipped_count": counts["skipped"],
            "rotation_blocked_count": counts["rotation_required"],
            "selected_count": len(adjusted_selected_files),
            "targets": targets,
        },
    }


def _parse_rotation_overrides(
    payload: dict[str, object],
    files: list[VideoFile],
) -> dict[Path, int]:
    raw_overrides = payload.get("rotation_overrides")
    if not isinstance(raw_overrides, dict):
        return {}
    allowed_paths = {str(file.path): file.path for file in files}
    rotations: dict[Path, int] = {}
    for raw_path, raw_rotation in raw_overrides.items():
        path = allowed_paths.get(str(raw_path))
        if path is None:
            continue
        rotation = validate_clockwise_rotation(raw_rotation)
        if rotation:
            rotations[path] = rotation
    return rotations


def _file_size_info(path: Path) -> dict[str, object]:
    try:
        stat = path.stat()
    except OSError:
        return {
            "file_size": "",
            "file_size_bytes": 0,
        }
    return {
        "file_size": _format_file_size(stat.st_size),
        "file_size_bytes": stat.st_size,
    }


def _format_media_created_time(timestamp: float | None) -> str:
    if timestamp is None:
        return ""
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _format_file_size(size: int) -> str:
    value = float(max(size, 0))
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024


def _recommended_gpu_mode(gpu_encoders: list[str]) -> str:
    available = set(gpu_encoders)
    system = platform.system()
    if system == "Darwin" and {"h264_videotoolbox", "hevc_videotoolbox"} & available:
        return "auto"
    if system == "Windows":
        for encoder in ("h264_nvenc", "hevc_nvenc", "h264_qsv", "hevc_qsv", "h264_amf", "hevc_amf"):
            if encoder in available:
                return "auto"
    if system == "Linux":
        for encoder in ("h264_nvenc", "hevc_nvenc", "h264_qsv", "hevc_qsv"):
            if encoder in available:
                return "auto"
    return "off"


def _detect_gui_ffmpeg_encoders(tools) -> set[str]:
    attempts = (5, 10, 15) if platform.system() == "Darwin" else (5,)
    encoders: set[str] = set()
    for timeout in attempts:
        encoders = detect_ffmpeg_encoders(tools, timeout=timeout)
        if platform.system() != "Darwin" and encoders:
            return encoders
        if any(encoder.endswith("_videotoolbox") for encoder in encoders):
            return encoders
        time.sleep(0.35)
    return encoders


def _open_media_file(path: Path) -> None:
    system = platform.system()
    if system == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    command = ["open", str(path)] if system == "Darwin" else ["xdg-open", str(path)]
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **subprocess_window_kwargs(),
    )


def _request_notification_permission() -> tuple[bool, str]:
    if platform.system() != "Darwin":
        return True, "Notification permission is not pre-requested on this platform."
    try:
        return _request_macos_notification_permission()
    except Exception as exc:
        return False, str(exc)


def _request_macos_notification_permission() -> tuple[bool, str]:
    try:
        from UserNotifications import (  # type: ignore[import-not-found]
            UNAuthorizationOptionAlert,
            UNAuthorizationOptionSound,
            UNUserNotificationCenter,
        )
    except Exception as exc:
        return False, f"macOS notification framework unavailable: {exc}"

    completed = threading.Event()
    result = {"ok": False, "message": "Permission request timed out."}

    def completion(granted, error) -> None:  # type: ignore[no-untyped-def]
        result["ok"] = bool(granted)
        result["message"] = str(error) if error else ("Notification permission granted." if granted else "Notification permission denied.")
        completed.set()

    center = UNUserNotificationCenter.currentNotificationCenter()
    center.requestAuthorizationWithOptions_completionHandler_(
        UNAuthorizationOptionAlert | UNAuthorizationOptionSound,
        completion,
    )
    completed.wait(timeout=5)
    return bool(result["ok"]), str(result["message"])


def _show_system_notification(title: str, body: str, sound: bool) -> tuple[bool, str]:
    system = platform.system()
    try:
        if system == "Darwin":
            return _show_macos_notification(title, body, sound)
        if system == "Windows":
            return _show_windows_notification(title, body, sound)
    except Exception as exc:
        return False, str(exc)
    return False, f"System notifications are not implemented for {system or 'this platform'}."


def _show_macos_notification(title: str, body: str, sound: bool) -> tuple[bool, str]:
    permission_result = _request_macos_notification_permission()
    _request_macos_dock_attention()
    errors = []
    for notifier in (_show_macos_notification_with_nsusernotification, _show_macos_notification_with_usernotifications):
        result = notifier(title, body, sound)
        if result[0]:
            return result
        errors.append(result[1])
    message = "; ".join(error for error in errors if error) or permission_result[1] or "macOS notification failed."
    return False, message


def _request_macos_dock_attention() -> tuple[bool, str]:
    try:
        from AppKit import NSApplication, NSCriticalRequest  # type: ignore[import-not-found]

        app = NSApplication.sharedApplication()
        app.requestUserAttention_(NSCriticalRequest)
        return True, "Dock attention requested."
    except Exception as exc:
        return False, str(exc)


def _show_macos_notification_with_nsusernotification(title: str, body: str, sound: bool) -> tuple[bool, str]:
    try:
        from Foundation import (  # type: ignore[import-not-found]
            NSUserNotification,
            NSUserNotificationCenter,
            NSUserNotificationDefaultSoundName,
        )
    except Exception as exc:
        return False, f"NSUserNotification unavailable: {exc}"

    notification = NSUserNotification.alloc().init()
    notification.setTitle_(title)
    notification.setInformativeText_(body)
    if sound:
        notification.setSoundName_(NSUserNotificationDefaultSoundName)
    NSUserNotificationCenter.defaultUserNotificationCenter().deliverNotification_(notification)
    return True, "macOS notification sent by VideoMergingTool."


def _show_macos_notification_with_usernotifications(title: str, body: str, sound: bool) -> tuple[bool, str]:
    try:
        from UserNotifications import (  # type: ignore[import-not-found]
            UNMutableNotificationContent,
            UNNotificationRequest,
            UNNotificationSound,
            UNTimeIntervalNotificationTrigger,
            UNUserNotificationCenter,
        )
    except Exception as exc:
        return False, f"macOS notification framework unavailable: {exc}"

    identifier = f"videomerge-{int(time.time() * 1000)}"
    content = UNMutableNotificationContent.alloc().init()
    content.setTitle_(title)
    content.setBody_(body)
    if sound:
        content.setSound_(UNNotificationSound.defaultSound())
    trigger = UNTimeIntervalNotificationTrigger.triggerWithTimeInterval_repeats_(0.1, False)
    request = UNNotificationRequest.requestWithIdentifier_content_trigger_(identifier, content, trigger)
    center = UNUserNotificationCenter.currentNotificationCenter()
    center.addNotificationRequest_withCompletionHandler_(request, None)
    return True, "macOS notification sent."


def _show_windows_notification(title: str, body: str, sound: bool) -> tuple[bool, str]:
    script = _windows_notification_script(title, body, sound)
    subprocess.Popen(
        ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **subprocess_window_kwargs(),
    )
    return True, "Windows notification requested."


def _windows_notification_script(title: str, body: str, sound: bool) -> str:
    title_ps = _powershell_single_quote(title)
    body_ps = _powershell_single_quote(body)
    sound_ps = "$true" if sound else "$false"
    return f"""
$ErrorActionPreference = 'Stop'
try {{
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing
  $notify = New-Object System.Windows.Forms.NotifyIcon
  $notify.Icon = [System.Drawing.SystemIcons]::Information
  $notify.BalloonTipTitle = {title_ps}
  $notify.BalloonTipText = {body_ps}
  $notify.Visible = $true
  if ({sound_ps}) {{ [System.Media.SystemSounds]::Asterisk.Play() }}
  $notify.ShowBalloonTip(5000)
  [System.Windows.Forms.Application]::DoEvents()
  Start-Sleep -Seconds 6
  $notify.Dispose()
}} catch {{
  if ({sound_ps}) {{ [System.Media.SystemSounds]::Asterisk.Play() }}
}}
"""


def _powershell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _build_merge_command(payload: dict[str, object]) -> list[str]:
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "merge", str(payload["input_dir"])]
    else:
        main_py = Path(__file__).resolve().parents[1] / "main.py"
        cmd = [sys.executable, str(main_py), "merge", str(payload["input_dir"])]
    cmd.extend(["--mode", str(payload.get("mode") or MergeMode.optimal.value)])
    cmd.extend(["--output-format", str(payload.get("output_format") or "mp4")])
    cmd.extend(["--check-level", str(payload.get("check_level") or "quick")])
    cmd.extend(["--on-error", str(payload.get("on_error") or "stop")])
    for key, flag in (("report_file", "--report-file"), ("log_file", "--log-file")):
        if payload.get(key):
            cmd.extend([flag, str(payload[key])])
    if payload.get("name"):
        cmd.extend(["--name", str(payload["name"])])
    if payload.get("output_dir"):
        cmd.extend(["--output-dir", str(payload["output_dir"])])
    if payload.get("sort_by"):
        cmd.extend(["--sort-by", str(payload["sort_by"])])
    if payload.get("video_codec"):
        cmd.extend(["--video-codec", str(payload["video_codec"])])
    if payload.get("gpu"):
        cmd.extend(["--gpu", str(payload["gpu"])])
    if payload.get("gpu_workers"):
        cmd.extend(["--gpu-workers", str(payload["gpu_workers"])])
    if payload.get("audio_codec"):
        cmd.extend(["--audio-codec", str(payload["audio_codec"])])
    if payload.get("quality_profile"):
        cmd.extend(["--quality-profile", str(payload["quality_profile"])])
    cmd.extend(["--crf", str(payload.get("crf", 23))])
    if payload.get("preset"):
        cmd.extend(["--preset", str(payload["preset"])])
    if payload.get("fps_policy"):
        cmd.extend(["--fps-policy", str(payload["fps_policy"])])
    if payload.get("resolution_policy"):
        cmd.extend(["--resolution-policy", str(payload["resolution_policy"])])
    if payload.get("pad_color"):
        cmd.extend(["--pad-color", str(payload["pad_color"])])
    if payload.get("ffmpeg_path"):
        cmd.extend(["--ffmpeg-path", str(payload["ffmpeg_path"])])
    if payload.get("ffprobe_path"):
        cmd.extend(["--ffprobe-path", str(payload["ffprobe_path"])])
    if payload.get("temp_dir"):
        cmd.extend(["--temp-dir", str(payload["temp_dir"])])
    selected_file_list = _write_selected_file_list(payload)
    if selected_file_list:
        cmd.extend(["--selected-files", str(selected_file_list)])
    if not payload.get("recursive", True):
        cmd.append("--no-recursive")
    if payload.get("overwrite"):
        cmd.append("--overwrite")
    if payload.get("dry_run"):
        cmd.append("--dry-run")
    if payload.get("keep_temp"):
        cmd.append("--keep-temp")
    if not payload.get("auto_download_deps", True):
        cmd.append("--no-auto-download-deps")
    return cmd


def _write_selected_file_list(payload: dict[str, object]) -> Path | None:
    selected = payload.get("selected_files")
    if not isinstance(selected, list):
        return None
    paths = [str(path) for path in selected if isinstance(path, str) and path]
    raw_rotations = payload.get("rotation_overrides")
    rotations: dict[str, int] = {}
    if isinstance(raw_rotations, dict):
        for path in paths:
            if path not in raw_rotations:
                continue
            rotation = validate_clockwise_rotation(raw_rotations[path])
            if rotation:
                rotations[path] = rotation
    entries: list[object]
    if rotations:
        entries = [
            {"path": path, "rotate_clockwise": rotations.get(path, 0)}
            for path in paths
        ]
    else:
        entries = paths
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", prefix="videomerge_selected_", delete=False)
    with handle:
        json.dump(entries, handle, ensure_ascii=False)
    return Path(handle.name)


def _run_merge(command: list[str], state: GuiState) -> None:
    state.log("Starting merge task.")
    process = None
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_process_group_kwargs(),
        )
        if state.start_process(process):
            _terminate_process(process)
        assert process.stdout is not None
        for line in process.stdout:
            stripped = line.rstrip()
            if "TASK_EVENT:" in stripped:
                try:
                    event = json.loads(stripped.split("TASK_EVENT:", 1)[1])
                    with state.lock:
                        if event.pop("incremental", False):
                            previous = state.result or {"checks": [], "skipped": [], "outputs": []}
                            for field in ("checks", "skipped"):
                                by_path = {item["path"]: item for item in previous.get(field, [])}
                                by_path.update({item["path"]: item for item in event.get(field, [])})
                                event[field] = list(by_path.values())
                            event["outputs"] = previous.get("outputs", [])
                        state.result = event
                except (ValueError, TypeError):
                    pass
                continue
            temp_match = re.search(r"(?:Preprocessing|Concat) temp directory:\s+(.+)$", stripped)
            if temp_match:
                state.record_temp_path(Path(temp_match.group(1).strip()))
            staging_match = re.search(r"Staging output:\s+(.+)$", stripped)
            if staging_match:
                state.record_temp_path(Path(staging_match.group(1).strip()))
            progress_match = re.search(r"Progress:\s+(\d+)/(\d+)\s+\((\d+)%\)", stripped)
            if progress_match:
                state.set_progress(int(progress_match.group(3)))
            if _is_useful_process_log(stripped):
                state.log(stripped)
        code = process.wait()
        was_cancelled = state.finish_process()
        if was_cancelled:
            with state.lock:
                state.result = {"checks": [], "skipped": [], "outputs": [], "error": "", **(state.result or {}), "status": "cancelled"}
            state.log("Merge stopped by user.")
            _cleanup_cancel_temp_dirs(state)
        elif code == 0:
            state.set_progress(100)
            state.log("Merge partially completed; review skipped inputs." if state.result and state.result.get("status") == "partial" else "Merge completed.")
        else:
            state.log(f"ERROR: Merge failed with exit code {code}.")
            with state.lock:
                state.result = {"checks": [], "skipped": [], "outputs": [], "error": "", **(state.result or {}), "status": "failed"}
    except Exception as exc:
        if process is not None and process.poll() is None:
            _terminate_process(process)
        state.log(f"ERROR: {exc}")
        with state.lock:
            state.result = {"status": "failed", "error": str(exc), "checks": [], "skipped": [], "outputs": []}
    finally:
        if process is not None and process.stdout is not None and hasattr(process.stdout, "close"):
            process.stdout.close()
        _cleanup_selected_file_list(command)
        state.finish_process()
        if state.result and "--report-file" in command:
            try:
                report = Path(command[command.index("--report-file") + 1])
                report.write_text(json.dumps(state.result, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError as exc:
                state.log(f"WARNING: Could not save task report: {exc}")


def _is_useful_process_log(message: str) -> bool:
    if not message:
        return False
    if re.search(r"Progress:\s+\d+/\d+\s+\(\d+%\)", message):
        return False
    if re.search(r"(?:Preprocessing|Concat) temp directory:\s+", message):
        return False
    if "Staging output:" in message or message.startswith("Command:"):
        return False
    return True


def _cleanup_selected_file_list(command: list[str]) -> None:
    try:
        index = command.index("--selected-files")
    except ValueError:
        return
    if index + 1 >= len(command):
        return
    path = Path(command[index + 1])
    if path.name.startswith("videomerge_selected_") and path.suffix == ".json":
        path.unlink(missing_ok=True)


def _cleanup_cancel_temp_dirs(state: GuiState) -> None:
    cleaned = 0
    for path in state.consume_cancel_cleanup_paths():
        if re.fullmatch(r"\..+\.[0-9a-f]{32}\.partial\.[a-z0-9]+", path.name):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                state.log(f"WARNING: Staging cleanup failed: {path} | {exc}")
            continue
        if not path.name.startswith(("videomerge_preprocess_", "videomerge_concat_")):
            state.log(f"Skipped unsafe temp cleanup path: {path}")
            continue
        try:
            if path.exists():
                shutil.rmtree(path)
                cleaned += 1
        except Exception as exc:
            state.log(f"WARNING: Temporary cleanup failed: {path} | {exc}")
    state.log(f"Temporary files cleaned after stop: {cleaned} folder(s).")


def _terminate_process(process: subprocess.Popen[str]) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                **subprocess_window_kwargs(),
            )
        else:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _process_group_kwargs() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {"start_new_session": True}


def _gui_logger(state: GuiState) -> logging.Logger:
    logger = logging.getLogger(f"videomerge.webgui.{id(state)}")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = QueueLogHandler(state)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)
    return logger


def _system_ui_language() -> str:
    system = platform.system()
    if system == "Windows":
        try:
            import ctypes

            language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "zh" if language_id & 0x3FF == 0x04 else "en"
        except (AttributeError, OSError):
            pass
    if system == "Darwin":
        try:
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleLanguages"],
                capture_output=True,
                text=True,
                timeout=2,
                **subprocess_window_kwargs(),
            )
            if result.returncode == 0:
                languages = re.findall(r"[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]+)*", result.stdout)
                if languages:
                    return "zh" if languages[0].lower().startswith("zh") else "en"
        except (OSError, subprocess.TimeoutExpired):
            pass
    language = os.environ.get("LANGUAGE") or os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES")
    if not language:
        language = (locale.getlocale()[0] or os.environ.get("LANG") or "en")
    return "zh" if language.lower().startswith("zh") else "en"


def _picker_language(language: str) -> str:
    return "zh" if language.lower().startswith("zh") else "en"


def _dialog_language(requested_language: str) -> str:
    # Native dialog chrome follows the OS; never give a Chinese shell English captions.
    if _system_ui_language() == "zh":
        return "zh"
    return _picker_language(requested_language)


def _pick_folder(kind: str, language: str = "en") -> str:
    language = _picker_language(language)
    title = PICKER_TEXT[language].get(kind, PICKER_TEXT[language]["folder"])
    if platform.system() == "Darwin":
        selected = _pick_folder_macos(title)
        _remember_picker_dir(kind, selected)
        return selected
    if platform.system() == "Windows":
        selected = _pick_folder_windows(title, _last_picker_dir(kind), language)
        if selected is None:
            selected = _pick_folder_tk(title)
            _remember_picker_dir(kind, selected)
            return selected
        _remember_picker_dir(kind, selected)
        return selected
    selected = _pick_folder_tk(title)
    _remember_picker_dir(kind, selected)
    return selected


def _pick_video_files(language: str = "en") -> list[str]:
    language = _picker_language(language)
    title = PICKER_TEXT[language]["files"]
    initial_dir = _last_picker_dir("source")
    if platform.system() == "Darwin":
        selected = _pick_video_files_macos(title)
    elif platform.system() == "Windows":
        selected = _pick_video_files_windows(title, initial_dir, language)
        if selected is None:
            selected = _pick_video_files_tk(title, initial_dir, language)
    else:
        selected = _pick_video_files_tk(title, initial_dir, language)
    normalized = _normalize_picked_video_files(selected or [])
    if normalized:
        _remember_picker_dir("source", normalized[0])
    return normalized


def _normalize_picked_video_files(values: list[str]) -> list[str]:
    paths: list[str] = []
    seen: set[Path] = set()
    for value in values:
        if not value:
            continue
        path = Path(value.strip().strip('"')).expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_file() or resolved.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        seen.add(resolved)
        paths.append(str(resolved))
    return paths


def _common_input_dir(paths: list[str]) -> str:
    if not paths:
        return ""
    try:
        common = Path(os.path.commonpath(paths))
    except ValueError:
        return str(Path(paths[0]).parent)
    return str(common.parent if common.is_file() else common)


def _validate_selected_source_files(
    values: list[object],
    input_dir: Path,
    sort_by: str,
) -> list[Path]:
    root = input_dir.expanduser().resolve()
    paths: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        path = Path(value).expanduser().resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Selected source file is outside the source root: {path}") from exc
        if path in seen:
            continue
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError(f"Selected source file is not a supported video: {path}")
        seen.add(path)
        paths.append(path)
    if not paths:
        raise ValueError("No supported source video files were selected.")
    return sort_video_paths(paths, root, sort_by)


def _pick_video_files_macos(title: str) -> list[str]:
    escaped_title = title.replace('"', '\\"')
    script = f'''
set chosenFiles to choose file with prompt "{escaped_title}" with multiple selections allowed
set output to ""
repeat with chosenFile in chosenFiles
    set output to output & POSIX path of chosenFile & linefeed
end repeat
return output
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **subprocess_window_kwargs(),
        )
        if result.returncode == 0:
            return [line for line in result.stdout.splitlines() if line]
    except Exception:
        return []
    return []


def _pick_video_files_windows(title: str, initial_dir: str | None = None, language: str = "en") -> list[str] | None:
    escaped_title = title.replace("'", "''")
    escaped_initial = (initial_dir or "").replace("'", "''")
    picker_text = PICKER_TEXT[_picker_language(language)]
    escaped_video_filter = picker_text["video_filter"].replace("'", "''")
    escaped_all_filter = picker_text["all_filter"].replace("'", "''")
    script = r'''
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = '__TITLE__'
$dialog.Multiselect = $true
$dialog.CheckFileExists = $true
$dialog.AutoUpgradeEnabled = $true
$dialog.Filter = '__VIDEO_FILTER__|*.mp4;*.mkv;*.mov;*.avi;*.ts;*.m4v;*.flv;*.webm;*.wmv|__ALL_FILTER__|*.*'
$initial = '__INITIAL_DIR__'
if ($initial -and (Test-Path -LiteralPath $initial -PathType Container)) {
  $dialog.InitialDirectory = $initial
}
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  $dialog.FileNames | ForEach-Object { Write-Output $_ }
}
'''.replace("__TITLE__", escaped_title).replace("__INITIAL_DIR__", escaped_initial).replace(
        "__VIDEO_FILTER__", escaped_video_filter
    ).replace("__ALL_FILTER__", escaped_all_filter)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **subprocess_window_kwargs(),
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        return None
    return None


def _pick_video_files_tk(title: str, initial_dir: str | None = None, language: str = "en") -> list[str]:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        picker_text = PICKER_TEXT[_picker_language(language)]
        selected = filedialog.askopenfilenames(
            title=title,
            initialdir=initial_dir or None,
            filetypes=[
                (picker_text["video_filter"], "*.mp4 *.mkv *.mov *.avi *.ts *.m4v *.flv *.webm *.wmv"),
                (picker_text["all_filter"], "*.*"),
            ],
            parent=root,
        )
        root.destroy()
        return list(selected)
    except Exception:
        return []


def _pick_folder_macos(title: str) -> str:
    script = 'POSIX path of (choose folder with prompt "{}")'.format(title)
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **subprocess_window_kwargs(),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        return ""
    return ""


def _pick_folder_windows(title: str, initial_dir: str | None = None, language: str = "en") -> str | None:
    escaped_title = title.replace("'", "''")
    escaped_initial = (initial_dir or "").replace("'", "''")
    picker_text = PICKER_TEXT[_picker_language(language)]
    escaped_placeholder = picker_text["folder_placeholder"].replace("'", "''")
    escaped_filter = picker_text["all_filter"].replace("'", "''")
    script = r"""
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = '__TITLE__'
$dialog.CheckFileExists = $false
$dialog.ValidateNames = $false
$dialog.DereferenceLinks = $true
$dialog.AutoUpgradeEnabled = $true
$dialog.Filter = '__ALL_FILTER__|*.*'
$dialog.FileName = '__FOLDER_PLACEHOLDER__'
$initial = '__INITIAL_DIR__'
if (-not $initial -or -not (Test-Path -LiteralPath $initial -PathType Container)) {
  $initial = [Environment]::GetFolderPath('MyVideos')
}
if (-not $initial -or -not (Test-Path -LiteralPath $initial -PathType Container)) {
  $initial = [Environment]::GetFolderPath('UserProfile')
}
if ($initial -and (Test-Path -LiteralPath $initial -PathType Container)) {
  $dialog.InitialDirectory = $initial
}
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  $selected = $dialog.FileName
  if (Test-Path -LiteralPath $selected -PathType Container) {
    Write-Output $selected
  } else {
    Write-Output (Split-Path -Parent $selected)
  }
}
""".replace("__TITLE__", escaped_title).replace("__INITIAL_DIR__", escaped_initial).replace(
        "__ALL_FILTER__", escaped_filter
    ).replace("__FOLDER_PLACEHOLDER__", escaped_placeholder)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **subprocess_window_kwargs(),
        )
        if result.returncode == 0:
            return _normalize_picked_folder(result.stdout.strip())
    except Exception:
        return None
    return None


def _normalize_picked_folder(path_text: str) -> str:
    path_text = path_text.strip().strip('"')
    if not path_text:
        return ""
    path = Path(path_text)
    if path.name in {text["folder_placeholder"] for text in PICKER_TEXT.values()}:
        return str(path.parent)
    if path.exists() and path.is_file():
        return str(path.parent)
    return str(path)


def _default_display_paths(input_dir: str = "") -> dict[str, str]:
    defaults = {
        "output_dir": "",
        "temp_dir": tempfile.gettempdir(),
        "ffmpeg": "",
        "ffprobe": "",
    }
    if input_dir:
        candidate = Path(input_dir)
        if candidate.is_dir():
            defaults["output_dir"] = str(candidate / "merged")

    logger = logging.getLogger("videomerge.gui.defaults")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    try:
        tools = resolve_tools(logger, False, default_tools_dir())
        defaults["ffmpeg"] = str(tools.ffmpeg)
        defaults["ffprobe"] = str(tools.ffprobe)
    except Exception:
        pass
    return defaults


def _config_dir() -> Path:
    frozen_dir = _frozen_writable_config_dir()
    if frozen_dir:
        return frozen_dir

    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "VideoMergingTool"
    if system == "Windows":
        root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        return Path(root) / "VideoMergingTool" if root else Path.home() / "AppData" / "Roaming" / "VideoMergingTool"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "VideoMergingTool"


def _frozen_writable_config_dir() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    if platform.system() == "Darwin":
        return None

    candidate = Path(sys.executable).resolve().parent / "config"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return candidate
    except OSError:
        return None


def _config_path() -> Path:
    return _config_dir() / "config.json"


def _load_gui_config() -> dict[str, object]:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_gui_config(payload: dict[str, object]) -> None:
    allowed = set(CONFIG_FIELD_IDS) | {"lang", "mode", "lastPickerDirs"}
    clean = {key: value for key, value in payload.items() if key in allowed}
    if "lastPickerDirs" not in clean:
        previous = _load_gui_config()
        if isinstance(previous.get("lastPickerDirs"), dict):
            clean["lastPickerDirs"] = previous["lastPickerDirs"]
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")


def _last_picker_dir(kind: str) -> str:
    picker_dirs = _load_gui_config().get("lastPickerDirs")
    if not isinstance(picker_dirs, dict):
        return ""
    value = picker_dirs.get(kind)
    if not isinstance(value, str) or not value:
        return ""
    return str(_nearest_existing_dir(Path(value)))


def _remember_picker_dir(kind: str, selected: str | None) -> None:
    if not selected:
        return
    try:
        selected_path = Path(selected)
        directory = selected_path if selected_path.is_dir() else selected_path.parent
        config = _load_gui_config()
        picker_dirs = config.get("lastPickerDirs")
        if not isinstance(picker_dirs, dict):
            picker_dirs = {}
        picker_dirs[kind] = str(directory)
        config["lastPickerDirs"] = picker_dirs
        _save_gui_config(config)
    except OSError:
        return


def _nearest_existing_dir(path: Path) -> Path:
    current = path.expanduser()
    while not current.exists() and current.parent != current:
        current = current.parent
    if current.exists() and current.is_file():
        return current.parent
    if current.exists() and current.is_dir():
        return current
    return Path.home()


def _pick_folder_tk(title: str) -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        selected = filedialog.askdirectory(title=title, mustexist=True, parent=root)
        root.destroy()
        return selected or ""
    except Exception:
        return ""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _format_duration(seconds: float) -> str:
    total = int(round(seconds))
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"
