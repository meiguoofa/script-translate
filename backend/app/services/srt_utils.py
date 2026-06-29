from __future__ import annotations

import re
from dataclasses import dataclass

_SRT_TIME = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


@dataclass(slots=True)
class SrtEntry:
    index: int
    start_ms: int
    end_ms: int
    text: str


def _to_ms(h: str, m: str, s: str, frac: str) -> int:
    return (
        int(h) * 3600_000
        + int(m) * 60_000
        + int(s) * 1000
        + int(frac.ljust(3, "0")[:3])
    )


def _from_ms(ms: int) -> str:
    if ms < 0:
        ms = 0
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(text: str) -> list[SrtEntry]:
    """解析 SRT 文本。容忍 BOM、空行、缺索引行。"""
    if not text:
        return []
    text = text.lstrip("﻿")
    blocks = re.split(r"\r?\n\r?\n+", text.strip())
    entries: list[SrtEntry] = []
    for idx, block in enumerate(blocks, start=1):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        # 第一行可能是索引号；找到第一行匹配时间轴的行
        time_line_idx = None
        for i, ln in enumerate(lines):
            if _SRT_TIME.search(ln):
                time_line_idx = i
                break
        if time_line_idx is None:
            continue
        m = _SRT_TIME.search(lines[time_line_idx])
        start_ms = _to_ms(m.group(1), m.group(2), m.group(3), m.group(4))
        end_ms = _to_ms(m.group(5), m.group(6), m.group(7), m.group(8))
        body = "\n".join(lines[time_line_idx + 1 :]).strip()
        entries.append(SrtEntry(index=idx, start_ms=start_ms, end_ms=end_ms, text=body))
    return entries


def build_srt(entries: list[SrtEntry]) -> str:
    parts: list[str] = []
    for i, e in enumerate(entries, start=1):
        parts.append(
            f"{i}\n{_from_ms(e.start_ms)} --> {_from_ms(e.end_ms)}\n{e.text}\n"
        )
    return "\n".join(parts)


def _to_ass_time(ms: int) -> str:
    if ms < 0:
        ms = 0
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, cs = divmod(ms, 1000)
    cs = cs // 10
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _escape_ass_text(text: str) -> str:
    if not text:
        return ""
    return (
        text.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", "\\N")
    )


def _safe_area_height(video_h: int) -> int:
    return max(120, video_h // 10)


def srt_to_ass(
    entries: list[SrtEntry],
    *,
    video_w: int,
    video_h: int,
    placement_mode: str = "safe_bottom",
) -> str:
    """把 SRT entries 转成 ASS 字幕。

    safe_bottom: 字幕放在底部安全区中线（搭配 FFmpeg scale+pad 黑边使用）。
    simple_bottom: 字幕直接放在距底部 60px 的位置。
    """
    font_size = max(28, video_h // 30)
    outline = max(2, video_h // 500)
    margin_v = max(40, video_h // 18)

    if placement_mode == "safe_bottom":
        sa = _safe_area_height(video_h)
        # 安全区中线 y：黑边在底部，中线 = video_h - sa/2
        pos_y = video_h - sa // 2
        # MarginV 在 ASS 里用不到（我们用 \pos），保持一个合理值
        margin_v = max(20, sa // 4)
    else:  # simple_bottom
        pos_y = video_h - 60

    pos_x = video_w // 2

    lines: list[str] = []
    lines.append("[Script Info]")
    lines.append("ScriptType: v4.00+")
    lines.append(f"PlayResX: {video_w}")
    lines.append(f"PlayResY: {video_h}")
    lines.append("")
    lines.append("[V4+ Styles]")
    lines.append(
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    )
    lines.append(
        f"Style: Default,Noto Sans CJK SC,{font_size},&H00FFFFFF,&H00000000,&H66000000,"
        f"0,0,0,0,100,100,0,0,1,{outline},0,2,20,20,{margin_v},1"
    )
    lines.append("")
    lines.append("[Events]")
    lines.append(
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    )
    for e in entries:
        text = _escape_ass_text(e.text)
        lines.append(
            f"Dialogue: 0,{_to_ass_time(e.start_ms)},{_to_ass_time(e.end_ms)},"
            f"Default,,0,0,0,,{{\\an2\\pos({pos_x},{pos_y})}}{text}"
        )
    return "\n".join(lines) + "\n"


def safe_area_height(video_h: int) -> int:
    """FFmpeg scale+pad 计算用：底部安全区像素高度。"""
    return _safe_area_height(video_h)
