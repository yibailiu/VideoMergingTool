You are helping me build a local batch video merging tool for end users.

---

# 版本一：适合贴到 GitHub Issue / 任务系统的简版

## 标题

开发一个本地视频批量智能合并工具（支持快速 / 最优 / 极限三种模式）

## 需求背景

需要开发一个本地视频批量合并工具，面向普通用户使用。工具需要能够扫描指定目录中的视频文件，分析媒体参数，并根据不同模式执行无损合并或统一转码后合并。

优先实现 CLI 版本，但代码结构需要便于后续扩展 GUI。

底层建议使用 FFmpeg + FFprobe。

---

## 核心目标

实现一个可本地运行的视频批量合并工具，支持：

- 扫描目录中的常见视频文件

- 读取媒体信息

- 按规则分组

- 必要时统一转码

- 合并输出

- 输出日志

- 处理异常情况

- 尽量做到普通用户开箱即用

---

## 功能范围

### 1. 输入扫描

支持扫描指定目录中的常见视频格式，包括但不限于：

- mp4

- mkv

- mov

- avi

- ts

- m4v

- flv

- webm

建议支持递归扫描子目录。

需要读取每个文件的媒体信息，包括：

- 视频编码

- 音频编码

- 分辨率

- 宽高比

- 帧率

- 像素格式

- 时长

- 是否有音轨

- 横屏 / 竖屏

- rotation metadata

---

### 2. 合并模式

#### Fast 模式

- 对参数一致的视频进行分组

- 条件包括：视频编码、音频编码、分辨率、帧率、像素格式、方向等

- 对同组视频执行真正的无损合并（stream copy）

- 不满足条件的视频跳过并记录原因

- 若存在多个分组，则输出多个合并结果

#### Optimal 模式

- 对全部视频分析后，统一视频编码和音频编码

- “少数服从多数”默认按文件数量统计

- 无音轨文件需要支持补静音

- 按方向拆分为：
  
  - 横屏一组
  
  - 竖屏一组

- 每组分别统一画布尺寸

- 允许缩放与补边

- 禁止裁切

- 最终横屏输出一个文件，竖屏输出一个文件

#### Extreme 模式

- 对全部视频统一编码、方向、比例和画布

- 允许旋转、缩放、补边

- 禁止裁切

- 所有视频最终合并成一个文件

- rotation metadata 建议在预处理阶段消解

---

### 3. 输出规则

支持：

- 自定义输出目录

- 若未指定，则在原目录创建 `merged` 文件夹

支持：

- 自定义输出文件名

- 或自动命名：`文件夹名_合并_分辨率`

支持输出格式选择：

- mp4

- mkv

- mov

- avi

- ts

- webm

需要处理封装格式与编码兼容性问题。

---

### 4. 日志与异常处理

需要输出完整日志，包括：

- 文件扫描结果

- 媒体信息摘要

- 分组结果

- 跳过原因

- 转码策略

- 合并顺序

- 输出路径

- 错误信息

- 总耗时

至少支持：

- 控制台日志

- 文件日志

需要处理：

- 输入目录不存在

- 目录为空

- 无可识别视频

- ffmpeg / ffprobe 缺失

- 文件损坏

- 无音轨

- 输出目录无权限

- 输出文件已存在

- 转码失败

- 合并失败

- 自动下载依赖失败

---

### 5. 运行方式与依赖管理

重点要求：不要默认要求普通用户手动安装运行环境。

优先方案：

- 提供独立可执行版本，用户无需安装 Python

备选方案：

- 程序启动时自动检测 ffmpeg / ffprobe / 必要依赖

- 若缺失则自动下载并配置

- 尽量不要求用户手动设置环境变量

目标是尽量做到“下载后即可使用”。

---

## 技术建议

- Python 3.11+

- FFmpeg / FFprobe

- typer

- logging

- dataclass

- tempfile

---

## 建议项目结构

- scanner.py

- probe.py

- grouping.py

- transcode.py

- merge.py

- naming.py

- env_check.py

- logger.py

- main.py

---

## 验收标准

- 能运行 CLI

- Fast 模式确实使用 stream copy，不隐式转码

- Optimal / Extreme 模式可以完成统一编码和合并

- 无音轨文件可补静音

- 输出日志清晰

- 支持自动检测依赖

- README 完整

- 提供示例命令

---

# 版本二：适合直接发给 Codex 的英文 Prompt

You are helping me build a local batch video merging tool for end users.

Please implement a **Python-based CLI project first**, with clean modular structure so it can be extended into a GUI later.

The tool should use **FFmpeg + FFprobe** for media probing, transcoding, scaling, padding, rotating, and merging.

## Project goal

Build a local video batch merge tool that can:

- scan a user-selected directory

- detect video files

- probe media information

- group files by compatibility

- transcode when necessary

- merge outputs

- generate logs

- handle failures gracefully

This tool is intended for **normal users**, so usability matters a lot.

---

## Core requirements

### 1. Input scanning

Scan a directory for common video files, at least:

- mp4

- mkv

- mov

- avi

- ts

- m4v

- flv

- webm

Optional: support recursive scanning.

For each file, use `ffprobe` to collect at least:

- file path

- container format

- video codec

- audio codec

- resolution

- width / height

- aspect ratio

- frame rate

- pixel format

- duration

- whether audio track exists

- orientation (landscape / portrait)

- rotation metadata if present

Please store media metadata in structured objects, e.g. dataclasses.

---

### 2. Merge modes

#### Mode A: Fast mode

Goal: merge videos as quickly as possible with **true lossless stream copy**, only when safe.

Rules:

- group videos only if key concat parameters match

- matching criteria should include:
  
  - video codec
  
  - audio codec
  
  - resolution
  
  - frame rate
  
  - pixel format
  
  - orientation
  
  - other critical concat-safe properties

- use true stream copy merge only

- do not silently transcode in this mode

- unmatched files should be skipped and logged

- if multiple compatible groups exist, output multiple merged files

Important:  
“Lossless merge” in this mode explicitly means **stream copy**, not re-encoding.

---

#### Mode B: Optimal mode

Goal: process as many files as possible, unify codecs, then output:

- one merged landscape video

- one merged portrait video

Rules:

- analyze all videos in the folder

- choose the target video codec and target audio codec using **majority vote by file count**

- transcode minority files into the selected target codecs

- if some files have no audio track, add silent audio so concat remains stable

- split videos into:
  
  - landscape group
  
  - portrait group

- for each group, determine a target canvas size using the largest suitable dimensions/spec

- scale videos to fit fully inside the target canvas

- padding is allowed

- cropping is forbidden

- original image content must remain fully visible

- after preprocessing, merge each group into one output

---

#### Mode C: Extreme mode

Goal: preprocess all videos and merge everything into **one final output file**.

Rules:

- unify video codec and audio codec using majority vote by file count

- if needed, add silent audio tracks

- determine one final target canvas / aspect / orientation using the largest suitable spec

- preprocess all videos so they conform to that final target

- allowed operations:
  
  - rotate
  
  - scale
  
  - pad

- forbidden:
  
  - crop

- original image content must remain fully visible

- rotation metadata should preferably be normalized/flattened during preprocessing

- final result should be a single merged file

---

### 3. Output directory

Support both:

- user-defined output directory

- default `merged` folder under the source directory

Create missing directories automatically.

---

### 4. Output filename

Support:

- user-defined filename

- auto-generated names

Suggested auto-naming patterns:

- foldername_merge_resolution

- foldername_landscape_merge_resolution

- foldername_portrait_merge_resolution

- foldername_extreme_merge_resolution

If the filename already exists, append a numeric suffix.

---

### 5. Output container formats

Allow user selection of output container format, at least:

- mp4

- mkv

- mov

- avi

- ts

- webm

Handle container/codec compatibility:

- warn clearly if the selected container is incompatible with the chosen codecs

- or automatically switch to a compatible strategy

---

### 6. Logging

Provide clear logs including:

- scanned files

- media metadata summary

- grouping results

- skipped files and reasons

- chosen target codecs

- preprocessing strategy

- merge order

- output file paths

- errors

- total runtime

- temp file cleanup results

Support:

- console logging

- file logging

Use Python `logging`.

---

### 7. Error handling

Handle at least:

- input directory does not exist

- empty directory

- no recognized video files

- ffmpeg / ffprobe missing

- unreadable or corrupted files

- files without audio track

- output directory permission issues

- existing output files

- transcode failure

- merge failure

- dependency download failure

- temp cleanup failure

The tool should avoid crashing the entire job because of a single problematic file when reasonable.

---

### 8. Runtime / dependency requirement

Important: do **not** assume the user will manually install Python, ffmpeg, or other runtime components.

Preferred approach:

- package the tool as a standalone executable for end users

Fallback approach:

- on startup, detect whether required dependencies are available

- at minimum detect:
  
  - ffmpeg
  
  - ffprobe
  
  - other required external binaries

- if missing, automatically download and configure them

- avoid requiring the user to set environment variables manually

Goal:  
The user should get as close as possible to a **download-and-run** experience.

If full automatic Python installation is too complex, prefer packaging the Python app into a distributable executable and auto-managing only ffmpeg/ffprobe.

---

### 9. CLI requirements

Please implement CLI first, preferably with `typer`.

Suggested command shape:

```bash
python main.py merge /path/to/input --mode fast --output-dir /path/to/output --output-format mp4
```

Suggested options:

- input_dir

- --mode [fast|optimal|extreme]

- --output-dir

- --output-format

- --name

- --recursive

- --overwrite

- --keep-temp

- --log-file

- --dry-run

- --pad-color

- --fps-policy

- --resolution-policy

- --video-codec

- --audio-codec

- --crf

- --preset

---

### 10. Suggested tech stack

- Python 3.11+

- typer

- ffmpeg / ffprobe

- logging

- dataclasses

- tempfile

---

### 11. Suggested module layout

Please keep the project modular, e.g.:

- scanner.py

- probe.py

- grouping.py

- transcode.py

- merge.py

- naming.py

- env_check.py

- logger.py

- main.py

Optional later:

- gui.py

---

### 12. Deliverables

Please provide:

1. complete runnable Python project code

2. requirements.txt

3. README.md

4. project structure explanation

5. CLI usage examples

6. dependency auto-detection / auto-download logic

7. notes for Windows / macOS / Linux

8. a few example commands

---

### 13. Hard constraints

Please follow these strictly:

1. Fast mode must use true stream copy only, never silent re-encoding

2. Majority vote means **by file count**, not by total duration

3. Scaling / rotating / padding must preserve the full visible image

4. Cropping is forbidden

5. Files without audio should be supported via silent audio insertion when needed

6. Minimize unnecessary re-encoding

7. Keep the code modular

8. CLI first, GUI later

9. End-user friendliness matters

10. Logs and error messages must be clear
