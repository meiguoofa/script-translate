from __future__ import annotations

from typing import Any

ADAPTIVE_STYLE_MODE = "adaptive_v1"
_FE_CANVAS_WIDTH = 1080
_FE_CANVAS_HEIGHT = 1920
_SINGLE_LANGUAGE_FONT_SIZE = 77
_BILINGUAL_FONT_SIZE = 67


def adaptive_fe_canvas() -> dict[str, int]:
    return {"Width": _FE_CANVAS_WIDTH, "Height": _FE_CANVAS_HEIGHT}


def build_adaptive_subtitle_config(
    *,
    bilingual: bool,
    subtitle_enabled: bool = True,
    font_color: str,
    font_color_opacity: float,
    subtitle_y: float,
) -> dict[str, Any]:
    return {
        "Type": "Text",
        "FontSize": (
            (_BILINGUAL_FONT_SIZE if bilingual else _SINGLE_LANGUAGE_FONT_SIZE)
            if subtitle_enabled
            else 0
        ),
        "FontColor": font_color,
        "FontColorOpacity": font_color_opacity,
        "X": 0.5,
        "Y": subtitle_y,
        "TextWidth": 0.9,
        "AdaptMode": "AutoWrap",
        "SizeRequestType": "RealDim",
        "Alignment": "Center",
        "BorderStyle": 1,
        "Outline": 2,
    }
