from __future__ import annotations

from app.services import ffmpeg_burn
from app.services.ffmpeg_burn import VideoLayout, probe_video_layout


def test_parse_cropdetect_output_uses_last_accumulated_crop() -> None:
    output = """
    [Parsed_cropdetect_0] x1:660 x2:1259 y1:0 y2:1079 w:600 h:1080 x:660 y:0 pts:1 crop=600:1080:660:0
    [Parsed_cropdetect_0] x1:656 x2:1263 y1:0 y2:1079 w:608 h:1080 x:656 y:0 pts:2 crop=608:1080:656:0
    """

    assert ffmpeg_burn._parse_cropdetect_output(output) == (608, 1080, 656, 0)


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


def test_probe_video_layout_falls_back_when_crop_probe_errors(
    monkeypatch,
) -> None:
    monkeypatch.setattr(ffmpeg_burn, "probe_video_size", lambda _path: (1920, 1080))

    def fail_probe(_path: str, _timestamp: float):
        raise TimeoutError("ffmpeg timed out")

    monkeypatch.setattr(ffmpeg_burn, "_probe_crop_sample", fail_probe)

    assert probe_video_layout(
        "episode.mp4", duration_seconds=100
    ) == VideoLayout.full_frame(1920, 1080)
