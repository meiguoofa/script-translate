from __future__ import annotations

from app.services.srt_utils import SrtEntry, build_srt, parse_srt


def clean_srt(srt_text: str) -> str:
    """极简 SRT 清洗：

    - 修剪每条字幕首尾空白
    - 合并相邻"文本完全相同 + 时间轴连续"的字幕
    - 跳过空文本字幕

    OCR 错字修正/水印识别/广告词删除不在 v1 范围。
    """

    entries = parse_srt(srt_text)
    if not entries:
        return srt_text

    cleaned: list[SrtEntry] = []
    for entry in entries:
        text = entry.text.strip()
        if not text:
            continue
        if cleaned:
            prev = cleaned[-1]
            if prev.text == text and prev.end_ms >= entry.start_ms - 1:
                # 时间相邻 + 文本相同 → 合并
                prev.end_ms = max(prev.end_ms, entry.end_ms)
                continue
        cleaned.append(
            SrtEntry(index=0, start_ms=entry.start_ms, end_ms=entry.end_ms, text=text)
        )

    for i, e in enumerate(cleaned, start=1):
        e.index = i
    return build_srt(cleaned)
