from __future__ import annotations

import logging
import platform
import shutil
import stat
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from .errors import DependencyError
from .models import ToolPaths


DOWNLOADS = {
    "Darwin": {
        "url": "https://evermeet.cx/ffmpeg/getrelease/zip",
        "ffmpeg_member": "ffmpeg",
        "ffprobe_url": "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
        "ffprobe_member": "ffprobe",
    },
    "Windows": {
        "url": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
        "ffmpeg_member": "ffmpeg.exe",
        "ffprobe_member": "ffprobe.exe",
    },
    "Linux": {
        "url": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
        "ffmpeg_member": "ffmpeg",
        "ffprobe_member": "ffprobe",
    },
}


def resolve_tools(
    logger: logging.Logger,
    auto_download: bool,
    tools_dir: Path,
    ffmpeg_path: Path | None = None,
    ffprobe_path: Path | None = None,
) -> ToolPaths:
    ffmpeg = ffmpeg_path or _find_binary("ffmpeg", tools_dir)
    ffprobe = ffprobe_path or _find_binary("ffprobe", tools_dir)

    if ffmpeg and ffprobe:
        logger.info("Using ffmpeg: %s", ffmpeg)
        logger.info("Using ffprobe: %s", ffprobe)
        return ToolPaths(ffmpeg=ffmpeg, ffprobe=ffprobe)

    if not auto_download:
        missing = []
        if not ffmpeg:
            missing.append("ffmpeg")
        if not ffprobe:
            missing.append("ffprobe")
        raise DependencyError(
            f"Missing {', '.join(missing)}. Install FFmpeg or rerun with --auto-download-deps."
        )

    logger.info("FFmpeg tools are missing; attempting automatic download.")
    downloaded = download_ffmpeg_tools(tools_dir, logger)
    if not downloaded.ffmpeg.exists() or not downloaded.ffprobe.exists():
        raise DependencyError("Automatic FFmpeg download did not produce ffmpeg and ffprobe.")
    return downloaded


def download_ffmpeg_tools(tools_dir: Path, logger: logging.Logger) -> ToolPaths:
    system = platform.system()
    config = DOWNLOADS.get(system)
    if not config:
        raise DependencyError(f"Automatic FFmpeg download is not supported on {system}.")

    tools_dir.mkdir(parents=True, exist_ok=True)
    archive_path = tools_dir / f"ffmpeg_download{_archive_suffix(config['url'])}"
    _download(config["url"], archive_path, logger)
    ffmpeg = _extract_member(archive_path, config["ffmpeg_member"], tools_dir, logger)

    if system == "Darwin" and "ffprobe_url" in config:
        ffprobe_archive = tools_dir / f"ffprobe_download{_archive_suffix(config['ffprobe_url'])}"
        _download(config["ffprobe_url"], ffprobe_archive, logger)
        ffprobe = _extract_member(ffprobe_archive, config["ffprobe_member"], tools_dir, logger)
    else:
        ffprobe = _extract_member(archive_path, config["ffprobe_member"], tools_dir, logger)

    _make_executable(ffmpeg)
    _make_executable(ffprobe)
    logger.info("Downloaded ffmpeg: %s", ffmpeg)
    logger.info("Downloaded ffprobe: %s", ffprobe)
    return ToolPaths(ffmpeg=ffmpeg, ffprobe=ffprobe)


def _find_binary(name: str, tools_dir: Path) -> Path | None:
    local_name = f"{name}.exe" if platform.system() == "Windows" else name
    local = tools_dir / local_name
    if local.exists():
        return local
    found = shutil.which(name)
    return Path(found) if found else None


def _download(url: str, output: Path, logger: logging.Logger) -> None:
    logger.info("Downloading %s", url)
    try:
        urllib.request.urlretrieve(url, output)
    except Exception as exc:  # pragma: no cover - depends on network.
        raise DependencyError(f"Failed to download {url}: {exc}") from exc


def _archive_suffix(url: str) -> str:
    if url.endswith(".tar.xz"):
        return ".tar.xz"
    if url.endswith(".zip") or "zip" in url:
        return ".zip"
    return ".bin"


def _extract_member(archive_path: Path, member_name: str, tools_dir: Path, logger: logging.Logger) -> Path:
    target_name = Path(member_name).name
    output_path = tools_dir / target_name

    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            match = _find_archive_member(archive.namelist(), member_name)
            if not match:
                raise DependencyError(f"Could not find {member_name} in {archive_path.name}.")
            with archive.open(match) as src, output_path.open("wb") as dst:
                dst.write(src.read())
            logger.debug("Extracted %s from %s", match, archive_path)
            return output_path

    try:
        with tarfile.open(archive_path) as archive:
            names = archive.getnames()
            match = _find_archive_member(names, member_name)
            if not match:
                raise DependencyError(f"Could not find {member_name} in {archive_path.name}.")
            extracted = archive.extractfile(match)
            if extracted is None:
                raise DependencyError(f"Could not extract {match}.")
            with extracted, output_path.open("wb") as dst:
                dst.write(extracted.read())
            logger.debug("Extracted %s from %s", match, archive_path)
            return output_path
    except tarfile.TarError as exc:
        raise DependencyError(f"Unsupported or corrupted archive {archive_path}: {exc}") from exc


def _find_archive_member(names: list[str], member_name: str) -> str | None:
    normalized = member_name.replace("\\", "/")
    for name in names:
        if name.replace("\\", "/").endswith(f"/{normalized}") or Path(name).name == normalized:
            return name
    return None


def _make_executable(path: Path) -> None:
    if platform.system() == "Windows":
        return
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
