from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .env_check import default_tools_dir, resolve_tools
from .grouping import group_fast, split_by_orientation
from .gpu import detect_ffmpeg_encoders
from .models import MergeMode, Orientation, VideoFile
from .probe import probe_files
from .scanner import scan_video_files
from .utils import subprocess_window_kwargs
from . import __version__


CONFIG_FIELD_IDS = [
    "outputDir",
    "tempDir",
    "format",
    "sortBy",
    "codec",
    "gpu",
    "audioCodec",
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
]


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
    * {
      user-select: text;
      -webkit-user-select: text;
    }
    body {
      background: var(--bg-body);
      color: var(--text-primary);
      font-family: var(--font-sans);
      font-size: 14px;
      min-height: 100vh;
      min-width: 900px;
      overflow: hidden;
      -webkit-font-smoothing: antialiased;
    }
    button, select, input[type="checkbox"], .mode-card, .info {
      user-select: none;
      -webkit-user-select: none;
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
      min-height: 28px;
    }
    button.dep-badge:hover { background: var(--bg-panel-hover); border-color: var(--border-focus); }
    .main {
      display: grid;
      grid-template-columns: minmax(520px, 1fr) minmax(340px, clamp(360px, 32vw, 480px));
      height: calc(100vh - 56px);
      min-height: 560px;
    }
    .left {
      border-right: 1px solid var(--border-subtle);
      display: grid;
      grid-template-rows: auto minmax(180px, 1fr) minmax(160px, 32vh) minmax(88px, auto);
      min-width: 0;
      overflow: hidden;
    }
    .right {
      background: var(--bg-panel);
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
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
    .summary { margin-top: 8px; }
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
      margin: clamp(12px, 2vw, 24px);
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
      margin: 0 clamp(12px, 2vw, 24px) 12px;
      background: #0A0A0A;
      border: 1px solid #1A1A1A;
      border-radius: var(--radius-panel);
      padding: 14px;
      min-height: 0;
      display: grid;
      grid-template-rows: 18px minmax(0, 1fr) 4px;
      gap: 8px;
      height: 100%;
      min-height: 150px;
      max-height: none;
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
      margin: 0 clamp(12px, 2vw, 24px) 18px;
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
    .header-actions { display: flex; align-items: center; gap: 10px; }
    .language-select {
      width: auto;
      min-width: 118px;
      padding: 6px 28px 6px 10px;
      font-size: 12px;
      font-weight: 700;
    }
    @media (max-width: 1040px) {
      body { min-width: 720px; overflow: auto; }
      .main { grid-template-columns: 1fr; height: auto; min-height: calc(100vh - 56px); }
      .left { border-right: 0; border-bottom: 1px solid var(--border-subtle); min-height: 620px; }
      .right { min-height: 560px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="logo">VIDEO MERGE <span class="logo-dot"></span></div>
    <div class="header-actions">
      <select class="language-select" id="languageSelect" title="Switch language">
        <option value="en">English</option>
        <option value="zh">简体中文</option>
      </select>
      <button class="dep-badge" id="ffmpegStatus" type="button"></button>
    </div>
  </header>
  <main class="main">
    <section class="left">
      <div class="pane-header">
        <div>
          <h2 data-i18n="sourceFiles">Source Files</h2>
          <div class="label-micro summary" id="summary" data-i18n="noFolderSelected">No folder selected</div>
        </div>
        <div class="toolbar">
          <button id="selectSource" data-i18n="selectFolder">Select Folder</button>
          <button class="btn-icon" id="refresh" title="Refresh">↻</button>
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
              <th data-i18n="filename">Filename</th><th data-i18n="resolution">Resolution</th><th data-i18n="codec">Codec</th><th>FPS</th><th data-i18n="duration">Dur</th><th data-i18n="status">Status</th>
            </tr>
          </thead>
          <tbody id="fileRows"></tbody>
        </table>
      </div>
      <div class="console">
        <div class="console-head"><span class="label-micro" data-i18n="processConsole">Process Console</span><span class="label-micro" id="progressText">0%</span></div>
        <div class="logs" id="logs"></div>
        <div class="bar"><div class="bar-fill" id="bar"></div></div>
      </div>
      <div class="plan">
        <div class="label-micro plan-title" id="planTitle"></div>
        <div class="plan-text" id="planText"></div>
      </div>
    </section>
    <aside class="right">
      <h2 class="config-title" data-i18n="configuration">Configuration</h2>
      <div class="config-scroll">
        <h3 data-i18n="mergeStrategy">Merge Strategy</h3>
        <div class="mode-list">
          <div class="mode-card" data-mode="fast"><div class="mode-head"><span class="mode-title" data-i18n="fastMerge">Fast Merge</span><span class="badge fast" data-i18n="lossless">Lossless</span></div><div class="mode-desc" data-i18n="fastDesc">Stream copy only. Skips incompatible groups.</div></div>
          <div class="mode-card active" data-mode="optimal"><div class="mode-head"><span class="mode-title" data-i18n="optimalMerge">Optimal Merge</span><span class="badge opt" data-i18n="smart">Smart</span></div><div class="mode-desc" data-i18n="optimalDesc">Groups by orientation and transcodes when needed.</div></div>
          <div class="mode-card" data-mode="extreme"><div class="mode-head"><span class="mode-title" data-i18n="extremeMerge">Extreme Merge</span><span class="badge extreme" data-i18n="bruteForce">Brute Force</span></div><div class="mode-desc" data-i18n="extremeDesc">Normalizes all files into one output.</div></div>
        </div>
        <div class="section">
          <h3 data-i18n="outputSettings">Output Settings</h3>
          <div class="field-label label-micro"><span data-i18n="outputFilenamePrefix">Output Filename Prefix</span> <span class="info" data-tip-i18n="tipName">i</span></div>
          <input id="name" value="Merged_Output">
          <div class="field-label label-micro"><span data-i18n="outputFolder">Output Folder</span> <span class="info" data-tip-i18n="tipOutputDir">i</span></div>
          <div class="folder-row"><input id="outputDir" placeholder=""><button id="selectOutput" data-i18n="browse">Browse</button></div>
          <div class="hint" data-i18n="outputDirHint">Leave empty to use the default merged folder under the source directory.</div>
          <div class="field-label label-micro"><span data-i18n="tempFolder">Temp Folder</span> <span class="info" data-tip-i18n="tipTempDir">i</span></div>
          <div class="folder-row"><input id="tempDir" placeholder=""><button id="selectTemp" data-i18n="browse">Browse</button></div>
          <div class="hint" data-i18n="tempDirHint">Leave empty to use the system default temp directory.</div>
          <div class="field-label label-micro"><span data-i18n="outputFormat">Output Format</span> <span class="info" data-tip-i18n="tipOutputFormat">i</span></div>
          <select id="format"><option>mp4</option><option>mkv</option><option>mov</option><option>avi</option><option>ts</option><option>webm</option></select>
          <div class="field-label label-micro"><span data-i18n="mergeSortOrder">Merge Sort Order</span> <span class="info" data-tip-i18n="tipSortOrder">i</span></div>
          <select id="sortBy">
            <option value="name-natural-asc" data-i18n="sortNameNaturalAsc">Filename natural (A-Z)</option>
            <option value="name-natural-desc" data-i18n="sortNameNaturalDesc">Filename natural (Z-A)</option>
            <option value="name-asc" data-i18n="sortNameAsc">Filename text (A-Z)</option>
            <option value="name-desc" data-i18n="sortNameDesc">Filename text (Z-A)</option>
            <option value="modified-asc" data-i18n="sortModifiedAsc">Modified time (oldest first)</option>
            <option value="modified-desc" data-i18n="sortModifiedDesc">Modified time (newest first)</option>
            <option value="size-asc" data-i18n="sortSizeAsc">File size (smallest first)</option>
            <option value="size-desc" data-i18n="sortSizeDesc">File size (largest first)</option>
          </select>
          <div class="field-label label-micro"><span data-i18n="targetVideoCodec">Target Video Codec</span> <span class="info" data-tip-i18n="tipVideoCodec">i</span></div>
          <select id="codec"><option value="">Auto majority</option><option>h264</option><option>hevc</option><option>vp9</option><option>av1</option><option>mpeg4</option></select>
          <div class="field-label label-micro"><span data-i18n="gpuAcceleration">GPU Acceleration</span> <span class="info" data-tip-i18n="tipGpu">i</span></div>
          <select id="gpu"><option value="off">off</option><option value="auto">auto</option><option value="nvenc">nvenc</option><option value="qsv">qsv</option><option value="amf">amf</option><option value="videotoolbox">videotoolbox (macOS)</option></select>
          <div class="field-label label-micro"><span data-i18n="targetAudioCodec">Target Audio Codec</span> <span class="info" data-tip-i18n="tipAudioCodec">i</span></div>
          <select id="audioCodec"><option value="">Auto majority</option><option>aac</option><option>mp3</option><option>opus</option><option>vorbis</option><option>pcm_s16le</option></select>
          <div class="num-row">
            <div><div class="field-label label-micro"><span data-i18n="crfQuality">CRF (Quality)</span> <span class="info" data-tip-i18n="tipCrf">i</span></div><div class="hint" data-i18n="lowerBetter">Lower = better</div></div>
            <input id="crf" type="number" min="0" max="51" value="20">
          </div>
          <div class="field-label label-micro"><span data-i18n="preset">Preset</span> <span class="info" data-tip-i18n="tipPreset">i</span></div>
          <select id="preset"><option>ultrafast</option><option>superfast</option><option>veryfast</option><option>faster</option><option>fast</option><option selected>medium</option><option>slow</option><option>slower</option><option>veryslow</option></select>
          <div class="field-label label-micro"><span data-i18n="fpsPolicy">FPS Policy</span> <span class="info" data-tip-i18n="tipFpsPolicy">i</span></div>
          <select id="fpsPolicy"><option>majority</option><option>max</option><option>min</option></select>
          <div class="field-label label-micro"><span data-i18n="resolutionPolicy">Resolution Policy</span> <span class="info" data-tip-i18n="tipResolutionPolicy">i</span></div>
          <select id="resolutionPolicy"><option>largest</option></select>
          <div class="field-label label-micro"><span data-i18n="padColor">Pad Color</span> <span class="info" data-tip-i18n="tipPadColor">i</span></div>
          <input id="padColor" value="black">
          <div class="field-label label-micro"><span data-i18n="ffmpegPath">FFmpeg Path</span> <span class="info" data-tip-i18n="tipFfmpegPath">i</span></div>
          <input id="ffmpegPath" placeholder="Optional">
          <div class="field-label label-micro"><span data-i18n="ffprobePath">FFprobe Path</span> <span class="info" data-tip-i18n="tipFfprobePath">i</span></div>
          <input id="ffprobePath" placeholder="Optional">
          <div class="toggle"><div class="toggle-text"><span class="toggle-title"><span data-i18n="recursiveScan">Recursive Scan</span> <span class="info" data-tip-i18n="tipRecursive">i</span></span></div><input id="recursive" type="checkbox" checked></div>
          <div class="toggle"><div class="toggle-text"><span class="toggle-title"><span data-i18n="overwrite">Overwrite</span> <span class="info" data-tip-i18n="tipOverwrite">i</span></span></div><input id="overwrite" type="checkbox"></div>
          <div class="toggle"><div class="toggle-text"><span class="toggle-title"><span data-i18n="dryRun">Dry Run</span> <span class="info" data-tip-i18n="tipDryRun">i</span></span></div><input id="dryRun" type="checkbox"></div>
          <div class="toggle"><div class="toggle-text"><span class="toggle-title"><span data-i18n="keepTempFiles">Keep Temp Files</span> <span class="info" data-tip-i18n="tipKeepTemp">i</span></span></div><input id="keepTemp" type="checkbox"></div>
          <div class="toggle"><div class="toggle-text"><span class="toggle-title"><span data-i18n="autoDownloadDeps">Auto Download Deps</span> <span class="info" data-tip-i18n="tipAutoDownload">i</span></span></div><input id="autoDownloadDeps" type="checkbox" checked></div>
        </div>
      </div>
      <div class="dock"><button class="btn-primary" id="startMerge"></button></div>
    </aside>
  </main>
  <div class="tooltip" id="tooltip"></div>
  <script>
    const messages = {
      en: {
        ffmpegNotChecked: "! FFmpeg Not Checked", ffmpegChecking: "... Checking FFmpeg", ffmpegInstalled: "✓ FFmpeg Installed", ffmpegMissing: "! FFmpeg Missing", refreshFfmpeg: "Refresh FFmpeg check",
        sourceFiles: "Source Files", noFolderSelected: "No folder selected", selectFolder: "Select Folder", filename: "Filename", resolution: "Resolution", codec: "Codec", duration: "Dur", status: "Status",
        processConsole: "Process Console", configuration: "Configuration", mergeStrategy: "Merge Strategy", outputSettings: "Output Settings", browse: "Browse",
        fastMerge: "Fast Merge", optimalMerge: "Optimal Merge", extremeMerge: "Extreme Merge", lossless: "Lossless", smart: "Smart", bruteForce: "Brute Force",
        fastDesc: "Stream copy only. Skips incompatible groups.", optimalDesc: "Groups by orientation and transcodes when needed.", extremeDesc: "Normalizes all files into one output.",
        outputFilenamePrefix: "Output Filename Prefix", outputFolder: "Output Folder", tempFolder: "Temp Folder", outputFormat: "Output Format", mergeSortOrder: "Merge Sort Order", targetVideoCodec: "Target Video Codec",
        gpuAcceleration: "GPU Acceleration", targetAudioCodec: "Target Audio Codec", crfQuality: "CRF (Quality)", lowerBetter: "Lower = better", preset: "Preset",
        fpsPolicy: "FPS Policy", resolutionPolicy: "Resolution Policy", padColor: "Pad Color", ffmpegPath: "FFmpeg Path", ffprobePath: "FFprobe Path",
        recursiveScan: "Recursive Scan", overwrite: "Overwrite", dryRun: "Dry Run", keepTempFiles: "Keep Temp Files", autoDownloadDeps: "Auto Download Deps",
        outputDirHint: "Leave empty to use the default merged folder under the source directory.", tempDirHint: "Leave empty to use the system default temp directory.",
        sortNameNaturalAsc: "Filename natural (A-Z)", sortNameNaturalDesc: "Filename natural (Z-A)", sortNameAsc: "Filename text (A-Z)", sortNameDesc: "Filename text (Z-A)",
        sortModifiedAsc: "Modified time (oldest first)", sortModifiedDesc: "Modified time (newest first)", sortSizeAsc: "File size (smallest first)", sortSizeDesc: "File size (largest first)",
        startMerge: "▷ START MERGE", stopMerge: "■ STOP MERGE", switchLanguage: "Switch language",
        modeSelected: "{mode} MODE SELECTED", selectFolderPlan: "Select a folder to preview the merge plan.",
        fastPlan: "Tool will stream-copy compatible groups only. Incompatible files will be skipped.",
        optimalPlan: "Tool will create up to {count} output file(s), separated by landscape and portrait display orientation.",
        extremePlan: "Tool will normalize all files to one display canvas and produce one output file.",
        groupLabel: "{orientation} group ({size})", ready: "Ready", needsTranscode: "Needs Transcode", summary: "{files} files detected - {groups} groups",
        folderCancelled: "Folder selection was cancelled or is unavailable on this system.", scanning: "Scanning {path}", filesAnalyzed: "{count} files analyzed.",
        startingMerge: "Starting {mode} merge", stoppingMerge: "Stopping current merge task...", selectBegin: "Select a source folder to begin.",
        tipName: "Maps to --name. Leave empty to use automatic names based on folder, mode, and resolution.",
        tipOutputDir: "Maps to --output-dir. Leave empty to create/use a merged folder under the source directory.",
        tipTempDir: "Maps to --temp-dir. Leave empty to use the system default temp directory.",
        tipOutputFormat: "Maps to --output-format. Supported containers: mp4, mkv, mov, avi, ts, webm.",
        tipSortOrder: "Maps to --sort-by. Controls the scan, preview, preprocessing, and final merge order.",
        tipVideoCodec: "Maps to --video-codec. Leave empty for automatic codec selection.",
        tipGpu: "Maps to --gpu. auto chooses the native encoder when available and falls back to CPU when needed.",
        tipAudioCodec: "Maps to --audio-codec. Leave empty to use majority vote, defaulting to AAC when needed.",
        tipCrf: "Maps to --crf. Lower means better quality and larger files.",
        tipPreset: "Maps to --preset. Slower presets usually produce smaller files at the same CRF but take longer.",
        tipFpsPolicy: "Maps to --fps-policy. majority uses the most common FPS; max/min choose the highest/lowest FPS.",
        tipResolutionPolicy: "Maps to --resolution-policy. Currently only largest is supported.",
        tipPadColor: "Maps to --pad-color. Used when videos are scaled into a canvas without cropping.",
        tipFfmpegPath: "Maps to --ffmpeg-path. Optional explicit path to ffmpeg binary.",
        tipFfprobePath: "Maps to --ffprobe-path. Optional explicit path to ffprobe binary.",
        tipRecursive: "Maps to --recursive / --no-recursive. When enabled, scans subfolders.",
        tipOverwrite: "Maps to --overwrite. Replace existing output files instead of appending a numeric suffix.",
        tipDryRun: "Maps to --dry-run. Prints commands and plan without running FFmpeg.",
        tipKeepTemp: "Maps to --keep-temp. Keeps preprocessed intermediate files for inspection.",
        tipAutoDownload: "Maps to --auto-download-deps / --no-auto-download-deps. Attempts to download ffmpeg/ffprobe when missing."
      },
      zh: {
        ffmpegNotChecked: "! FFmpeg 未检查", ffmpegChecking: "... 正在检查 FFmpeg", ffmpegInstalled: "✓ FFmpeg 已安装", ffmpegMissing: "! FFmpeg 缺失", refreshFfmpeg: "重新检查 FFmpeg",
        sourceFiles: "源文件", noFolderSelected: "未选择文件夹", selectFolder: "选择文件夹", filename: "文件名", resolution: "分辨率", codec: "编码", duration: "时长", status: "状态",
        processConsole: "处理控制台", configuration: "配置", mergeStrategy: "合并策略", outputSettings: "输出设置", browse: "浏览",
        fastMerge: "快速合并", optimalMerge: "智能合并", extremeMerge: "强制合并", lossless: "无损", smart: "智能", bruteForce: "强制",
        fastDesc: "仅使用流复制，跳过不兼容分组。", optimalDesc: "按横竖屏分组，必要时转码。", extremeDesc: "统一所有文件到一个输出。",
        outputFilenamePrefix: "输出文件名前缀", outputFolder: "输出目录", tempFolder: "临时目录", outputFormat: "输出格式", mergeSortOrder: "合并排序方式", targetVideoCodec: "目标视频编码",
        gpuAcceleration: "GPU 加速", targetAudioCodec: "目标音频编码", crfQuality: "CRF（质量）", lowerBetter: "越低质量越高", preset: "编码预设",
        fpsPolicy: "帧率策略", resolutionPolicy: "分辨率策略", padColor: "填充颜色", ffmpegPath: "FFmpeg 路径", ffprobePath: "FFprobe 路径",
        recursiveScan: "递归扫描", overwrite: "覆盖输出", dryRun: "试运行", keepTempFiles: "保留临时文件", autoDownloadDeps: "自动下载依赖",
        outputDirHint: "留空时默认使用源目录下的 merged 文件夹。", tempDirHint: "留空时使用系统默认临时目录。",
        sortNameNaturalAsc: "文件名自然升序", sortNameNaturalDesc: "文件名自然降序", sortNameAsc: "文件名文本升序", sortNameDesc: "文件名文本降序",
        sortModifiedAsc: "修改时间从旧到新", sortModifiedDesc: "修改时间从新到旧", sortSizeAsc: "文件大小从小到大", sortSizeDesc: "文件大小从大到小",
        startMerge: "▷ 开始合并", stopMerge: "■ 停止合并", switchLanguage: "切换语言",
        modeSelected: "已选择 {mode} 模式", selectFolderPlan: "选择文件夹后预览合并计划。",
        fastPlan: "工具将仅对兼容分组合并，跳过不兼容文件。",
        optimalPlan: "工具将按横竖屏生成最多 {count} 个输出文件。",
        extremePlan: "工具将把所有文件统一到一个画布并生成一个输出文件。",
        groupLabel: "{orientation} 分组（{size}）", ready: "就绪", needsTranscode: "需要转码", summary: "检测到 {files} 个文件 - {groups} 个分组",
        folderCancelled: "文件夹选择已取消，或当前系统不可用。", scanning: "正在扫描 {path}", filesAnalyzed: "已分析 {count} 个文件。",
        startingMerge: "开始 {mode} 合并", stoppingMerge: "正在停止当前合并任务...", selectBegin: "请选择源文件夹开始。",
        tipName: "对应 --name。留空时根据文件夹、模式和分辨率自动命名。",
        tipOutputDir: "对应 --output-dir。留空时在源目录下创建或使用 merged 文件夹。",
        tipTempDir: "对应 --temp-dir。留空时使用系统默认临时目录。",
        tipOutputFormat: "对应 --output-format。支持 mp4、mkv、mov、avi、ts、webm。",
        tipSortOrder: "对应 --sort-by。控制扫描、预览、预处理和最终合并顺序。",
        tipVideoCodec: "对应 --video-codec。留空时自动选择编码。",
        tipGpu: "对应 --gpu。auto 会优先选择可用的系统原生编码器，必要时回退 CPU。",
        tipAudioCodec: "对应 --audio-codec。留空时按多数文件选择，需要时默认 AAC。",
        tipCrf: "对应 --crf。数值越低质量越高，文件越大。",
        tipPreset: "对应 --preset。更慢的预设通常体积更小，但耗时更长。",
        tipFpsPolicy: "对应 --fps-policy。majority 使用最常见帧率，max/min 选择最高/最低帧率。",
        tipResolutionPolicy: "对应 --resolution-policy。目前仅支持 largest。",
        tipPadColor: "对应 --pad-color。视频缩放到画布且不裁剪时使用。",
        tipFfmpegPath: "对应 --ffmpeg-path。可选的 ffmpeg 二进制路径。",
        tipFfprobePath: "对应 --ffprobe-path。可选的 ffprobe 二进制路径。",
        tipRecursive: "对应 --recursive / --no-recursive。启用后扫描子文件夹。",
        tipOverwrite: "对应 --overwrite。替换已有输出，不追加数字后缀。",
        tipDryRun: "对应 --dry-run。只打印命令和计划，不运行 FFmpeg。",
        tipKeepTemp: "对应 --keep-temp。保留预处理临时文件用于检查。",
        tipAutoDownload: "对应 --auto-download-deps / --no-auto-download-deps。缺少 ffmpeg/ffprobe 时尝试自动下载。"
      }
    };
    const state = {
      mode: "optimal",
      inputDir: "",
      files: [],
      running: false,
      statusTimer: null,
      lang: "en",
      deps: { status: "notChecked", message: "" },
      defaults: {}
    };
    const pathFields = ["outputDir", "tempDir", "ffmpegPath", "ffprobePath"];
    const $ = (id) => document.getElementById(id);
    const t = (key, values = {}) => {
      let text = (messages[state.lang] && messages[state.lang][key]) || messages.en[key] || key;
      Object.entries(values).forEach(([name, value]) => { text = text.replace(`{${name}}`, value); });
      return text;
    };
    function applyLanguage() {
      document.documentElement.lang = state.lang === "zh" ? "zh-Hans" : "en";
      document.querySelectorAll("[data-i18n]").forEach(node => { node.textContent = t(node.dataset.i18n); });
      document.querySelectorAll("[data-tip-i18n]").forEach(node => { node.dataset.tip = t(node.dataset.tipI18n); });
      $("languageSelect").value = state.lang;
      $("languageSelect").title = t("switchLanguage");
      renderDepStatus();
      setRunning(state.running);
      renderModes();
      if (!state.files.length && !state.inputDir) $("summary").textContent = t("noFolderSelected");
    }
    function renderDepStatus() {
      const keys = {
        notChecked: "ffmpegNotChecked",
        checking: "ffmpegChecking",
        installed: "ffmpegInstalled",
        missing: "ffmpegMissing"
      };
      const badge = $("ffmpegStatus");
      badge.textContent = t(keys[state.deps.status] || "ffmpegNotChecked");
      badge.title = state.deps.message ? `${t("refreshFfmpeg")}: ${state.deps.message}` : t("refreshFfmpeg");
      badge.disabled = state.deps.status === "checking";
    }
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
      button.textContent = running ? t("stopMerge") : t("startMerge");
      button.classList.toggle("stop", running);
    }
    async function api(path, body) {
      const response = await fetch(path, {
        method: body ? "POST" : "GET",
        headers: body ? {"Content-Type": "application/json"} : undefined,
        body: body ? JSON.stringify(body) : undefined
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || payload.message || response.statusText);
      return payload;
    }
    function readConfig() {
      const values = { lang: state.lang, mode: state.mode };
      const ids = ["format", "sortBy", "codec", "gpu", "audioCodec", "crf", "preset", "fpsPolicy", "resolutionPolicy", "padColor", "outputDir", "tempDir", "ffmpegPath", "ffprobePath", "recursive", "overwrite", "dryRun", "keepTemp", "autoDownloadDeps"];
      ids.forEach(id => {
        const node = $(id);
        if (pathFields.includes(id) && node.dataset.custom !== "true") return;
        values[id] = node.type === "checkbox" ? node.checked : node.value;
      });
      return values;
    }
    function applyConfig(config) {
      if (!config || typeof config !== "object") return;
      if (config.lang && messages[config.lang]) state.lang = config.lang;
      if (config.mode) state.mode = config.mode;
      Object.entries(config).forEach(([id, value]) => {
        const node = $(id);
        if (!node) return;
        if (pathFields.includes(id)) node.dataset.custom = value ? "true" : "false";
        if (node.type === "checkbox") node.checked = Boolean(value);
        else node.value = value;
      });
    }
    async function loadConfig() {
      try { applyConfig(await api("/config")); } catch (error) { log(`ERROR: ${error.message}`); }
    }
    let saveTimer = null;
    function scheduleSaveConfig() {
      if (saveTimer) clearTimeout(saveTimer);
      saveTimer = setTimeout(async () => {
        try { await api("/config", readConfig()); } catch (error) { log(`ERROR: ${error.message}`); }
      }, 250);
    }
    function applyDefaultPaths() {
      const mapping = {
        outputDir: "output_dir",
        tempDir: "temp_dir",
        ffmpegPath: "ffmpeg",
        ffprobePath: "ffprobe"
      };
      pathFields.forEach(id => {
        const node = $(id);
        if (node.dataset.custom === "true") return;
        node.value = state.defaults[mapping[id]] || "";
      });
    }
    async function refreshDefaultPaths() {
      try {
        state.defaults = await api("/defaults", { input_dir: state.inputDir });
        applyDefaultPaths();
      } catch (error) {
        log(`ERROR: ${error.message}`);
      }
    }
    function configPathValue(id) {
      const node = $(id);
      return node.dataset.custom === "true" ? node.value : "";
    }
    async function checkDeps() {
      state.deps = { status: "checking", message: "" };
      renderDepStatus();
      try {
        const payload = await api("/deps");
        state.defaults.ffmpeg = payload.ffmpeg || state.defaults.ffmpeg || "";
        state.defaults.ffprobe = payload.ffprobe || state.defaults.ffprobe || "";
        applyDefaultPaths();
        state.deps = {
          status: payload.ok ? "installed" : "missing",
          message: payload.message || ""
        };
        renderDepStatus();
        log(payload.message);
      } catch (error) {
        state.deps = { status: "missing", message: error.message };
        renderDepStatus();
        log(`ERROR: ${error.message}`);
      }
    }
    function renderModes() {
      document.querySelectorAll(".mode-card").forEach(card => {
        card.classList.toggle("active", card.dataset.mode === state.mode);
      });
      $("planTitle").textContent = t("modeSelected", { mode: state.mode.toUpperCase() });
      updatePlan();
    }
    function updatePlan() {
      if (!state.files.length) {
        $("planText").textContent = t("selectFolderPlan");
        return;
      }
      const groups = new Set(state.files.map(file => file.orientation));
      if (state.mode === "fast") {
        $("planText").textContent = t("fastPlan");
      } else if (state.mode === "optimal") {
        $("planText").textContent = t("optimalPlan", { count: groups.size });
      } else {
        $("planText").textContent = t("extremePlan");
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
        rows.insertAdjacentHTML("beforeend", `<tr class="group-row"><td colspan="6">${t("groupLabel", { orientation, size: `${w}x${h}` })}</td></tr>`);
        group.forEach(file => {
          const cls = file.fast_ready ? "status-ok" : "status-warn";
          const status = file.fast_ready ? t("ready") : t("needsTranscode");
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
      $("summary").textContent = t("summary", { files: files.length, groups: Object.keys(by).length }).toUpperCase();
      updatePlan();
    }
    async function selectFolder(kind) {
      try {
        const result = await api(`/pick-folder?kind=${kind}`);
        if (!result.path) {
          log(t("folderCancelled"));
          return;
        }
        if (kind === "source") {
          state.inputDir = result.path;
          await refreshDefaultPaths();
          await scan();
        } else {
          const id = kind === "temp" ? "tempDir" : "outputDir";
          $(id).value = result.path;
          $(id).dataset.custom = "true";
          scheduleSaveConfig();
        }
      } catch (error) { log(`ERROR: ${error.message}`); }
    }
    async function scan() {
      if (!state.inputDir) return selectFolder("source");
      progress(5);
      log(t("scanning", { path: state.inputDir }));
      try {
        const payload = await api("/scan", { input_dir: state.inputDir, recursive: $("recursive").checked, sort_by: $("sortBy").value });
        state.files = payload.files;
        renderFiles(payload.files);
        progress(100);
        log(t("filesAnalyzed", { count: payload.files.length }));
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
      log(t("startingMerge", { mode: state.mode }));
      try {
        const payload = await api("/merge", {
          input_dir: state.inputDir,
          mode: state.mode,
          name: $("name").value,
          output_dir: configPathValue("outputDir"),
          output_format: $("format").value,
          sort_by: $("sortBy").value,
          video_codec: $("codec").value,
          gpu: $("gpu").value,
          audio_codec: $("audioCodec").value,
          crf: Number($("crf").value),
          preset: $("preset").value,
          fps_policy: $("fpsPolicy").value,
          resolution_policy: $("resolutionPolicy").value,
          pad_color: $("padColor").value,
          ffmpeg_path: configPathValue("ffmpegPath"),
          ffprobe_path: configPathValue("ffprobePath"),
          temp_dir: configPathValue("tempDir"),
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
        log(t("stoppingMerge"));
        await api("/cancel", {});
      } catch (error) {
        log(`ERROR: ${error.message}`);
      }
    }
    document.querySelectorAll(".mode-card").forEach(card => card.addEventListener("click", () => {
      state.mode = card.dataset.mode;
      renderModes();
      scheduleSaveConfig();
    }));
    $("selectSource").addEventListener("click", () => selectFolder("source"));
    $("selectOutput").addEventListener("click", () => selectFolder("output"));
    $("selectTemp").addEventListener("click", () => selectFolder("temp"));
    $("refresh").addEventListener("click", scan);
    $("startMerge").addEventListener("click", merge);
    $("languageSelect").addEventListener("change", () => {
      state.lang = $("languageSelect").value;
      applyLanguage();
      if (state.files.length) renderFiles(state.files);
      scheduleSaveConfig();
    });
    ["format", "sortBy", "codec", "gpu", "audioCodec", "crf", "preset", "fpsPolicy", "resolutionPolicy", "padColor", "outputDir", "tempDir", "ffmpegPath", "ffprobePath", "recursive", "overwrite", "dryRun", "keepTemp", "autoDownloadDeps"].forEach(id => {
      const node = $(id);
      if (pathFields.includes(id)) {
        node.addEventListener("input", () => {
          node.dataset.custom = node.value.trim() ? "true" : "false";
          if (node.dataset.custom !== "true") refreshDefaultPaths();
        });
      }
      node.addEventListener(node.type === "checkbox" ? "change" : "input", scheduleSaveConfig);
      node.addEventListener("change", scheduleSaveConfig);
    });
    $("ffmpegStatus").addEventListener("click", checkDeps);
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
    (async () => {
      await loadConfig();
      await refreshDefaultPaths();
      applyLanguage();
      log(t("selectBegin"));
      checkDeps();
    })();
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
        self.cleanup_temp_on_cancel = True
        self.temp_paths: list[Path] = []
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

    def begin_run(self, cleanup_temp_on_cancel: bool = True) -> bool:
        with self.lock:
            if self.running:
                return False
            self.logs.clear()
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
    port = port or _free_port()
    state = GuiState()
    server = ThreadingHTTPServer((host, port), _make_handler(state))
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

    webview.create_window(f"VideoMergingTool {__version__}", url, width=1280, height=820, min_size=(900, 620))
    webview.start()


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
            if parsed.path == "/config":
                self._send_json(_load_gui_config())
                return
            if parsed.path == "/defaults":
                self._send_json(_default_display_paths())
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
            if parsed.path == "/config":
                _save_gui_config(payload)
                self._send_json({"ok": True})
                return
            if parsed.path == "/defaults":
                self._send_json(_default_display_paths(str(payload.get("input_dir") or "")))
                return
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

        def _deps(self) -> None:
            try:
                logger = _gui_logger(state)
                tools = resolve_tools(logger, True, default_tools_dir())
                encoders = detect_ffmpeg_encoders(tools, timeout=3)
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
                tools = resolve_tools(logger, True, default_tools_dir())
                input_dir = Path(str(payload["input_dir"]))
                if not input_dir.is_dir():
                    raise ValueError(f"Selected path is not a folder: {input_dir}")
                paths = scan_video_files(
                    input_dir,
                    bool(payload.get("recursive", True)),
                    str(payload.get("sort_by") or "name-natural-asc"),
                )
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
            if not state.begin_run(cleanup_temp_on_cancel=not bool(payload.get("keep_temp"))):
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
    if payload.get("sort_by"):
        cmd.extend(["--sort-by", str(payload["sort_by"])])
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
    if payload.get("temp_dir"):
        cmd.extend(["--temp-dir", str(payload["temp_dir"])])
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
            temp_match = re.search(r"(?:Preprocessing|Concat) temp directory:\s+(.+)$", stripped)
            if temp_match:
                state.record_temp_path(Path(temp_match.group(1).strip()))
            progress_match = re.search(r"Progress:\s+(\d+)/(\d+)\s+\((\d+)%\)", stripped)
            if progress_match:
                state.set_progress(int(progress_match.group(3)))
        code = process.wait()
        was_cancelled = state.finish_process()
        if was_cancelled:
            state.log("Merge stopped by user.")
            _cleanup_cancel_temp_dirs(state)
        elif code == 0:
            state.set_progress(100)
            state.log("Merge completed.")
        else:
            state.log(f"ERROR: Merge failed with exit code {code}.")
    except Exception as exc:
        state.log(f"ERROR: {exc}")
    finally:
        state.finish_process()


def _cleanup_cancel_temp_dirs(state: GuiState) -> None:
    cleaned = 0
    for path in state.consume_cancel_cleanup_paths():
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


def _pick_folder(kind: str) -> str:
    title = "Select output folder" if kind == "output" else "Select source video folder"
    if platform.system() == "Darwin":
        return _pick_folder_macos(title)
    if platform.system() == "Windows":
        return _pick_folder_windows(title) or _pick_folder_tk(title)
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
            **subprocess_window_kwargs(),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        return ""
    return ""


def _pick_folder_windows(title: str) -> str:
    escaped_title = title.replace("'", "''")
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = '{escaped_title}'
$dialog.CheckFileExists = $false
$dialog.ValidateNames = $false
$dialog.FileName = 'Select this folder'
$dialog.Filter = 'All files (*.*)|*.*'
$dialog.RestoreDirectory = $true
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
  $selected = $dialog.FileName
  if (Test-Path -LiteralPath $selected -PathType Container) {{
    Write-Output $selected
  }} else {{
    Write-Output (Split-Path -Parent $selected)
  }}
}}
"""
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
        return ""
    return ""


def _normalize_picked_folder(path_text: str) -> str:
    path_text = path_text.strip().strip('"')
    if not path_text:
        return ""
    path = Path(path_text)
    if path.name == "Select this folder":
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
    allowed = set(CONFIG_FIELD_IDS) | {"lang", "mode"}
    clean = {key: value for key, value in payload.items() if key in allowed}
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")


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
