from __future__ import annotations

import logging
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .env_check import resolve_tools
from .grouping import group_fast, split_by_orientation
from .models import MergeMode, Orientation, ToolPaths, VideoFile
from .probe import probe_files
from .scanner import scan_video_files


COLORS = {
    "bg": "#161715",
    "panel": "#1D1E1C",
    "panel_hover": "#252724",
    "input": "#121311",
    "border": "#2C2D2A",
    "border_focus": "#4A4D46",
    "text": "#FFFFFF",
    "secondary": "#9B9C98",
    "muted": "#666763",
    "red": "#E94E3D",
    "green": "#5E9C60",
    "yellow": "#D4A35B",
    "blue": "#3498DB",
    "console": "#0A0A0A",
}


class QueueLogHandler(logging.Handler):
    def __init__(self, output_queue: queue.Queue[tuple[str, object]]) -> None:
        super().__init__()
        self.output_queue = output_queue

    def emit(self, record: logging.LogRecord) -> None:
        self.output_queue.put(("log", self.format(record)))


class VideoMergeGUI:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("VideoMergingTool")
        self.root.geometry("1320x760")
        self.root.minsize(1040, 640)
        self.root.configure(bg=COLORS["bg"])

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.input_dir: Path | None = None
        self.tools: ToolPaths | None = None
        self.media_files: list[VideoFile] = []
        self.is_busy = False

        self.mode_var = tk.StringVar(value=MergeMode.optimal.value)
        self.name_var = tk.StringVar(value="Merged_Output")
        self.codec_var = tk.StringVar(value="h264")
        self.format_var = tk.StringVar(value="mp4")
        self.crf_var = tk.IntVar(value=20)
        self.dry_run_var = tk.BooleanVar(value=False)
        self.keep_temp_var = tk.BooleanVar(value=False)
        self.recursive_var = tk.BooleanVar(value=True)

        self._build_styles()
        self._build_layout()
        self._set_ffmpeg_status("FFmpeg Not Checked", "warn")
        self._set_summary("No folder selected")
        self._log("Select a source folder to begin.")
        self.root.after(100, self._process_events)

    def run(self) -> None:
        self.root.mainloop()

    def _build_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Files.Treeview",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            fieldbackground=COLORS["panel"],
            bordercolor=COLORS["border"],
            rowheight=30,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Files.Treeview.Heading",
            background=COLORS["panel"],
            foreground=COLORS["muted"],
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        )
        style.map("Files.Treeview", background=[("selected", COLORS["panel_hover"])])
        style.configure(
            "Dark.Horizontal.TProgressbar",
            troughcolor="#222222",
            background=COLORS["red"],
            bordercolor="#222222",
            lightcolor=COLORS["red"],
            darkcolor=COLORS["red"],
        )

    def _build_layout(self) -> None:
        self._build_header()

        main = tk.Frame(self.root, bg=COLORS["bg"])
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=0, minsize=360)
        main.rowconfigure(0, weight=1)

        self.left = tk.Frame(main, bg=COLORS["bg"], highlightthickness=1, highlightbackground=COLORS["border"])
        self.left.grid(row=0, column=0, sticky="nsew")
        self.right = tk.Frame(main, bg=COLORS["panel"], width=380)
        self.right.grid(row=0, column=1, sticky="nsew")
        self.right.grid_propagate(False)

        self._build_left_pane()
        self._build_right_pane()

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=COLORS["bg"], height=56, highlightthickness=1, highlightbackground=COLORS["border"])
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        logo = tk.Frame(header, bg=COLORS["bg"])
        logo.pack(side=tk.LEFT, padx=18)
        tk.Label(
            logo,
            text="VIDEO MERGE",
            bg=COLORS["bg"],
            fg=COLORS["text"],
            font=("Segoe UI", 13, "bold"),
        ).pack(side=tk.LEFT)
        tk.Label(logo, text="●", bg=COLORS["bg"], fg=COLORS["red"], font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=(4, 0))

        self.ffmpeg_badge = tk.Label(
            header,
            bg=COLORS["panel"],
            fg=COLORS["secondary"],
            bd=1,
            relief=tk.SOLID,
            padx=12,
            pady=4,
            font=("Segoe UI", 9),
        )
        self.ffmpeg_badge.pack(side=tk.RIGHT, padx=18)

    def _build_left_pane(self) -> None:
        header = tk.Frame(self.left, bg=COLORS["bg"], height=76)
        header.pack(fill=tk.X, padx=16, pady=(14, 8))
        header.columnconfigure(0, weight=1)

        tk.Label(header, text="Source Files", bg=COLORS["bg"], fg=COLORS["text"], font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.summary_label = tk.Label(
            header,
            text="",
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("Segoe UI", 8, "bold"),
        )
        self.summary_label.grid(row=1, column=0, sticky="w", pady=(8, 0))

        select_button = self._button(header, "▣  Select Folder", self.select_folder, secondary=True)
        select_button.grid(row=0, column=1, rowspan=2, sticky="e", padx=(8, 6))
        refresh_button = self._button(header, "↻", self.refresh_folder, icon=True)
        refresh_button.grid(row=0, column=2, rowspan=2, sticky="e")

        table_frame = tk.Frame(self.left, bg=COLORS["panel"], highlightthickness=1, highlightbackground=COLORS["border"])
        table_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 12))
        columns = ("filename", "resolution", "codec", "fps", "duration", "status")
        self.files_tree = ttk.Treeview(table_frame, columns=columns, show="headings", style="Files.Treeview")
        headings = {
            "filename": "FILENAME",
            "resolution": "RESOLUTION",
            "codec": "CODEC",
            "fps": "FPS",
            "duration": "DUR",
            "status": "STATUS",
        }
        widths = {
            "filename": 300,
            "resolution": 130,
            "codec": 120,
            "fps": 90,
            "duration": 90,
            "status": 140,
        }
        for col in columns:
            self.files_tree.heading(col, text=headings[col])
            self.files_tree.column(col, width=widths[col], anchor=tk.W)
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.files_tree.yview)
        self.files_tree.configure(yscrollcommand=scrollbar.set)
        self.files_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.files_tree.tag_configure("group", background=COLORS["bg"], foreground=COLORS["secondary"])
        self.files_tree.tag_configure("ok", foreground=COLORS["green"])
        self.files_tree.tag_configure("warn", foreground=COLORS["yellow"])

        self.plan_frame = tk.Frame(self.left, bg=COLORS["panel"], highlightthickness=1, highlightbackground=COLORS["border"])
        self.plan_frame.pack(fill=tk.X, padx=16, pady=(0, 16))
        self.plan_title = tk.Label(
            self.plan_frame,
            text="OPTIMAL MODE SELECTED",
            bg=COLORS["panel"],
            fg=COLORS["red"],
            font=("Segoe UI", 9, "bold"),
        )
        self.plan_title.pack(anchor="w", padx=12, pady=(12, 4))
        self.plan_text = tk.Label(
            self.plan_frame,
            text="Select a folder to preview the merge plan.",
            bg=COLORS["panel"],
            fg=COLORS["secondary"],
            justify=tk.LEFT,
            wraplength=820,
            font=("Segoe UI", 10),
        )
        self.plan_text.pack(anchor="w", fill=tk.X, padx=12, pady=(0, 12))

    def _build_right_pane(self) -> None:
        tk.Label(
            self.right,
            text="Configuration",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", padx=16, pady=(18, 24))

        content = tk.Frame(self.right, bg=COLORS["panel"])
        content.pack(fill=tk.BOTH, expand=True, padx=16)

        self._section_label(content, "MERGE STRATEGY")
        self.mode_cards: dict[str, tk.Frame] = {}
        self._mode_card(content, MergeMode.fast.value, "Fast Merge", "LOSSLESS", "Stream copy only. Skips incompatible groups.")
        self._mode_card(content, MergeMode.optimal.value, "Optimal Merge", "SMART", "Groups by orientation and transcodes when needed.")
        self._mode_card(content, MergeMode.extreme.value, "Extreme Merge", "BRUTE FORCE", "Normalizes all files into one output.")
        self._refresh_mode_cards()

        self._section_label(content, "OUTPUT SETTINGS", pady=(22, 8))
        self._labeled_entry(content, "OUTPUT FILENAME PREFIX", self.name_var)
        self._labeled_option(content, "OUTPUT FORMAT", self.format_var, ["mp4", "mkv", "mov", "webm"])
        self._labeled_option(content, "TARGET CODEC", self.codec_var, ["h264", "hevc", "vp9"])

        row = tk.Frame(content, bg=COLORS["panel"])
        row.pack(fill=tk.X, pady=(10, 12))
        tk.Label(row, text="CRF (QUALITY)\nLower = better", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(
            side=tk.LEFT
        )
        tk.Spinbox(
            row,
            from_=0,
            to=51,
            textvariable=self.crf_var,
            width=6,
            bg=COLORS["input"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief=tk.FLAT,
            justify=tk.RIGHT,
        ).pack(side=tk.RIGHT)

        self._check(content, "Recursive Scan", "Scan subfolders", self.recursive_var)
        self._check(content, "Dry Run", "Simulate FFmpeg commands only", self.dry_run_var)
        self._check(content, "Keep Temp Files", "Keep preprocessed files for inspection", self.keep_temp_var)

        self._build_console(content)

        dock = tk.Frame(self.right, bg=COLORS["panel"], highlightthickness=1, highlightbackground=COLORS["border"])
        dock.pack(fill=tk.X, side=tk.BOTTOM, padx=16, pady=16)
        self.start_button = self._button(dock, "▷  START MERGE", self.start_merge, primary=True)
        self.start_button.pack(fill=tk.X, pady=8)

    def _build_console(self, parent: tk.Widget) -> None:
        console = tk.Frame(parent, bg=COLORS["console"], highlightthickness=1, highlightbackground="#1A1A1A")
        console.pack(fill=tk.BOTH, expand=True, pady=(18, 0))
        header = tk.Frame(console, bg=COLORS["console"])
        header.pack(fill=tk.X, padx=12, pady=(10, 0))
        tk.Label(header, text="PROCESS CONSOLE", bg=COLORS["console"], fg=COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(
            side=tk.LEFT
        )
        self.progress_label = tk.Label(header, text="0%", bg=COLORS["console"], fg=COLORS["secondary"], font=("Segoe UI", 8, "bold"))
        self.progress_label.pack(side=tk.RIGHT)
        self.console = tk.Text(
            console,
            height=9,
            bg=COLORS["console"],
            fg=COLORS["secondary"],
            insertbackground=COLORS["text"],
            bd=0,
            highlightthickness=0,
            font=("Consolas", 9),
            wrap=tk.WORD,
        )
        self.console.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)
        self.progress = ttk.Progressbar(console, style="Dark.Horizontal.TProgressbar", mode="determinate", maximum=100)
        self.progress.pack(fill=tk.X, padx=12, pady=(0, 12))

    def _section_label(self, parent: tk.Widget, text: str, pady: tuple[int, int] = (0, 8)) -> None:
        tk.Label(parent, text=text, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(
            anchor="w", pady=pady
        )

    def _mode_card(self, parent: tk.Widget, value: str, title: str, badge: str, desc: str) -> None:
        frame = tk.Frame(parent, bg=COLORS["bg"], highlightthickness=1, highlightbackground=COLORS["border"], cursor="hand2")
        frame.pack(fill=tk.X, pady=5)
        frame.bind("<Button-1>", lambda _event, mode=value: self._set_mode(mode))
        top = tk.Frame(frame, bg=COLORS["bg"])
        top.pack(fill=tk.X, padx=12, pady=(10, 2))
        tk.Label(top, text=title, bg=COLORS["bg"], fg=COLORS["text"], font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        tk.Label(top, text=badge, bg=COLORS["panel_hover"], fg=COLORS["secondary"], font=("Segoe UI", 7, "bold")).pack(side=tk.RIGHT)
        tk.Label(frame, text=desc, bg=COLORS["bg"], fg=COLORS["secondary"], justify=tk.LEFT, wraplength=310, font=("Segoe UI", 9)).pack(
            anchor="w", padx=12, pady=(0, 10)
        )
        self.mode_cards[value] = frame

    def _labeled_entry(self, parent: tk.Widget, label: str, variable: tk.StringVar) -> None:
        self._section_label(parent, label, pady=(8, 4))
        entry = tk.Entry(parent, textvariable=variable, bg=COLORS["input"], fg=COLORS["text"], insertbackground=COLORS["text"], relief=tk.FLAT)
        entry.pack(fill=tk.X, ipady=7)

    def _labeled_option(self, parent: tk.Widget, label: str, variable: tk.StringVar, values: list[str]) -> None:
        self._section_label(parent, label, pady=(12, 4))
        menu = tk.OptionMenu(parent, variable, *values)
        menu.configure(bg=COLORS["input"], fg=COLORS["text"], activebackground=COLORS["panel_hover"], relief=tk.FLAT)
        menu["menu"].configure(bg=COLORS["input"], fg=COLORS["text"])
        menu.pack(fill=tk.X)

    def _check(self, parent: tk.Widget, title: str, desc: str, variable: tk.BooleanVar) -> None:
        row = tk.Frame(parent, bg=COLORS["panel"], highlightthickness=1, highlightbackground=COLORS["border"])
        row.pack(fill=tk.X, pady=5)
        text = tk.Frame(row, bg=COLORS["panel"])
        text.pack(side=tk.LEFT, padx=0, pady=8)
        tk.Label(text, text=title, bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(text, text=desc, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="w")
        tk.Checkbutton(
            row,
            variable=variable,
            bg=COLORS["panel"],
            activebackground=COLORS["panel"],
            selectcolor=COLORS["input"],
            fg=COLORS["text"],
        ).pack(side=tk.RIGHT)

    def _button(
        self,
        parent: tk.Widget,
        text: str,
        command,
        primary: bool = False,
        secondary: bool = False,
        icon: bool = False,
    ) -> tk.Button:
        bg = COLORS["text"] if primary else COLORS["bg"]
        fg = COLORS["bg"] if primary else COLORS["text"]
        if icon:
            fg = COLORS["secondary"]
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=COLORS["panel_hover"],
            activeforeground=fg,
            relief=tk.FLAT if primary else tk.SOLID,
            bd=0 if primary else 1,
            padx=14 if not icon else 8,
            pady=8,
            font=("Segoe UI", 9, "bold" if primary else "normal"),
            cursor="hand2",
        )

    def _set_mode(self, mode: str) -> None:
        self.mode_var.set(mode)
        self._refresh_mode_cards()
        self._update_plan()

    def _refresh_mode_cards(self) -> None:
        for value, frame in self.mode_cards.items():
            active = value == self.mode_var.get()
            frame.configure(highlightbackground=COLORS["red"] if active else COLORS["border"])

    def select_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select source video folder")
        if folder:
            self.input_dir = Path(folder)
            self.scan_folder()

    def refresh_folder(self) -> None:
        if self.input_dir is None:
            self.select_folder()
            return
        self.scan_folder()

    def scan_folder(self) -> None:
        if self.input_dir is None or self.is_busy:
            return
        self.is_busy = True
        self._set_progress(0)
        self._clear_table()
        self._log(f"Scanning {self.input_dir}")
        thread = threading.Thread(target=self._scan_worker, daemon=True)
        thread.start()

    def _scan_worker(self) -> None:
        assert self.input_dir is not None
        logger = self._queue_logger()
        try:
            self.events.put(("progress", 8))
            tools = resolve_tools(logger, True, Path.cwd() / ".tools" / "ffmpeg")
            self.tools = tools
            self.events.put(("ffmpeg", ("FFmpeg Installed", "ok")))
            paths = scan_video_files(self.input_dir, self.recursive_var.get())
            self.events.put(("progress", 25))
            media_files, failures = probe_files(paths, tools, logger)
            self.events.put(("scan_done", (media_files, failures, len(paths))))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def start_merge(self) -> None:
        if self.input_dir is None:
            messagebox.showwarning("No folder", "Select a source folder first.")
            return
        if self.is_busy:
            return
        self.is_busy = True
        self._set_progress(0)
        self._log(f"Starting {self.mode_var.get()} merge")
        threading.Thread(target=self._merge_worker, daemon=True).start()

    def _merge_worker(self) -> None:
        assert self.input_dir is not None
        cmd = self._build_merge_command()
        self.events.put(("log", "Command: " + " ".join(f'"{part}"' if " " in part else part for part in cmd)))
        self.events.put(("progress", 5))
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert process.stdout is not None
            for line in process.stdout:
                self.events.put(("log", line.rstrip()))
                self._maybe_update_progress_from_line(line)
            code = process.wait()
            if code == 0:
                self.events.put(("progress", 100))
                self.events.put(("done", "Merge completed."))
            else:
                self.events.put(("error", f"Merge failed with exit code {code}."))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _build_merge_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "merge", str(self.input_dir)]
        else:
            main_py = Path(__file__).resolve().parents[1] / "main.py"
            cmd = [sys.executable, str(main_py), "merge", str(self.input_dir)]
        cmd.extend(["--mode", self.mode_var.get()])
        cmd.extend(["--output-format", self.format_var.get()])
        name = self.name_var.get().strip()
        if name:
            cmd.extend(["--name", name])
        codec = self.codec_var.get()
        if codec:
            cmd.extend(["--video-codec", codec])
        cmd.extend(["--crf", str(self.crf_var.get())])
        if not self.recursive_var.get():
            cmd.append("--no-recursive")
        if self.dry_run_var.get():
            cmd.append("--dry-run")
        if self.keep_temp_var.get():
            cmd.append("--keep-temp")
        return cmd

    def _maybe_update_progress_from_line(self, line: str) -> None:
        lowered = line.lower()
        if "media:" in lowered:
            self.events.put(("progress", 18))
        elif "preprocess" in lowered:
            self.events.put(("progress", 45))
        elif "merge order" in lowered:
            self.events.put(("progress", 72))
        elif "output written" in lowered:
            self.events.put(("progress", 92))

    def _process_events(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._log(str(payload))
            elif kind == "progress":
                self._set_progress(int(payload))
            elif kind == "ffmpeg":
                label, state = payload  # type: ignore[misc]
                self._set_ffmpeg_status(str(label), str(state))
            elif kind == "scan_done":
                media_files, failures, total = payload  # type: ignore[misc]
                self._on_scan_done(media_files, failures, total)
            elif kind == "done":
                self._log(str(payload))
                self.is_busy = False
            elif kind == "error":
                self._log("ERROR: " + str(payload))
                self._set_progress(0)
                self.is_busy = False
                messagebox.showerror("VideoMergingTool", str(payload))
        self.root.after(100, self._process_events)

    def _on_scan_done(self, media_files: list[VideoFile], failures: dict[Path, str], total: int) -> None:
        self.media_files = media_files
        self._populate_table(media_files)
        groups = split_by_orientation(media_files)
        self._set_summary(f"{len(media_files)} files detected • {len(groups)} groups")
        if failures:
            self._log(f"{len(failures)} file(s) could not be analyzed.")
        self._update_plan()
        self._set_progress(100)
        self.is_busy = False

    def _populate_table(self, files: list[VideoFile]) -> None:
        self._clear_table()
        fast_groups = group_fast(files)
        by_orientation = split_by_orientation(files)
        for orientation in (Orientation.landscape, Orientation.portrait):
            group = by_orientation.get(orientation, [])
            if not group:
                continue
            max_width = max(file.display_width for file in group)
            max_height = max(file.display_height for file in group)
            self.files_tree.insert(
                "",
                tk.END,
                values=(f"{orientation.value.title()} Group ({max_width}x{max_height})", "", "", "", "", ""),
                tags=("group",),
            )
            for file in group:
                fast_ready = any(file in members and len(members) > 1 for members in fast_groups.values())
                status = "Ready" if fast_ready else "Needs Transcode"
                tag = "ok" if fast_ready else "warn"
                self.files_tree.insert(
                    "",
                    tk.END,
                    values=(
                        file.path.name,
                        f"{file.display_width}x{file.display_height}",
                        f"{file.video_codec}/{file.audio_codec or 'none'}",
                        f"{file.frame_rate_float:.2f}" if file.frame_rate_float else file.frame_rate,
                        _format_duration(file.duration),
                        status,
                    ),
                    tags=(tag,),
                )

    def _update_plan(self) -> None:
        mode = self.mode_var.get()
        self.plan_title.configure(text=f"{mode.upper()} MODE SELECTED")
        if not self.media_files:
            self.plan_text.configure(text="Select a folder to preview the merge plan.")
            return
        groups = split_by_orientation(self.media_files)
        if mode == MergeMode.fast.value:
            fast_group_count = sum(1 for members in group_fast(self.media_files).values() if len(members) > 1)
            text = f"Tool will stream-copy compatible groups only. {fast_group_count} group(s) can be merged without transcoding."
        elif mode == MergeMode.optimal.value:
            text = f"Tool will create up to {len(groups)} output file(s), separated by landscape and portrait display orientation."
        else:
            text = "Tool will normalize all files to one display canvas and produce one output file."
        self.plan_text.configure(text=text)

    def _clear_table(self) -> None:
        for item in self.files_tree.get_children():
            self.files_tree.delete(item)

    def _set_summary(self, text: str) -> None:
        self.summary_label.configure(text=text.upper())

    def _set_ffmpeg_status(self, text: str, state: str) -> None:
        color = COLORS["green"] if state == "ok" else COLORS["yellow"]
        self.ffmpeg_badge.configure(text=f"✓ {text}" if state == "ok" else f"! {text}", fg=color)

    def _set_progress(self, value: int) -> None:
        value = max(0, min(value, 100))
        self.progress.configure(value=value)
        self.progress_label.configure(text=f"{value}%")

    def _log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.console.insert(tk.END, f"[{stamp}] {message}\n")
        self.console.see(tk.END)

    def _queue_logger(self) -> logging.Logger:
        logger = logging.getLogger(f"videomerge.gui.{id(self)}")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = QueueLogHandler(self.events)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(handler)
        return logger


def _format_duration(seconds: float) -> str:
    total = int(round(seconds))
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def launch_gui() -> None:
    try:
        app = VideoMergeGUI()
        app.run()
    except tk.TclError as exc:
        raise RuntimeError(f"Could not start GUI: {exc}") from exc
