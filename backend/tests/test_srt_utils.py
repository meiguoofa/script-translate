from __future__ import annotations

from app.services.srt_utils import SrtEntry, _wrap_text_to_lines, srt_to_ass


def test_wrap_text_prefers_english_word_boundaries() -> None:
    text = "She told me to get lost just for questioning the scale."

    lines = _wrap_text_to_lines(
        text,
        max_width=300,
        font_size=43,
        max_lines=10,
    )

    assert lines == [
        "She told me",
        "to get lost",
        "just for",
        "questioning",
        "the scale.",
    ]


def test_wrap_text_keeps_character_fallback_for_cjk() -> None:
    lines = _wrap_text_to_lines(
        "这是一个测试字幕",
        max_width=80,
        font_size=40,
        max_lines=10,
    )

    assert lines == ["这是", "一个", "测试", "字幕"]


def test_srt_to_ass_uses_effective_content_bounds() -> None:
    entries = [
        SrtEntry(
            index=1,
            start_ms=0,
            end_ms=2000,
            text="She told me to get lost just for questioning the scale.",
        )
    ]

    ass = srt_to_ass(
        entries,
        video_w=1920,
        video_h=1080,
        font_size_pct=4,
        pos_x_ratio=0.5,
        text_width_ratio=0.9,
        content_x_px=656,
        content_width_px=608,
    )

    assert (
        "Style: Default,Noto Sans CJK SC,43,&H00FFFFFF,&H00000000,&H66000000,"
        "0,0,0,0,100,100,0,0,1,2,0,2,686,686,"
    ) in ass
    assert r"{\an2\pos(960," in ass
    assert r"\N" in next(
        line for line in ass.splitlines() if line.startswith("Dialogue:")
    )


def test_srt_to_ass_positions_relative_to_offset_content() -> None:
    ass = srt_to_ass(
        [SrtEntry(index=1, start_ms=0, end_ms=1000, text="Hello")],
        video_w=1920,
        video_h=1080,
        pos_x_ratio=0.25,
        content_x_px=120,
        content_width_px=600,
    )

    assert r"{\an2\pos(270," in ass
    assert (
        "Style: Default,Noto Sans CJK SC,36,&H00FFFFFF,&H00000000,&H66000000,"
        "0,0,0,0,100,100,0,0,1,2,0,2,149,1229,"
    ) in ass


def test_srt_to_ass_defaults_to_full_canvas_bounds() -> None:
    ass = srt_to_ass(
        [SrtEntry(index=1, start_ms=0, end_ms=1000, text="Hello")],
        video_w=1920,
        video_h=1080,
        pos_x_ratio=0.25,
    )

    assert r"{\an2\pos(480," in ass
    assert (
        "Style: Default,Noto Sans CJK SC,36,&H00FFFFFF,&H00000000,&H66000000,"
        "0,0,0,0,100,100,0,0,1,2,0,2,95,95,"
    ) in ass
