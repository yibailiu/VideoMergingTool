class VideoMergeError(Exception):
    """Base exception for user-facing video merge errors."""


class DependencyError(VideoMergeError):
    """Raised when FFmpeg or FFprobe cannot be found or prepared."""


class ProbeError(VideoMergeError):
    """Raised when a media file cannot be probed."""


class CommandError(VideoMergeError):
    """Raised when an external command fails."""


class NoUsableInputs(CommandError):
    """Every input of one output group was explicitly excluded as damaged."""
