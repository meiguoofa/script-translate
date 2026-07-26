from __future__ import annotations

from types import SimpleNamespace

from app.routers import subtitle_erase as subtitle_erase_router
from app.services import subtitle_erase_translate_runner as runner
from app.services.ffmpeg_burn import VideoLayout, VideoLayoutProbeError


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


def test_build_ass_from_layout_never_probes_video(monkeypatch) -> None:
    layout = VideoLayout(
        canvas_width=1920,
        canvas_height=1080,
        content_x=656,
        content_y=0,
        content_width=608,
        content_height=1080,
    )
    ass_call: dict = {}

    def fail_probe(*_args, **_kwargs):
        raise AssertionError("ASS rendering must not probe the video")

    def fake_srt_to_ass(entries, **kwargs):
        ass_call.update(entries=entries, **kwargs)
        return "shared-layout-ass"

    monkeypatch.setattr(runner, "probe_video_layout", fail_probe)
    monkeypatch.setattr(runner, "srt_to_ass", fake_srt_to_ass)

    result = runner._build_ass_from_layout(
        "1\n00:00:00,000 --> 00:00:01,000\nOlá\n",
        _snapshot(),
        layout,
    )

    assert result == "shared-layout-ass"
    assert ass_call["content_x_px"] == 656
    assert ass_call["content_width_px"] == 608


def test_active_picture_layout_wraps_long_portuguese_subtitle() -> None:
    layout = VideoLayout(
        canvas_width=1920,
        canvas_height=1080,
        content_x=656,
        content_y=0,
        content_width=608,
        content_height=1080,
    )
    srt_text = (
        "1\n"
        "00:00:00,000 --> 00:00:03,000\n"
        "A casa de casamento fui eu que comprei à vista antes de me casar\n"
    )

    ass_text = runner._build_ass_from_layout(srt_text, _snapshot(), layout)

    assert "Style: Default,Noto Sans CJK SC,43" in ass_text
    assert ",686,686,60,1" in ass_text
    assert "\\N" in ass_text


async def test_probe_oss_video_layout_uses_public_url(monkeypatch) -> None:
    calls: dict = {}
    layout = VideoLayout.full_frame(1920, 1080)

    class FakeOSS:
        def public_url(self, key: str) -> str:
            calls["key"] = key
            return f"https://cdn.example/{key}"

    def fake_probe(video_source, *, duration_seconds):
        calls.update(
            video_source=video_source,
            duration_seconds=duration_seconds,
        )
        return layout

    monkeypatch.setattr(runner, "probe_video_layout", fake_probe)

    result = await runner._probe_oss_video_layout(
        FakeOSS(),
        "oss://bucket/path/clean.mp4",
        duration_seconds=12,
    )

    assert result == layout
    assert calls["key"] == "path/clean.mp4"
    assert calls["video_source"] == "https://cdn.example/path/clean.mp4"
    assert calls["duration_seconds"] == 12


async def test_probe_oss_video_layout_wraps_public_url_errors() -> None:
    class FailingOSS:
        def public_url(self, _key: str) -> str:
            raise OSError("OSS endpoint unavailable")

    try:
        await runner._probe_oss_video_layout(
            FailingOSS(),
            "oss://bucket/path/clean.mp4",
            duration_seconds=12,
        )
    except VideoLayoutProbeError as exc:
        assert "OSS video layout probe failed" in str(exc)
    else:
        raise AssertionError("expected VideoLayoutProbeError")


async def test_get_or_probe_oss_video_layout_caches_and_reuses_result(
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
    calls = 0

    async def fake_probe(_oss, _oss_uri, *, duration_seconds):
        nonlocal calls
        calls += 1
        assert duration_seconds == 45
        return layout

    monkeypatch.setattr(runner, "_probe_oss_video_layout", fake_probe, raising=False)
    item: dict = {}
    source_uri = "oss://bucket/path/clean.mp4"

    first, first_created = await runner._get_or_probe_oss_video_layout(
        object(),
        item,
        source_uri,
        duration_seconds=45,
    )
    second, second_created = await runner._get_or_probe_oss_video_layout(
        object(),
        item,
        source_uri,
        duration_seconds=45,
    )

    assert first == second == layout
    assert first_created is True
    assert second_created is False
    assert calls == 1
    assert item["video_layout"] == {
        "version": 1,
        "source_oss_uri": source_uri,
        "canvas_width": 1920,
        "canvas_height": 1080,
        "content_x": 656,
        "content_y": 0,
        "content_width": 608,
        "content_height": 1080,
    }


def test_video_layout_cache_rejects_wrong_source_and_invalid_bounds() -> None:
    cache = {
        "version": 1,
        "source_oss_uri": "oss://bucket/old.mp4",
        "canvas_width": 1920,
        "canvas_height": 1080,
        "content_x": 656,
        "content_y": 0,
        "content_width": 608,
        "content_height": 1080,
    }

    assert (
        runner._video_layout_from_cache(cache, "oss://bucket/current.mp4") is None
    )

    cache["source_oss_uri"] = "oss://bucket/current.mp4"
    cache["content_width"] = 1400
    assert (
        runner._video_layout_from_cache(cache, "oss://bucket/current.mp4") is None
    )


def test_video_layout_cache_rejects_boolean_version() -> None:
    source_uri = "oss://bucket/current.mp4"
    cache = {
        "version": True,
        "source_oss_uri": source_uri,
        "canvas_width": 1920,
        "canvas_height": 1080,
        "content_x": 656,
        "content_y": 0,
        "content_width": 608,
        "content_height": 1080,
    }

    assert runner._video_layout_from_cache(cache, source_uri) is None


def test_force_redetext_invalidates_cached_video_layout() -> None:
    assert "video_layout" in subtitle_erase_router.REDETEXT_FIELDS


def _reused_episode_fixture() -> tuple[dict, list[dict]]:
    snapshot = {
        **_snapshot(),
        "target_langs": ["en", "pt"],
        "force_redetext": False,
        "force_recaption": False,
        "burn_mode": "mps",
        "output_oss_prefix": "oss://bucket/output",
    }
    items = [
        {
            "input_oss_uri": "oss://bucket/input/video.mp4",
            "drama_index": 0,
            "episode_index": 0,
            "filename": "video.mp4",
            "duration_seconds": 100,
            "clean_video_oss_uri": (
                "oss://bucket/output/drama-00/ep00-video.clean.mp4"
            ),
            "cleaned_srt_oss_uri": (
                "oss://bucket/output/drama-00/ep00-video.clean.srt"
            ),
            "translations": {},
        }
    ]
    return snapshot, items


async def test_mps_episode_passes_one_shared_layout_to_all_languages(
    monkeypatch,
) -> None:
    snapshot, items = _reused_episode_fixture()
    layout = VideoLayout(
        canvas_width=1920,
        canvas_height=1080,
        content_x=656,
        content_y=0,
        content_width=608,
        content_height=1080,
    )
    layout_calls = 0
    received_layouts: list[VideoLayout | None] = []

    class FakeOSS:
        bucket_name = "bucket"

        def get_object_text(self, _key):
            return "1\n00:00:00,000 --> 00:00:01,000\nHello\n"

    async def fake_persist(*_args, **_kwargs):
        return None

    async def fake_get_layout(*_args, **_kwargs):
        nonlocal layout_calls
        layout_calls += 1
        return layout, True

    async def fake_run_translation(*_args, video_layout=None, **_kwargs):
        lang = _args[9]
        received_layouts.append(video_layout)
        items[0]["translations"][lang] = {"status": "succeeded"}

    monkeypatch.setattr(runner, "_persist_items", fake_persist)
    monkeypatch.setattr(
        runner, "_get_or_probe_oss_video_layout", fake_get_layout, raising=False
    )
    monkeypatch.setattr(runner, "_run_translation_for_lang", fake_run_translation)

    await runner._run_episode_impl(
        object(),
        "job-id",
        object(),
        FakeOSS(),
        None,
        object(),
        snapshot,
        items,
        0,
    )

    assert layout_calls == 1
    assert received_layouts == [layout, layout]
    assert items[0]["status"] == "succeeded"


async def test_mps_episode_does_not_submit_languages_when_layout_probe_fails(
    monkeypatch,
) -> None:
    snapshot, items = _reused_episode_fixture()
    translation_calls = 0

    class FakeOSS:
        bucket_name = "bucket"

        def get_object_text(self, _key):
            return "1\n00:00:00,000 --> 00:00:01,000\nHello\n"

    async def fake_persist(*_args, **_kwargs):
        return None

    async def fail_layout(*_args, **_kwargs):
        raise VideoLayoutProbeError("insufficient successful samples")

    async def fake_run_translation(*_args, **_kwargs):
        nonlocal translation_calls
        translation_calls += 1

    monkeypatch.setattr(runner, "_persist_items", fake_persist)
    monkeypatch.setattr(
        runner, "_get_or_probe_oss_video_layout", fail_layout, raising=False
    )
    monkeypatch.setattr(runner, "_run_translation_for_lang", fake_run_translation)

    await runner._run_episode_impl(
        object(),
        "job-id",
        object(),
        FakeOSS(),
        None,
        object(),
        snapshot,
        items,
        0,
    )

    assert translation_calls == 0
    assert items[0]["status"] == "failed"
    assert "远程视频布局探测失败" in items[0]["error"]


async def test_mps_language_burn_renders_ass_from_supplied_layout(
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
    items = [{"duration_seconds": 100, "translations": {"pt": {}}}]
    snapshot = {
        **_snapshot(),
        "translate_mode": "none",
        "burn_mode": "mps",
        "source_lang": "auto",
    }
    rendered_layouts: list[VideoLayout] = []
    uploaded_ass: list[str] = []

    class FakeOSS:
        bucket_name = "bucket"

        def put_object_text(self, _key, text):
            uploaded_ass.append(text)

        def public_url(self, key):
            return f"https://cdn.example/{key}"

    class FakeMPS:
        def __init__(self, _settings):
            pass

        async def submit_subtitle_burn(self, **_kwargs):
            return SimpleNamespace(job_id="mps-job")

        async def wait_for_job(self, _job_id, **_kwargs):
            return None

    async def fake_persist(*_args, **_kwargs):
        return None

    def fake_render(_srt_text, _snapshot_value, actual_layout):
        rendered_layouts.append(actual_layout)
        return "ass-from-shared-layout"

    monkeypatch.setattr(runner, "_persist_items", fake_persist)
    monkeypatch.setattr(runner, "_build_ass_from_layout", fake_render)
    monkeypatch.setattr(runner, "MPSClient", FakeMPS)

    await runner._run_translation_for_lang(
        object(),
        "job-id",
        object(),
        FakeOSS(),
        None,
        SimpleNamespace(
            ims_poll_interval_seconds=1,
            ims_poll_timeout_seconds=10,
        ),
        snapshot,
        items,
        0,
        "pt",
        "oss://bucket/clean.srt",
        "1\n00:00:00,000 --> 00:00:01,000\nOlá\n",
        "oss://bucket/clean.mp4",
        "output",
        0,
        0,
        "video.mp4",
        "job-d00-e00",
        video_layout=layout,
    )

    assert rendered_layouts == [layout]
    assert uploaded_ass == ["ass-from-shared-layout"]
    assert items[0]["translations"]["pt"]["status"] == "succeeded"
