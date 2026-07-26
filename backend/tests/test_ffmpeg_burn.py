from __future__ import annotations

import subprocess

import pytest

from app.services import ffmpeg_burn
from app.services.ffmpeg_burn import (
    VideoLayout,
    VideoLayoutProbeError,
    probe_video_layout,
)


def test_parse_cropdetect_output_uses_last_accumulated_crop() -> None:
    output = """
    [Parsed_cropdetect_0] x1:660 x2:1259 y1:0 y2:1079 w:600 h:1080 x:660 y:0 pts:1 crop=600:1080:660:0
    [Parsed_cropdetect_0] x1:656 x2:1263 y1:0 y2:1079 w:608 h:1080 x:656 y:0 pts:2 crop=608:1080:656:0
    """

    assert ffmpeg_burn._parse_cropdetect_output(output) == (608, 1080, 656, 0)


def test_probe_crop_sample_retries_once_after_timeout(monkeypatch) -> None:
    calls: list[list[str]] = []
    crop_output = (
        "[Parsed_cropdetect_0] "
        "w:608 h:1080 x:656 y:0 crop=608:1080:656:0"
    )

    def fake_run(command, **_kwargs):
        calls.append(command)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(command, timeout=15)
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="",
            stderr=crop_output,
        )

    monkeypatch.setattr(ffmpeg_burn.subprocess, "run", fake_run)

    assert ffmpeg_burn._probe_crop_sample("https://example/episode.mp4", 10) == (
        608,
        1080,
        656,
        0,
    )
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("video_path", "expected_timeout"),
    [
        ("episode.mp4", 30),
        ("https://example/episode.mp4", 60),
    ],
)
def test_probe_video_size_uses_source_specific_timeout(
    monkeypatch,
    video_path: str,
    expected_timeout: int,
) -> None:
    calls: list[int] = []

    def fake_run(command, **kwargs):
        calls.append(kwargs["timeout"])
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="1920,1080\n",
            stderr="",
        )

    monkeypatch.setattr(ffmpeg_burn.subprocess, "run", fake_run)

    assert ffmpeg_burn.probe_video_size(video_path) == (1920, 1080)
    assert calls == [expected_timeout]


@pytest.mark.parametrize(
    ("video_path", "expected_timeout"),
    [
        ("episode.mp4", 15),
        ("https://example/episode.mp4", 45),
    ],
)
def test_probe_crop_sample_uses_source_specific_timeout(
    monkeypatch,
    video_path: str,
    expected_timeout: int,
) -> None:
    calls: list[int] = []

    def fake_run(command, **kwargs):
        calls.append(kwargs["timeout"])
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(ffmpeg_burn.subprocess, "run", fake_run)

    assert ffmpeg_burn._probe_crop_sample(video_path, 10) is None
    assert calls == [expected_timeout]


def test_probe_video_layout_wraps_video_size_probe_timeout(monkeypatch) -> None:
    def fail_size_probe(_path: str):
        raise subprocess.TimeoutExpired(["ffprobe"], timeout=30)

    monkeypatch.setattr(ffmpeg_burn, "probe_video_size", fail_size_probe)

    with pytest.raises(VideoLayoutProbeError, match="video size probe failed"):
        probe_video_layout("https://example/episode.mp4", duration_seconds=100)


def test_probe_video_layout_returns_full_frame_for_portrait_without_crop_probe(
    monkeypatch,
) -> None:
    monkeypatch.setattr(ffmpeg_burn, "probe_video_size", lambda _path: (1080, 1920))

    def fail_probe(*_args, **_kwargs):
        raise AssertionError("portrait video must not run another probe")

    monkeypatch.setattr(ffmpeg_burn, "probe_video_duration_seconds", fail_probe)
    monkeypatch.setattr(ffmpeg_burn, "_probe_crop_sample", fail_probe)

    assert probe_video_layout("portrait.mp4") == VideoLayout.full_frame(1080, 1920)


def test_probe_video_layout_accepts_stable_centered_pillarbox(
    monkeypatch,
) -> None:
    monkeypatch.setattr(ffmpeg_burn, "probe_video_size", lambda _path: (1920, 1080))
    crops = iter(
        [
            (608, 1080, 656, 0),
            (610, 1080, 655, 0),
        ]
    )
    monkeypatch.setattr(
        ffmpeg_burn,
        "_probe_crop_sample",
        lambda _path, _timestamp: next(crops),
    )

    layout = probe_video_layout("episode.mp4", duration_seconds=100)

    assert layout == VideoLayout(
        canvas_width=1920,
        canvas_height=1080,
        content_x=656,
        content_y=0,
        content_width=608,
        content_height=1080,
    )


def test_probe_video_layout_uses_third_sample_to_resolve_disagreement(
    monkeypatch,
) -> None:
    monkeypatch.setattr(ffmpeg_burn, "probe_video_size", lambda _path: (1920, 1080))
    crops = iter(
        [
            (608, 1080, 656, 0),
            (800, 1080, 560, 0),
            (610, 1080, 655, 0),
        ]
    )
    monkeypatch.setattr(
        ffmpeg_burn,
        "_probe_crop_sample",
        lambda _path, _timestamp: next(crops),
    )

    layout = probe_video_layout("episode.mp4", duration_seconds=100)

    assert layout.content_x == 656
    assert layout.content_width == 608


def test_probe_video_layout_falls_back_when_samples_are_inconsistent(
    monkeypatch,
) -> None:
    monkeypatch.setattr(ffmpeg_burn, "probe_video_size", lambda _path: (1920, 1080))
    crops = iter(
        [
            (608, 1080, 656, 0),
            (800, 1080, 560, 0),
            (1000, 1080, 460, 0),
        ]
    )
    monkeypatch.setattr(
        ffmpeg_burn,
        "_probe_crop_sample",
        lambda _path, _timestamp: next(crops),
    )

    assert probe_video_layout(
        "episode.mp4", duration_seconds=100
    ) == VideoLayout.full_frame(1920, 1080)


def test_probe_video_layout_rejects_non_pillarbox_crop(monkeypatch) -> None:
    monkeypatch.setattr(ffmpeg_burn, "probe_video_size", lambda _path: (1920, 1080))
    crops = iter(
        [
            (608, 900, 656, 90),
            (608, 900, 656, 90),
            (608, 900, 656, 90),
        ]
    )
    monkeypatch.setattr(
        ffmpeg_burn,
        "_probe_crop_sample",
        lambda _path, _timestamp: next(crops),
    )

    assert probe_video_layout(
        "episode.mp4", duration_seconds=100
    ) == VideoLayout.full_frame(1920, 1080)


def test_probe_video_layout_falls_back_when_all_crop_probes_error(
    monkeypatch,
) -> None:
    monkeypatch.setattr(ffmpeg_burn, "probe_video_size", lambda _path: (1920, 1080))

    def fail_probe(_path: str, _timestamp: float):
        raise TimeoutError("ffmpeg timed out")

    monkeypatch.setattr(ffmpeg_burn, "_probe_crop_sample", fail_probe)

    assert probe_video_layout(
        "episode.mp4", duration_seconds=100
    ) == VideoLayout.full_frame(1920, 1080)


def test_probe_video_layout_falls_back_when_only_one_remote_sample_succeeds(
    monkeypatch,
) -> None:
    monkeypatch.setattr(ffmpeg_burn, "probe_video_size", lambda _path: (1920, 1080))
    samples = iter(
        [
            TimeoutError("first sample timed out"),
            TimeoutError("second sample timed out"),
            (608, 1080, 656, 0),
        ]
    )

    def sample_or_raise(_path: str, _timestamp: float):
        result = next(samples)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(ffmpeg_burn, "_probe_crop_sample", sample_or_raise)

    assert probe_video_layout(
        "https://example/episode.mp4", duration_seconds=100
    ) == VideoLayout.full_frame(1920, 1080)
