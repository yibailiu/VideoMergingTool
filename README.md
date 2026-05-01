# VideoMergingTool

![VideoMergingTool icon](assets/icons/VideoMergingTool.png)

本地批量视频智能合并工具。当前版本提供可点击启动的桌面 GUI，同时保留 CLI；内部模块按扫描、探测、分组、转码、合并拆分。

桌面安装包内置精简 FFmpeg / FFprobe 二进制，普通用户安装后即可使用，不需要手动配置环境变量。

## 功能

- 扫描常见视频格式：`mp4`、`mkv`、`mov`、`avi`、`ts`、`m4v`、`flv`、`webm`
- 支持递归扫描
- 使用 `ffprobe` 读取编码、分辨率、帧率、像素格式、时长、音轨、方向、rotation metadata
- `fast` 模式：只对完全兼容的分组做 `-c copy` 无损合并，不隐式转码
- `optimal` 模式：按横屏/竖屏拆分，统一编码、画布、帧率，输出最多两个文件
- `extreme` 模式：统一全部视频为一个画布并输出单个文件
- 无音轨视频在转码模式中自动补静音
- 转码模式只允许旋转、缩放、补边，不裁切
- 支持控制台日志和文件日志
- 支持 dry-run、覆盖、保留临时文件、自定义输出目录和文件名
- 桌面 GUI 使用内嵌窗口，不依赖外部浏览器打开

## 普通用户用法

推荐直接下载 GitHub Release 里的安装包。

- Windows：运行 `VideoMergingTool-Setup.exe` 安装后从开始菜单/桌面图标启动。
- macOS：打开 `VideoMergingTool.dmg`，将 `VideoMergingTool.app` 拖入 Applications 后从图标启动。
- Linux：运行 `VideoMergingTool`。

桌面应用和安装包会使用 `assets/icons/VideoMergingTool.*` 中的应用图标。

打包后的桌面应用无参数启动时会直接打开 GUI，不需要命令行，也不会调用外部浏览器。

仍然可以直接使用命令行：

```powershell
.\VideoMergingTool.exe merge "F:\Videos" --mode fast
```

macOS / Linux CLI 示例：

```bash
./VideoMergingTool merge ~/Videos --mode fast
```

源码运行时仍会在缺少 FFmpeg / FFprobe 时尝试下载到当前运行目录的 `.tools/ffmpeg`。打包后的桌面应用优先使用应用内置的 FFmpeg / FFprobe。

## 开发者运行方式

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 基本用法

启动 GUI：

```bash
python main.py gui
```

CLI 合并：

```bash
python main.py merge /path/to/input --mode fast
```

```bash
python main.py merge /path/to/input \
  --mode optimal \
  --output-dir /path/to/output \
  --output-format mp4 \
  --log-file /path/to/output/merge.log
```

```bash
python main.py merge /path/to/input \
  --mode extreme \
  --name final_video \
  --overwrite \
  --keep-temp
```

## 常用参数

```text
input_dir                         输入目录
--mode fast|optimal|extreme       合并模式
--output-dir PATH                 输出目录，默认 input_dir/merged
--output-format mp4|mkv|mov|avi|ts|webm
--name TEXT                       自定义输出文件名，不含扩展名
--recursive / --no-recursive      是否递归扫描，默认递归
--sort-by TEXT                    合并排序，默认 name-natural-asc
--overwrite                       覆盖已有输出文件
--keep-temp                       保留转码中间文件
--temp-dir PATH                   自定义临时目录，默认使用系统临时目录
--log-file PATH                   写入详细文件日志
--dry-run                         只打印流程和命令，不执行 FFmpeg
--pad-color TEXT                  补边颜色，默认 black
--fps-policy majority|max|min     转码模式帧率策略
--video-codec TEXT                指定目标视频 codec
--audio-codec TEXT                指定目标音频 codec
--crf INT                         转码质量，默认 20
--preset TEXT                     编码 preset，默认 medium
--gpu off|auto|nvenc|qsv|amf|videotoolbox
                                  转码模式使用 GPU 硬件编码加速，默认 off
--ffmpeg-path PATH                指定 ffmpeg
--ffprobe-path PATH               指定 ffprobe
--auto-download-deps / --no-auto-download-deps
```

`--sort-by` 可选值：`name-natural-asc`、`name-natural-desc`、`name-asc`、`name-desc`、`modified-asc`、`modified-desc`、`size-asc`、`size-desc`。

## GPU 加速

GPU 加速只作用于需要转码的 `optimal` / `extreme` 模式，`fast` 模式仍然使用无损 stream copy。

- Windows：`--gpu auto` 按 NVIDIA NVENC、Intel QSV、AMD AMF 的顺序选择可用编码器。
- macOS：`--gpu auto` 使用 FFmpeg 的 VideoToolbox 编码器（`h264_videotoolbox` / `hevc_videotoolbox`）。
- Linux：`--gpu auto` 优先 NVENC，其次 QSV。
- 如果目标视频编码不是 H.264/HEVC，或者当前 FFmpeg 没有对应硬件编码器，会自动回退 CPU 编码并写入日志。

macOS 的 VideoToolbox 不支持 libx264 风格的 CRF 控制，工具会把 `--crf` 映射为码率区间；数值越低仍表示质量越高、文件越大。

## 三种模式说明

### Fast

Fast 模式只做真正的 stream copy：

```bash
ffmpeg -f concat -safe 0 -i list.txt -c copy output.mp4
```

只有视频编码、音频编码、分辨率、帧率、像素格式、方向、rotation 等关键参数一致的文件才会进入同一组。单文件组会被跳过并写入日志。

### Optimal

Optimal 模式按文件数量多数投票选择目标视频和音频 codec，然后拆成横屏、竖屏两组。每组选择最大画布，所有输入都会完整缩放进画布并补边，不裁切。无音轨文件会添加静音音轨。

### Extreme

Extreme 模式对全部文件选择一个最终画布和编码策略，消解 rotation metadata，统一转码后合并为一个文件。

## 输出命名

未指定 `--name` 时会自动生成：

- `文件夹名_fast_序号_merge_分辨率`
- `文件夹名_landscape_merge_分辨率`
- `文件夹名_portrait_merge_分辨率`
- `文件夹名_extreme_merge_分辨率`

如果文件已存在且未传 `--overwrite`，会自动追加 `_1`、`_2` 等后缀。

## FFmpeg 检测

默认行为：

1. 打包应用优先使用应用内置的 `ffmpeg` / `ffprobe`
2. 源码运行时查找本地工具目录 `./.tools/ffmpeg`
3. 查找系统 `PATH` 和常见安装路径
4. 源码运行时如果仍缺失，尝试下载静态 FFmpeg / FFprobe

自动下载地址按平台选择：

- macOS: evermeet.cx FFmpeg builds
- Windows: gyan.dev FFmpeg essentials build
- Linux: johnvansickle.com static build

如果源码运行时网络不可用或下载源不可达，可以手动安装 FFmpeg，或用 `--ffmpeg-path` 和 `--ffprobe-path` 指定二进制路径。

## 本地打包为独立可执行文件

Windows PowerShell:

```powershell
.\scripts\build_windows.ps1
```

生成文件：

```text
dist\VideoMergingTool.exe
dist\installer\VideoMergingTool-Setup.exe
```

macOS / Linux:

```bash
bash scripts/build_local.sh
```

生成文件：

```text
dist/VideoMergingTool.app   # macOS
dist/VideoMergingTool.dmg   # macOS 安装镜像
dist/VideoMergingTool       # Linux
```

## GitHub 自动打包和发布

仓库包含 GitHub Actions workflow：

```text
.github/workflows/build-and-release.yml
```

自动行为：

- 推送到 `main`：自动构建 Windows、macOS、Linux 三个平台的可执行文件，并上传到 Actions Artifacts
- 推送版本 tag，例如 `v0.1.0`：自动构建三个平台，并创建 GitHub Release，附带 `.dmg`、Windows 安装 `.exe` 和 Linux 可执行文件
- 手动触发 workflow：可在 GitHub Actions 页面点击 `Run workflow`

发布新版本：

```bash
git tag v0.1.0
git push origin v0.1.0
```

发布后，用户可以在 GitHub 仓库的 Releases 页面下载：

- `VideoMergingTool-Setup.exe`
- `VideoMergingTool.dmg`
- `VideoMergingTool`

## 平台说明

- macOS/Linux: 需要给打包后的二进制执行权限
- Windows: 建议在 PowerShell 或 CMD 中运行
- WebM 输出会自动倾向 VP9 + Opus
- MP4 输出建议使用 H.264 + AAC

## 示例

快速无损合并兼容文件：

```bash
python main.py merge ~/Videos/trip --mode fast --output-format mp4
```

尽可能处理所有视频，分别输出横屏和竖屏：

```bash
python main.py merge ~/Videos/mixed --mode optimal --crf 20 --preset medium
```

强制输出一个最终文件：

```bash
python main.py merge ~/Videos/mixed --mode extreme --name all_in_one --overwrite
```

只查看计划和 FFmpeg 命令：

```bash
python main.py merge ~/Videos/mixed --mode optimal --dry-run --verbose
```
