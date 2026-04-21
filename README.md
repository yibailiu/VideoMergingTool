# VideoMergingTool

本地批量视频智能合并工具。当前版本优先提供 CLI，内部模块按扫描、探测、分组、转码、合并拆分，后续可以扩展 GUI。

底层依赖 FFmpeg / FFprobe。程序启动时会优先查找系统已有二进制；缺失时默认尝试下载安装到项目目录 `.tools/ffmpeg`，避免普通用户手动配置环境变量。

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

## 安装开发依赖

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
--overwrite                       覆盖已有输出文件
--keep-temp                       保留转码中间文件
--log-file PATH                   写入详细文件日志
--dry-run                         只打印流程和命令，不执行 FFmpeg
--pad-color TEXT                  补边颜色，默认 black
--fps-policy majority|max|min     转码模式帧率策略
--video-codec TEXT                指定目标视频 codec
--audio-codec TEXT                指定目标音频 codec
--crf INT                         转码质量，默认 20
--preset TEXT                     编码 preset，默认 medium
--ffmpeg-path PATH                指定 ffmpeg
--ffprobe-path PATH               指定 ffprobe
--auto-download-deps / --no-auto-download-deps
```

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

## 依赖自动检测和下载

默认行为：

1. 查找 `./.tools/ffmpeg`
2. 查找系统 `PATH`
3. 如果缺失，尝试下载静态 FFmpeg/FFprobe 到 `./.tools/ffmpeg`

自动下载地址按平台选择：

- macOS: evermeet.cx FFmpeg builds
- Windows: gyan.dev FFmpeg essentials build
- Linux: johnvansickle.com static build

如果网络不可用或下载源不可达，可以手动安装 FFmpeg，或用 `--ffmpeg-path` 和 `--ffprobe-path` 指定二进制路径。

## 打包为独立可执行文件

推荐使用 PyInstaller：

```bash
pip install pyinstaller
pyinstaller --onefile --name VideoMergingTool main.py
```

生成文件位于 `dist/VideoMergingTool`。面向普通用户分发时，可以保留自动下载 FFmpeg 的逻辑，也可以把 FFmpeg/FFprobe 一起打包到应用目录。

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
