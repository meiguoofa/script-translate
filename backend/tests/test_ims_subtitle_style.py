from app.services.ims_subtitle_style import (
    ADAPTIVE_STYLE_MODE,
    adaptive_fe_canvas,
    build_adaptive_subtitle_config,
)


def test_builds_compact_single_language_adaptive_style() -> None:
    assert ADAPTIVE_STYLE_MODE == "adaptive_v1"
    assert adaptive_fe_canvas() == {"Width": 1080, "Height": 1920}
    assert build_adaptive_subtitle_config(
        bilingual=False,
        font_color="#FFFFFF",
        font_color_opacity=1,
        subtitle_y=0.76,
    ) == {
        "Type": "Text",
        "FontSize": 77,
        "FontColor": "#FFFFFF",
        "FontColorOpacity": 1,
        "X": 0.5,
        "Y": 0.76,
        "TextWidth": 0.9,
        "AdaptMode": "AutoWrap",
        "SizeRequestType": "RealDim",
        "Alignment": "Center",
        "BorderStyle": 1,
        "Outline": 2,
    }


def test_builds_smaller_bilingual_adaptive_style() -> None:
    style = build_adaptive_subtitle_config(
        bilingual=True,
        font_color="#12Ab34",
        font_color_opacity=0.8,
        subtitle_y=0.7,
    )

    assert style["FontSize"] == 67
    assert style["FontColor"] == "#12Ab34"
    assert style["FontColorOpacity"] == 0.8
    assert style["Y"] == 0.7


def test_hides_subtitles_with_zero_font_size() -> None:
    style = build_adaptive_subtitle_config(
        bilingual=False,
        subtitle_enabled=False,
        font_color="#FFFFFF",
        font_color_opacity=1,
        subtitle_y=0.76,
    )

    assert style["FontSize"] == 0
