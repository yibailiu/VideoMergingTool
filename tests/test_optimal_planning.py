from __future__ import annotations

import unittest
from pathlib import Path

from videomerge.planning import build_extreme_group_plan, build_optimal_group_plan
from videomerge.models import Orientation, VideoFile


class OptimalPlanningTests(unittest.TestCase):
    def test_dominant_policy_only_transcodes_five_4k_outliers(self) -> None:
        files = [
            _video(f"1080_{index}.mp4", 1920, 1080, 4_000_000)
            for index in range(595)
        ] + [
            _video(f"4k_{index}.mp4", 3840, 2160, 15_000_000)
            for index in range(5)
        ]

        plan = build_optimal_group_plan(files)

        self.assertEqual(plan.canvas.label, "1920x1080")
        self.assertEqual(plan.copy_count, 595)
        self.assertEqual(plan.transcode_count, 5)
        self.assertEqual(plan.profile.video_bitrate, 4_000_000)

    def test_largest_policy_requires_explicit_opt_in(self) -> None:
        files = [
            _video(f"1080_{index}.mp4", 1920, 1080, 4_000_000)
            for index in range(5)
        ] + [_video("4k.mp4", 3840, 2160, 15_000_000)]

        plan = build_optimal_group_plan(files, resolution_policy="largest")

        self.assertEqual(plan.canvas.label, "3840x2160")
        self.assertEqual(plan.copy_count, 1)
        self.assertEqual(plan.transcode_count, 5)

    def test_extreme_mode_uses_dominant_canvas_for_595_to_5_batch(self) -> None:
        files = [
            _video(f"1080_{index}.mp4", 1920, 1080, 4_000_000)
            for index in range(595)
        ] + [
            _video(f"4k_{index}.mp4", 3840, 2160, 15_000_000)
            for index in range(5)
        ]

        plan = build_extreme_group_plan(files)

        self.assertEqual(plan.canvas.label, "1920x1080")
        self.assertEqual(plan.copy_count, 595)
        self.assertEqual(plan.transcode_count, 5)

    def test_hevc_dominant_profile_preserves_hevc_target(self) -> None:
        files = [
            _video(f"hevc_{index}.mp4", 1920, 1080, 3_000_000, codec="hevc")
            for index in range(3)
        ]

        plan = build_optimal_group_plan(files)

        self.assertEqual(plan.codec_plan.video_codec, "hevc")
        self.assertEqual(plan.copy_count, 3)
        self.assertEqual(plan.transcode_count, 0)

    def test_large_batch_separates_remux_audio_and_video_actions(self) -> None:
        files = [_video(f"ready_{index}.mp4", 1920, 1080, 4_000_000) for index in range(598)]
        files.append(
            _video("container_only.mkv", 1920, 1080, 4_000_000).__class__(
                **{**_video("container_only.mkv", 1920, 1080, 4_000_000).__dict__, "container": "matroska"}
            )
        )
        files.append(
            _video("audio_only.mp4", 1920, 1080, 4_000_000).__class__(
                **{**_video("audio_only.mp4", 1920, 1080, 4_000_000).__dict__, "audio_sample_rate": 44100}
            )
        )

        plan = build_optimal_group_plan(files)

        self.assertEqual(plan.copy_count, 598)
        self.assertEqual(plan.remux_count, 1)
        self.assertEqual(plan.audio_count, 1)
        self.assertEqual(plan.transcode_count, 0)

    def test_time_base_difference_uses_remux_instead_of_video_transcode(self) -> None:
        ready = [_video(f"ready_{index}.mp4", 1920, 1080, 4_000_000) for index in range(2)]
        different_time_base = _video("different_time_base.mp4", 1920, 1080, 4_000_000).__class__(
            **{
                **_video("different_time_base.mp4", 1920, 1080, 4_000_000).__dict__,
                "video_time_base": "1/90000",
            }
        )

        plan = build_optimal_group_plan([*ready, different_time_base])

        self.assertEqual(plan.copy_count, 2)
        self.assertEqual(plan.remux_count, 1)
        self.assertEqual(plan.transcode_count, 0)


def _video(name: str, width: int, height: int, bitrate: int, codec: str = "h264") -> VideoFile:
    return VideoFile(
        path=Path(name),
        container="mp4",
        video_codec=codec,
        audio_codec="aac",
        width=width,
        height=height,
        display_width=width,
        display_height=height,
        aspect_ratio=f"{width}:{height}",
        frame_rate="30/1",
        frame_rate_float=30.0,
        pixel_format="yuv420p",
        duration=10.0,
        has_audio=True,
        orientation=Orientation.landscape,
        rotation=0,
        video_bitrate=bitrate,
        audio_bitrate=128_000,
        audio_sample_rate=48_000,
        audio_channels=2,
        video_time_base="1/15360",
    )


if __name__ == "__main__":
    unittest.main()
