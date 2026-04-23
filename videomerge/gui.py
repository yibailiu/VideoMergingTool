from __future__ import annotations

import json
import logging
import os
import platform
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .env_check import resolve_tools
from .grouping import group_fast, split_by_orientation
from .gpu import detect_ffmpeg_encoders
from .models import MergeMode, Orientation, VideoFile
from .probe import probe_files
from .scanner import scan_video_files


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VideoMergingTool</title>
  <style>
    :root {
      --bg-body: #161715;
      --bg-panel: #1D1E1C;
      --bg-panel-hover: #252724;
      --bg-input: #121311;
      --border-subtle: #2C2D2A;
      --border-focus: #4A4D46;
      --text-primary: #FFFFFF;
      --text-secondary: #9B9C98;
      --text-muted: #666763;
      --accent-red: #E94E3D;
      --accent-green: #5E9C60;
      --accent-yellow: #D4A35B;
      --accent-blue: #3498DB;
      --radius-panel: 8px;
      --radius-input: 6px;
      --radius-pill: 9999px;
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      --font-mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, Courier, monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg-body);
      color: var(--text-primary);
      font-family: var(--font-sans);
      font-size: 14px;
      height: 100vh;
      min-width: 1180px;
      min-height: 720px;
      overflow: hidden;
      -webkit-font-smoothing: antialiased;
    }
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--border-subtle); border-radius: var(--radius-pill); }
    header {
      height: 56px;
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 24px;
      background: var(--bg-body);
    }
    .logo { font-size: 18px; font-weight: 800; letter-spacing: -.03em; display: flex; align-items: center; gap: 8px; }
    .logo-dot { width: 6px; height: 6px; background: var(--accent-red); border-radius: 50%; }
    .dep-badge {
      color: var(--accent-green);
      background: var(--bg-panel);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-pill);
      padding: 4px 12px;
      font-size: 12px;
    }
    .main {
      display: grid;
      grid-template-columns: minmax(760px, 1fr) 420px;
      height: calc(100vh - 56px);
      min-height: 664px;
    }
    .left {
      border-right: 1px solid var(--border-subtle);
      display: grid;
      grid-template-rows: 86px minmax(240px, 1fr) auto 78px;
      min-width: 0;
      overflow: hidden;
    }
    .right {
      background: var(--bg-panel);
      display: grid;
      grid-template-rows: 66px minmax(0, 1fr) 84px;
      overflow: hidden;
    }
    .pane-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 16px 24px 12px;
      border-bottom: 1px solid var(--border-subtle);
    }
    h2 { font-size: 16px; font-weight: 700; }
    h3, .label-micro {
      font-size: 11px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: .08em;
      font-weight: 800;
    }
    .summary { margin-top: 12px; }
    .toolbar { display: flex; gap: 8px; align-items: center; }
    button {
      font: inherit;
      cursor: pointer;
      border: 1px solid var(--border-subtle);
      background: var(--bg-body);
      color: var(--text-primary);
      border-radius: var(--radius-pill);
      padding: 9px 16px;
      transition: background .16s, border-color .16s, transform .16s;
    }
    button:hover { background: var(--bg-panel-hover); border-color: var(--border-focus); }
    button:active { transform: scale(.98); }
    .btn-icon { border-radius: var(--radius-input); padding: 8px 10px; color: var(--text-secondary); }
    .btn-primary {
      width: 100%;
      background: var(--text-primary);
      color: var(--bg-body);
      border: none;
      border-radius: var(--radius-pill);
      font-weight: 800;
      padding: 14px 24px;
    }
    .btn-primary.stop {
      background: var(--accent-red);
      color: var(--text-primary);
    }
    .table-wrap {
      margin: 24px;
      margin-bottom: 12px;
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-panel);
      overflow: auto;
      background: var(--bg-panel);
      min-height: 0;
    }
    table { width: 100%; min-width: 760px; border-collapse: collapse; table-layout: fixed; }
    th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: var(--bg-panel);
      color: var(--text-muted);
      text-align: left;
      padding: 11px 16px;
      border-bottom: 1px solid var(--border-subtle);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .08em;
    }
    td {
      padding: 10px 16px;
      border-bottom: 1px solid var(--border-subtle);
      color: var(--text-secondary);
      font-size: 13px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .mono { font-family: var(--font-mono); }
    .group-row td {
      background: var(--bg-body);
      color: var(--text-secondary);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .06em;
    }
    .status-ok { color: var(--accent-green); }
    .status-warn { color: var(--accent-yellow); }
    .console {
      margin: 0 24px 12px;
      background: #0A0A0A;
      border: 1px solid #1A1A1A;
      border-radius: var(--radius-panel);
      padding: 14px;
      min-height: 0;
      display: grid;
      grid-template-rows: 18px minmax(0, 1fr) 4px;
      gap: 8px;
      height: 230px;
      min-height: 150px;
      max-height: 42vh;
      resize: vertical;
      overflow: hidden;
    }
    .console-head { display: flex; justify-content: space-between; }
    .logs {
      overflow: auto;
      font-family: var(--font-mono);
      color: var(--text-muted);
      font-size: 12px;
      line-height: 1.5;
      white-space: pre-wrap;
    }
    .bar { height: 4px; background: #222; border-radius: 2px; overflow: hidden; }
    .bar-fill { height: 100%; width: 0%; background: var(--accent-red); transition: width .2s; }
    .plan {
      margin: 0 24px 18px;
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-panel);
      background: var(--bg-panel);
      padding: 14px 16px;
      overflow: hidden;
    }
    .plan-title { color: var(--accent-red); margin-bottom: 8px; }
    .plan-text { color: var(--text-secondary); font-size: 13px; }
    .config-title { padding: 18px 24px; border-bottom: 1px solid var(--border-subtle); }
    .config-scroll { overflow: auto; padding: 24px; min-height: 0; }
    .mode-list { display: grid; gap: 10px; margin-top: 12px; }
    .mode-card {
      background: var(--bg-body);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-panel);
      padding: 14px 16px;
      cursor: pointer;
    }
    .mode-card.active { border-color: var(--accent-red); background: rgba(233,78,61,.04); }
    .mode-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px; }
    .mode-title { font-weight: 800; }
    .badge {
      font-size: 10px;
      color: var(--text-secondary);
      background: var(--bg-panel-hover);
      border-radius: 4px;
      padding: 2px 7px;
      text-transform: uppercase;
      letter-spacing: .06em;
    }
    .mode-card.active .badge.opt { color: var(--accent-blue); background: rgba(52,152,219,.18); }
    .mode-card.active .badge.fast { color: var(--accent-green); background: rgba(94,156,96,.18); }
    .mode-card.active .badge.extreme { color: var(--accent-red); background: rgba(233,78,61,.18); }
    .mode-desc { color: var(--text-secondary); font-size: 12px; line-height: 1.4; }
    .section { margin-top: 26px; }
    label { display: block; margin: 12px 0 6px; }
    input:not([type="checkbox"]), select {
      width: 100%;
      background: var(--bg-input);
      color: var(--text-primary);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-input);
      padding: 10px 12px;
      font: inherit;
    }
    input[type="checkbox"] {
      appearance: none;
      -webkit-appearance: none;
      width: 36px;
      height: 20px;
      flex: 0 0 36px;
      border: 1px solid var(--border-focus);
      border-radius: var(--radius-pill);
      background: var(--bg-input);
      position: relative;
      cursor: pointer;
      padding: 0;
      margin-top: 2px;
    }
    input[type="checkbox"]::after {
      content: "";
      position: absolute;
      width: 14px;
      height: 14px;
      top: 2px;
      left: 2px;
      border-radius: 50%;
      background: var(--text-secondary);
      transition: left .16s, background .16s;
    }
    input[type="checkbox"]:checked { background: rgba(94,156,96,.22); border-color: var(--accent-green); }
    input[type="checkbox"]:checked::after { left: 18px; background: var(--accent-green); }
    .folder-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
    .hint { color: var(--text-muted); font-size: 12px; margin-top: 6px; line-height: 1.4; }
    .num-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
    .num-row input { width: 80px; text-align: right; }
    .field-label {
      display: flex;
      align-items: center;
      gap: 6px;
      margin: 12px 0 6px;
    }
    .info {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 15px;
      height: 15px;
      flex: 0 0 15px;
      border: 1px solid var(--border-focus);
      border-radius: 50%;
      color: var(--text-muted);
      font-size: 10px;
      line-height: 1;
      cursor: help;
      text-transform: none;
      letter-spacing: 0;
    }
    .tooltip {
      position: fixed;
      display: none;
      max-width: 300px;
      z-index: 10;
      background: #0A0A0A;
      color: var(--text-secondary);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-input);
      padding: 8px 10px;
      font: 12px/1.4 var(--font-sans);
      box-shadow: 0 8px 24px rgba(0,0,0,.35);
      pointer-events: none;
    }
    .toggle {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 12px 0;
      border-bottom: 1px solid var(--border-subtle);
    }
    .toggle span { color: var(--text-primary); }
    .toggle-title { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
    .toggle-text { min-width: 0; }
    .toggle small { display: block; color: var(--text-muted); margin-top: 3px; }
    .dock { padding: 18px 24px; border-top: 1px solid var(--border-subtle); }
  </style>
</head>
<body>
  <header>
    <div class="logo">VIDEO MERGE <span class="logo-dot"></span></div>
    <div class="dep-badge" id="ffmpegStatus">! FFmpeg Not Checked</div>
  </header>
  <main class="main">
    <section class="left">
      <div class="pane-header">
        <div>
          <h2>Source Files</h2>
          <div class="label-micro summary" id="summary">No folder selected</div>
        </div>
        <div class="toolbar">
          <button id="selectSource">Select Folder</button>
          <button class="btn-icon" id="refresh">↻</button>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <colgroup>
            <col style="width: 34%">
            <col style="width: 15%">
            <col style="width: 15%">
            <col style="width: 12%">
            <col style="width: 10%">
            <col style="width: 14%">
          </colgroup>
          <thead>
            <tr>
              <th>Filename</th><th>Resolution</th><th>Codec</th><th>FPS</th><th>Dur</th><th>Status</th>
            </tr>
          </thead>
          <tbody id="fileRows"></tbody>
        </table>
      </div>
      <div class="console">
        <div class="console-head"><span class="label-micro">Process Console</span><span class="label-micro" id="progressText">0%</span></div>
        <div class="logs" id="logs"></div>
        <div class="bar"><div class="bar-fill" id="bar"></div></div>
      </div>
      <div class="plan">
        <div class="label-micro plan-title" id="planTitle">Optimal Mode Selected</div>
        <div class="plan-text" id="planText">Select a folder to preview the merge plan.</div>
      </div>
    </section>
    <aside class="right">
      <h2 class="config-title">Configuration</h2>
      <div class="config-scroll">
        <h3>Merge Strategy</h3>
        <div class="mode-list">
          <div class="mode-card" data-mode="fast"><div class="mode-head"><span class="mode-title">Fast Merge</span><span class="badge fast">Lossless</span></div><div class="mode-desc">Stream copy only. Skips incompatible groups.</div></div>
          <div class="mode-card active" data-mode="optimal"><div class="mode-head"><span class="mode-title">Optimal Merge</span><span class="badge opt">Smart</span></div><div class="mode-desc">Groups by orientation and transcodes when needed.</div></div>
          <div class="mode-card" data-mode="extreme"><div class="mode-head"><span class="mode-title">Extreme Merge</span><span class="badge extreme">Brute Force</span></div><div class="mode-desc">Normalizes all files into one output.</div></div>
        </div>
        <div class="section">
          <h3>Output Settings</h3>
          <div class="field-label label-micro">Output Filename Prefix <span class="info" data-tip="Maps to --name. Leave empty to use automatic names based on folder, mode, and resolution.">i</span></div>
          <input id="name" value="Merged_Output">
          <div class="field-label label-micro">Output Folder <span class="info" data-tip="Maps to --output-dir. Leave empty to create/use a merged folder under the source directory.">i</span></div>
          <div class="folder-row"><input id="outputDir" placeholder=""><button id="selectOutput">Browse</button></div>
          <div class="hint">Leave empty to use the default merged folder under the source directory.</div>
          <div class="field-label label-micro">Output Format <span class="info" data-tip="Maps to --output-format. Supported containers: mp4, mkv, mov, avi, ts, webm.">i</span></div>
          <select id="format"><option>mp4</option><option>mkv</option><option>mov</option><option>avi</option><option>ts</option><option>webm</option></select>
          <div class="field-label label-micro">Target Video Codec <span class="info" data-tip="Maps to --video-codec. Leave at h264 for broad compatibility.">i</span></div>
          <select id="codec"><option value="">Auto majority</option><option>h264</option><option>hevc</option><option>vp9</option><option>av1</option><option>mpeg4</option></select>
          <div class="field-label label-micro">GPU Acceleration <span class="info" data-tip="Maps to --gpu. auto chooses the native encoder for the OS: Windows NVENC/QSV/AMF, macOS VideoToolbox. Unsupported codecs or missing encoders fall back to CPU.">i</span></div>
          <select id="gpu"><option value="off">off</option><option value="auto">auto</option><option value="nvenc">nvenc</option><option value="qsv">qsv</option><option value="amf">amf</option><option value="videotoolbox">videotoolbox (macOS)</option></select>
          <div class="field-label label-micro">Target Audio Codec <span class="info" data-tip="Maps to --audio-codec. Leave empty to use majority vote, defaulting to AAC when needed.">i</span></div>
          <select id="audioCodec"><option value="">Auto majority</option><option>aac</option><option>mp3</option><option>opus</option><option>vorbis</option><option>pcm_s16le</option></select>
          <div class="num-row">
            <div><div class="field-label label-micro">CRF (Quality) <span class="info" data-tip="Maps to --crf. Lower means better quality and larger files. Common values: 18 high quality, 20 balanced, 23 smaller.">i</span></div><div class="hint">Lower = better</div></div>
            <input id="crf" type="number" min="0" max="51" value="20">
          </div>
          <div class="field-label label-micro">Preset <span class="info" data-tip="Maps to --preset. Slower presets usually produce smaller files at the same CRF but take longer.">i</span></div>
          <select id="preset"><option>ultrafast</option><option>superfast</option><option>veryfast</option><option>faster</option><option>fast</option><option selected>medium</option><option>slow</option><option>slower</option><option>veryslow</option></select>
          <div class="field-label label-micro">FPS Policy <span class="info" data-tip="Maps to --fps-policy. majority uses the most common FPS, max/min choose the highest/lowest FPS in the group.">i</span></div>
          <select id="fpsPolicy"><option>majority</option><option>max</option><option>min</option></select>
          <div class="field-label label-micro">Resolution Policy <span class="info" data-tip="Maps to --resolution-policy. Currently only largest is supported.">i</span></div>
          <select id="resolutionPolicy"><option>largest</option></select>
          <div class="field-label label-micro">Pad Color <span class="info" data-tip="Maps to --pad-color. Used when videos are scaled into a canvas without cropping.">i</span></div>
          <input id="padColor" value="black">
          <div class="field-label label-micro">FFmpeg Path <span class="info" data-tip="Maps to --ffmpeg-path. Optional explicit path to ffmpeg binary.">i</span></div>
          <input id="ffmpegPath" placeholder="Optional">
          <div class="field-label label-micro">FFprobe Path <span class="info" data-tip="Maps to --ffprobe-path. Optional explicit path to ffprobe binary.">i</span></div>
          <input id="ffprobePath" placeholder="Optional">
          <div class="toggle"><div class="toggle-text"><span class="toggle-title">Recursive Scan <span class="info" data-tip="Maps to --recursive / --no-recursive. When enabled, scans subfolders.">i</span></span></div><input id="recursive" type="checkbox" checked></div>
          <div class="toggle"><div class="toggle-text"><span class="toggle-title">Overwrite <span class="info" data-tip="Maps to --overwrite. Replace existing output files instead of appending a numeric suffix.">i</span></span></div><input id="overwrite" type="checkbox"></div>
          <div class="toggle"><div class="toggle-text"><span class="toggle-title">Dry Run <span class="info" data-tip="Maps to --dry-run. Prints commands and plan without running FFmpeg.">i</span></span></div><input id="dryRun" type="checkbox"></div>
          <div class="toggle"><div class="toggle-text"><span class="toggle-title">Keep Temp Files <span class="info" data-tip="Maps to --keep-temp. Keeps preprocessed intermediate files for inspection.">i</span></span></div><input id="keepTemp" type="checkbox"></div>
          <div class="toggle"><div class="toggle-text"><span class="toggle-title">Auto Download Deps <span class="info" data-tip="Maps to --auto-download-deps / --no-auto-download-deps. Attempts to download ffmpeg/ffprobe when missing.">i</span></span></div><input id="autoDownloadDeps" type="checkbox" checked></div>
        </div>
      </div>
      <div class="dock"><button class="btn-primary" id="startMerge">▷ START MERGE</button></div>
    </aside>
  </main>
  <div class="tooltip" id="tooltip"></div>
  <script>
    const state = { mode: "optimal", inputDir: "", files: [], running: false, statusTimer: null };
    const $ = (id) => document.getElementById(id);
    function log(message) {
      const stamp = new Date().toTimeString().slice(0, 8);
      $("logs").textContent += `[${stamp}] ${message}\n`;
      $("logs").scrollTop = $("logs").scrollHeight;
    }
    function progress(value) {
      const clamped = Math.max(0, Math.min(100, value));
      $("progressText").textContent = `${clamped}%`;
      $("bar").style.width = `${clamped}%`;
    }
    function setRunning(running) {
      state.running = running;
      const button = $("startMerge");
      button.textContent = running ? "■ STOP MERGE" : "▷ START MERGE";
      button.classList.toggle("stop", running);
    }
    async function api(path, body) {
      const response = await fetch(path, {
        method: body ? "POST" : "GET",
        headers: body ? {"Content-Type": "application/json"} : undefined,
        body: body ? JSON.stringify(body) : undefined
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || response.statusText);
      return payload;
    }
    async function checkDeps() {
      $("ffmpegStatus").textContent = "… Checking FFmpeg";
      try {
        const payload = await api("/deps");
        $("ffmpegStatus").textContent = payload.ok ? "✓ FFmpeg Installed" : "! FFmpeg Missing";
        log(payload.message);
      } catch (error) {
        $("ffmpegStatus").textContent = "! FFmpeg Missing";
        log(`ERROR: ${error.message}`);
      }
    }
    function renderModes() {
      document.querySelectorAll(".mode-card").forEach(card => {
        card.classList.toggle("active", card.dataset.mode === state.mode);
      });
      $("planTitle").textContent = `${state.mode.toUpperCase()} MODE SELECTED`;
      updatePlan();
    }
    function updatePlan() {
      if (!state.files.length) {
        $("planText").textContent = "Select a folder to preview the merge plan.";
        return;
      }
      const groups = new Set(state.files.map(file => file.orientation));
      if (state.mode === "fast") {
        $("planText").textContent = "Tool will stream-copy compatible groups only. Incompatible files will be skipped.";
      } else if (state.mode === "optimal") {
        $("planText").textContent = `Tool will create up to ${groups.size} output file(s), separated by landscape and portrait display orientation.`;
      } else {
        $("planText").textContent = "Tool will normalize all files to one display canvas and produce one output file.";
      }
    }
    function renderFiles(files) {
      const rows = $("fileRows");
      rows.innerHTML = "";
      const by = {};
      files.forEach(file => {
        const key = file.orientation || "unknown";
        (by[key] ||= []).push(file);
      });
      Object.entries(by).forEach(([orientation, group]) => {
        const w = Math.max(...group.map(file => file.display_width));
        const h = Math.max(...group.map(file => file.display_height));
        rows.insertAdjacentHTML("beforeend", `<tr class="group-row"><td colspan="6">${orientation} group (${w}x${h})</td></tr>`);
        group.forEach(file => {
          const cls = file.fast_ready ? "status-ok" : "status-warn";
          const status = file.fast_ready ? "Ready" : "Needs Transcode";
          rows.insertAdjacentHTML("beforeend", `
            <tr>
              <td title="${file.path}">${file.name}</td>
              <td class="mono">${file.display_width}x${file.display_height}</td>
              <td class="mono">${file.video_codec}/${file.audio_codec || "none"}</td>
              <td class="mono">${file.fps}</td>
              <td class="mono">${file.duration}</td>
              <td class="${cls}">${status}</td>
            </tr>`);
        });
      });
      $("summary").textContent = `${files.length} files detected • ${Object.keys(by).length} groups`.toUpperCase();
      updatePlan();
    }
    async function selectFolder(kind) {
      try {
        const result = await api(`/pick-folder?kind=${kind}`);
        if (!result.path) {
          log("Folder selection was cancelled or is unavailable on this system.");
          return;
        }
        if (kind === "source") {
          state.inputDir = result.path;
          await scan();
        } else {
          $("outputDir").value = result.path;
        }
      } catch (error) { log(`ERROR: ${error.message}`); }
    }
    async function scan() {
      if (!state.inputDir) return selectFolder("source");
      progress(5);
      log(`Scanning ${state.inputDir}`);
      try {
        const payload = await api("/scan", { input_dir: state.inputDir, recursive: $("recursive").checked });
        state.files = payload.files;
        renderFiles(payload.files);
        progress(100);
        log(`${payload.files.length} files analyzed.`);
      } catch (error) {
        progress(0);
        log(`ERROR: ${error.message}`);
      }
    }
    async function merge() {
      if (state.running) {
        await cancelMerge();
        return;
      }
      if (!state.inputDir) {
        await selectFolder("source");
        if (!state.inputDir) return;
      }
      progress(4);
      log(`Starting ${state.mode} merge`);
      try {
        const payload = await api("/merge", {
          input_dir: state.inputDir,
          mode: state.mode,
          name: $("name").value,
          output_dir: $("outputDir").value,
          output_format: $("format").value,
          video_codec: $("codec").value,
          gpu: $("gpu").value,
          audio_codec: $("audioCodec").value,
          crf: Number($("crf").value),
          preset: $("preset").value,
          fps_policy: $("fpsPolicy").value,
          resolution_policy: $("resolutionPolicy").value,
          pad_color: $("padColor").value,
          ffmpeg_path: $("ffmpegPath").value,
          ffprobe_path: $("ffprobePath").value,
          recursive: $("recursive").checked,
          overwrite: $("overwrite").checked,
          dry_run: $("dryRun").checked,
          keep_temp: $("keepTemp").checked,
          auto_download_deps: $("autoDownloadDeps").checked
        });
        setRunning(true);
        log(`Command: ${payload.command.join(" ")}`);
        if (state.statusTimer) clearInterval(state.statusTimer);
        state.statusTimer = setInterval(async () => {
          const status = await api("/status");
          $("logs").textContent = status.logs.join("\n") + (status.logs.length ? "\n" : "");
          $("logs").scrollTop = $("logs").scrollHeight;
          progress(status.progress);
          setRunning(status.running);
          if (!status.running) {
            clearInterval(state.statusTimer);
            state.statusTimer = null;
          }
        }, 500);
      } catch (error) {
        progress(0);
        setRunning(false);
        log(`ERROR: ${error.message}`);
      }
    }
    async function cancelMerge() {
      try {
        log("Stopping current merge task...");
        await api("/cancel", {});
      } catch (error) {
        log(`ERROR: ${error.message}`);
      }
    }
    document.querySelectorAll(".mode-card").forEach(card => card.addEventListener("click", () => {
      state.mode = card.dataset.mode;
      renderModes();
    }));
    $("selectSource").addEventListener("click", () => selectFolder("source"));
    $("selectOutput").addEventListener("click", () => selectFolder("output"));
    $("refresh").addEventListener("click", scan);
    $("startMerge").addEventListener("click", merge);
    document.querySelectorAll(".info").forEach(icon => {
      icon.addEventListener("mouseenter", () => {
        const tip = $("tooltip");
        tip.textContent = icon.dataset.tip || "";
        tip.style.display = "block";
        const rect = icon.getBoundingClientRect();
        const width = Math.min(300, Math.max(220, tip.offsetWidth || 260));
        let left = rect.right + 10;
        if (left + width > window.innerWidth - 12) left = rect.left - width - 10;
        if (left < 12) left = 12;
        let top = rect.top - 8;
        const height = tip.offsetHeight || 48;
        if (top + height > window.innerHeight - 12) top = window.innerHeight - height - 12;
        if (top < 12) top = 12;
        tip.style.left = `${left}px`;
        tip.style.top = `${top}px`;
      });
      icon.addEventListener("mouseleave", () => {
        $("tooltip").style.display = "none";
      });
    });
    renderModes();
    log("Select a source folder to begin.");
    checkDeps();
  </script>
</body>
</html>
"""


class GuiState:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.progress = 0
        self.running = False
        self.cancel_requested = False
        self.process: subprocess.Popen[str] | None = None
        self.lock = threading.Lock()

    def log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        with self.lock:
            self.logs.append(f"[{stamp}] {message}")
            self.logs = self.logs[-400:]

    def set_progress(self, value: int) -> None:
        with self.lock:
            self.progress = max(0, min(100, value))

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            return {"logs": list(self.logs), "progress": self.progress, "running": self.running}

    def begin_run(self) -> bool:
        with self.lock:
            if self.running:
                return False
            self.logs.clear()
            self.progress = 4
            self.running = True
            self.cancel_requested = False
            self.process = None
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


class QueueLogHandler(logging.Handler):
    def __init__(self, state: GuiState) -> None:
        super().__init__()
        self.state = state

    def emit(self, record: logging.LogRecord) -> None:
        self.state.log(self.format(record))


def launch_gui(host: str = "127.0.0.1", port: int | None = None) -> None:
    port = port or _free_port()
    state = GuiState()
    server = ThreadingHTTPServer((host, port), _make_handler(state))
    url = f"http://{host}:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    webbrowser.open(url)
    print(f"VideoMergingTool GUI running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        while thread.is_alive():
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


def _make_handler(state: GuiState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(HTML)
                return
            if parsed.path == "/pick-folder":
                kind = parse_qs(parsed.query).get("kind", ["source"])[0]
                self._send_json({"path": _pick_folder(kind)})
                return
            if parsed.path == "/deps":
                self._deps()
                return
            if parsed.path == "/status":
                self._send_json(state.snapshot())
                return
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            payload = self._read_json()
            if parsed.path == "/scan":
                self._scan(payload)
                return
            if parsed.path == "/merge":
                self._merge(payload)
                return
            if parsed.path == "/cancel":
                self._cancel()
                return
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

        def _deps(self) -> None:
            try:
                logger = _gui_logger(state)
                tools = resolve_tools(logger, True, Path.cwd() / ".tools" / "ffmpeg")
                encoders = detect_ffmpeg_encoders(tools)
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

        def _scan(self, payload: dict[str, object]) -> None:
            try:
                logger = _gui_logger(state)
                state.set_progress(8)
                tools = resolve_tools(logger, True, Path.cwd() / ".tools" / "ffmpeg")
                input_dir = Path(str(payload["input_dir"]))
                paths = scan_video_files(input_dir, bool(payload.get("recursive", True)))
                state.set_progress(25)
                media_files, failures = probe_files(paths, tools, logger)
                if failures:
                    state.log(f"{len(failures)} file(s) could not be analyzed.")
                files = _serialize_files(media_files)
                state.set_progress(100)
                self._send_json({"files": files})
            except Exception as exc:
                state.set_progress(0)
                self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def _merge(self, payload: dict[str, object]) -> None:
            if not state.begin_run():
                self._send_json({"error": "A merge is already running."}, HTTPStatus.CONFLICT)
                return
            command = _build_merge_command(payload)
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

        def _send_html(self, content: str) -> None:
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


def _serialize_files(files: list[VideoFile]) -> list[dict[str, object]]:
    fast_groups = group_fast(files)
    output = []
    for file in files:
        fast_ready = any(file in members and len(members) > 1 for members in fast_groups.values())
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
                "orientation": file.orientation.value,
                "fast_ready": fast_ready,
            }
        )
    return output


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


def _build_merge_command(payload: dict[str, object]) -> list[str]:
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "merge", str(payload["input_dir"])]
    else:
        main_py = Path(__file__).resolve().parents[1] / "main.py"
        cmd = [sys.executable, str(main_py), "merge", str(payload["input_dir"])]
    cmd.extend(["--mode", str(payload.get("mode") or MergeMode.optimal.value)])
    cmd.extend(["--output-format", str(payload.get("output_format") or "mp4")])
    if payload.get("name"):
        cmd.extend(["--name", str(payload["name"])])
    if payload.get("output_dir"):
        cmd.extend(["--output-dir", str(payload["output_dir"])])
    if payload.get("video_codec"):
        cmd.extend(["--video-codec", str(payload["video_codec"])])
    if payload.get("gpu"):
        cmd.extend(["--gpu", str(payload["gpu"])])
    if payload.get("audio_codec"):
        cmd.extend(["--audio-codec", str(payload["audio_codec"])])
    cmd.extend(["--crf", str(payload.get("crf") or 20)])
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


def _run_merge(command: list[str], state: GuiState) -> None:
    state.log("Command: " + " ".join(command))
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
            state.log(stripped)
            lowered = stripped.lower()
            if "media:" in lowered:
                state.set_progress(18)
            elif "preprocess" in lowered:
                state.set_progress(45)
            elif "merge order" in lowered:
                state.set_progress(72)
            elif "output written" in lowered:
                state.set_progress(92)
        code = process.wait()
        was_cancelled = state.finish_process()
        if was_cancelled:
            state.log("Merge stopped by user.")
        elif code == 0:
            state.set_progress(100)
            state.log("Merge completed.")
        else:
            state.log(f"ERROR: Merge failed with exit code {code}.")
    except Exception as exc:
        state.log(f"ERROR: {exc}")
    finally:
        state.finish_process()


def _terminate_process(process: subprocess.Popen[str]) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
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
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
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


def _pick_folder(kind: str) -> str:
    title = "Select output folder" if kind == "output" else "Select source video folder"
    if platform.system() == "Darwin":
        return _pick_folder_macos(title)
    return _pick_folder_tk(title)


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
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        return ""
    return ""


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
