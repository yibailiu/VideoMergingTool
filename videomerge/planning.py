from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .grouping import (
    DominantSourceProfile,
    choose_canvas,
    choose_dominant_source_profile,
    choose_fps,
    majority_codec_plan,
)
from .models import Canvas, CodecPlan, VideoFile
from .transcode import plan_preprocess_actions


@dataclass(frozen=True)
class OptimalGroupPlan:
    profile: DominantSourceProfile
    canvas: Canvas
    fps: float
    codec_plan: CodecPlan
    actions: dict[Path, str]

    @property
    def copy_count(self) -> int:
        return sum(action == "copy" for action in self.actions.values())

    @property
    def remux_count(self) -> int:
        return sum(action == "remux" for action in self.actions.values())

    @property
    def audio_count(self) -> int:
        return sum(action == "audio" for action in self.actions.values())

    @property
    def transcode_count(self) -> int:
        return sum(action == "transcode" for action in self.actions.values())


def build_optimal_group_plan(
    files: list[VideoFile],
    output_format: str = "mp4",
    requested_video_codec: str | None = None,
    requested_audio_codec: str | None = None,
    fps_policy: str = "majority",
    resolution_policy: str = "dominant",
) -> OptimalGroupPlan:
    profile = choose_dominant_source_profile(files)
    codec_plan = majority_codec_plan(
        profile.files,
        requested_video_codec,
        requested_audio_codec,
        default_video_codec=_default_video_codec(output_format),
    )
    codec_plan = _adjust_for_container(codec_plan, output_format)
    canvas = choose_canvas(files) if resolution_policy == "largest" else profile.canvas
    fps = choose_fps(files, fps_policy) if fps_policy in {"max", "min"} else profile.fps
    actions = plan_preprocess_actions(
        files,
        canvas,
        fps,
        codec_plan,
        reference_files=profile.files,
    )
    return OptimalGroupPlan(
        profile=profile,
        canvas=canvas,
        fps=fps,
        codec_plan=codec_plan,
        actions=actions,
    )


def build_extreme_group_plan(
    files: list[VideoFile],
    output_format: str = "mp4",
    requested_video_codec: str | None = None,
    requested_audio_codec: str | None = None,
    fps_policy: str = "majority",
) -> OptimalGroupPlan:
    return build_optimal_group_plan(
        files,
        output_format=output_format,
        requested_video_codec=requested_video_codec,
        requested_audio_codec=requested_audio_codec,
        fps_policy=fps_policy,
        resolution_policy="dominant",
    )


def _default_video_codec(output_format: str) -> str:
    return "vp9" if output_format == "webm" else "h264"


def _adjust_for_container(plan: CodecPlan, output_format: str) -> CodecPlan:
    if output_format != "webm":
        return plan
    video_codec = plan.video_codec if plan.output_video_encoder in {"libvpx", "libvpx-vp9", "libaom-av1"} else "vp9"
    video_encoder = plan.output_video_encoder if video_codec == plan.video_codec else "libvpx-vp9"
    audio_codec = plan.audio_codec if plan.output_audio_encoder in {"libopus", "libvorbis"} else "opus"
    audio_encoder = plan.output_audio_encoder if audio_codec == plan.audio_codec else "libopus"
    return CodecPlan(video_codec, audio_codec, video_encoder, audio_encoder)
