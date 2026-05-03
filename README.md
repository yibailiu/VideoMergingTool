# VideoMergingTool

[English](README.md) | [简体中文](README.zh-CN.md)

![VideoMergingTool icon](assets/icons/VideoMergingTool.png)

VideoMergingTool is a local batch video merging tool powered by FFmpeg. It provides a clickable desktop GUI for normal users and keeps the CLI available for automation and advanced workflows.

Packaged desktop builds include a compact FFmpeg / FFprobe bundle, so users do not need to install FFmpeg manually.

## Features

- Scans common video formats: `mp4`, `mkv`, `mov`, `avi`, `ts`, `m4v`, `flv`, `webm`
- Optional recursive scanning
- Reads codec, resolution, FPS, pixel format, duration, audio tracks, display orientation, and rotation metadata with `ffprobe`
- `fast` mode: lossless stream-copy merge for fully compatible groups
- `optimal` mode: splits landscape and portrait videos, then normalizes each group when needed
- `extreme` mode: normalizes all videos into one canvas and produces one output
- Adds silent audio for files without audio in transcode modes
- Rotates, scales, and pads videos without cropping
- Supports console logs, file logs, dry-run, overwrite, temp retention, custom output folder, and custom temp folder
- Desktop GUI runs in an embedded app window and does not depend on an external browser
- Built-in i18n with English and Simplified Chinese

## Download And Use

Download the latest build from GitHub Releases.

- Windows: run `VideoMergingTool-Setup.exe`, then launch from Start Menu or the desktop shortcut.
- macOS Apple Silicon: open `VideoMergingTool-macos-apple-silicon.dmg`, then drag `VideoMergingTool.app` into Applications.
- macOS Intel: open `VideoMergingTool-macos-intel.dmg`, then drag `VideoMergingTool.app` into Applications.
- Linux: run `VideoMergingTool`.

The packaged app opens the GUI directly. It does not require command-line startup and does not open an external browser.

### System Security Prompts

Unsigned installers cannot fully bypass Windows SmartScreen or macOS Gatekeeper. Windows requires Authenticode signing with a trusted certificate for publisher identity and reputation. macOS requires Apple Developer ID signing and notarization to avoid manual security approval. The build scripts include optional signing hooks; unsigned builds remain available for testing.

## CLI Examples

Windows:

```powershell
.\VideoMergingTool.exe merge "F:\Videos" --mode fast
```

macOS / Linux:

```bash
./VideoMergingTool merge ~/Videos --mode fast
```

Source checkout:

```bash
python main.py gui
python main.py merge /path/to/input --mode optimal --output-format mp4
```

## Common Options

```text
input_dir                         Input directory
--mode fast|optimal|extreme       Merge mode
--output-dir PATH                 Output directory, default: input_dir/merged
--output-format mp4|mkv|mov|avi|ts|webm
--name TEXT                       Custom output filename without extension
--recursive / --no-recursive      Scan subdirectories, enabled by default
--sort-by TEXT                    Merge order, default: name-natural-asc
--overwrite                       Replace existing output files
--keep-temp                       Keep transcode intermediate files
--temp-dir PATH                   Custom temp directory, default: system temp
--log-file PATH                   Write detailed file logs
--dry-run                         Print plan and commands without running FFmpeg
--pad-color TEXT                  Padding color, default: black
--fps-policy majority|max|min     FPS policy for transcode modes
--video-codec TEXT                Target video codec
--audio-codec TEXT                Target audio codec
--crf INT                         Transcode quality, default: 20
--preset TEXT                     Encoder preset, default: medium
--gpu off|auto|nvenc|qsv|amf|videotoolbox
--ffmpeg-path PATH                Explicit ffmpeg path
--ffprobe-path PATH               Explicit ffprobe path
--auto-download-deps / --no-auto-download-deps
```

`--sort-by` values: `name-natural-asc`, `name-natural-desc`, `name-asc`, `name-desc`, `modified-asc`, `modified-desc`, `size-asc`, `size-desc`.

## GPU Acceleration

GPU acceleration applies only to transcode modes: `optimal` and `extreme`. `fast` mode remains lossless stream copy.

- Windows: `--gpu auto` checks NVIDIA NVENC, Intel QSV, then AMD AMF.
- macOS: `--gpu auto` uses FFmpeg VideoToolbox encoders when available.
- Linux: `--gpu auto` checks NVENC, then QSV.
- If the target codec is not H.264/HEVC, or if the encoder is unavailable, the tool falls back to CPU encoding and writes a log message.

## Merge Modes

### Fast

Fast mode performs true stream copy:

```bash
ffmpeg -f concat -safe 0 -i list.txt -c copy output.mp4
```

Only files with compatible video codec, audio codec, resolution, FPS, pixel format, orientation, and rotation metadata can be merged in the same group.

### Optimal

Optimal mode chooses target codecs by file-count majority, splits files into landscape and portrait groups, selects the largest canvas per group, and scales each input into that canvas without cropping.

### Extreme

Extreme mode normalizes all files to one canvas and codec plan, clears rotation metadata, and produces one final output.

## FFmpeg Discovery

Default lookup order:

1. Bundled `ffmpeg` / `ffprobe` inside the packaged app
2. Source checkout tool directory: `./.tools/ffmpeg`
3. System `PATH` and common install locations
4. Automatic download for source runs when dependencies are still missing

Automatic download sources:

- macOS: evermeet.cx FFmpeg builds
- Windows: gyan.dev FFmpeg essentials build
- Linux: johnvansickle.com static build

## Build Locally

Windows PowerShell:

```powershell
.\scripts\build_windows.ps1
```

macOS / Linux:

```bash
bash scripts/build_local.sh
```

Generated artifacts:

```text
dist/installer/VideoMergingTool-Setup.exe
dist/VideoMergingTool-macos-apple-silicon.dmg
dist/VideoMergingTool-macos-intel.dmg
dist/VideoMergingTool
```

## GitHub Release Builds

GitHub Actions workflow:

```text
.github/workflows/build-and-release.yml
```

- Push to `main` or `dev`: build platform artifacts and upload Actions artifacts.
- Push a version tag such as `v0.2.11-dev`: build release assets and attach them to a GitHub Release.
- Manual run: use `Run workflow` on the Actions page.

Release command:

```bash
git tag v0.2.11-dev
git push origin v0.2.11-dev
```
