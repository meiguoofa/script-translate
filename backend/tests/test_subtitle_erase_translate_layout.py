from __future__ import annotations

from app.services import subtitle_erase_translate_runner as runner
from app.services.ffmpeg_burn import VideoLayout


def _snapshot() -> dict:
    return {
        "placement_mode": "simple_bottom",
        "burn_font_size": 4,
        "burn_font_color": "#FFFFFF",
        "burn_font_color_opacity": 1.0,
        "burn_x": 0.5,
        "burn_y": 0.9,
        "burn_text_width": 0.9,
    }


def test_build_ass_for_video_passes_effective_picture_to_srt_to_ass(
    monkeypatch,
) -> None:
    layout = VideoLayout(
        canvas_width=1920,
        canvas_height=1080,
        content_x=656,
        content_y=0,
        content_width=608,
        content_height=1080,
    )
    probe_call: dict = {}
    ass_call: dict = {}

    def fake_probe(path: str, *, duration_seconds: float | None = None):
        probe_call.update(path=path, duration_seconds=duration_seconds)
        return layout

    def fake_srt_to_ass(entries, **kwargs):
        ass_call.update(entries=entries, **kwargs)
        return "generated ass"

    monkeypatch.setattr(runner, "probe_video_layout", fake_probe)
    monkeypatch.setattr(runner, "srt_to_ass", fake_srt_to_ass)

    ass_text, actual_layout = runner._build_ass_for_video(
        "clean.mp4",
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n",
        _snapshot(),
        duration_seconds=42.5,
    )

    assert ass_text == "generated ass"
    assert actual_layout == layout
    assert probe_call == {"path": "clean.mp4", "duration_seconds": 42.5}
    assert ass_call["video_w"] == 1920
    assert ass_call["video_h"] == 1080
    assert ass_call["content_x_px"] == 656
    assert ass_call["content_width_px"] == 608


async def test_build_ass_for_oss_video_probes_public_url(monkeypatch) -> None:
    calls: dict = {}
    layout = VideoLayout.full_frame(1920, 1080)

    class FakeOSS:
        def public_url(self, key: str) -> str:
            calls["key"] = key
            return f"https://cdn.example/{key}"

    def fake_build(video_source, srt_text, snapshot, *, duration_seconds):
        calls.update(
            video_source=video_source,
            srt_text=srt_text,
            snapshot=snapshot,
            duration_seconds=duration_seconds,
        )
        return "ass", layout

    monkeypatch.setattr(runner, "_build_ass_for_video", fake_build)

    result = await runner._build_ass_for_oss_video(
        FakeOSS(),
        "oss://bucket/path/clean.mp4",
        "subtitle",
        _snapshot(),
        duration_seconds=12,
    )

    assert result == ("ass", layout)
    assert calls["key"] == "path/clean.mp4"
    assert calls["video_source"] == "https://cdn.example/path/clean.mp4"
    assert calls["duration_seconds"] == 12
