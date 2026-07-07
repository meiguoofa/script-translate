from __future__ import annotations

import asyncio
import logging
import math

from app.llm.base import TranslationBatchLine
from app.llm.registry import ProviderRegistry
from app.services.srt_utils import SrtEntry, build_srt, parse_srt

logger = logging.getLogger("subtitle_translator")


async def translate_srt(
    srt_text: str,
    *,
    registry: ProviderRegistry,
    model_provider: str,
    model_name: str,
    target_lang: str,
    batch_size: int,
) -> str:
    """翻译 SRT 文本，保留时间轴。返回新的 SRT 文本。

    所有 batch 并发提交（asyncio.gather），由 provider 侧的 httpx 连接池 / 远端 QPS 自然限流。
    """
    entries = parse_srt(srt_text)
    if not entries:
        return srt_text

    provider = registry.get_provider(model_provider)

    batch_count = max(1, math.ceil(len(entries) / batch_size))

    async def _translate_one(batch_index: int) -> list[tuple[int, str]]:
        start = batch_index * batch_size
        end = start + batch_size
        batch = entries[start:end]
        batch_lines = [
            TranslationBatchLine(
                label=f"L{offset:04d}", line_id=str(e.index), text=e.text
            )
            for offset, e in enumerate(batch, start=1)
        ]
        result = await provider.translate_batch(
            model=model_name,
            target_lang=target_lang,
            context="",
            lines=batch_lines,
        )
        return [
            (e.index, result.translations.get(bl.label, e.text))
            for bl, e in zip(batch_lines, batch)
        ]

    batch_results = await asyncio.gather(
        *(_translate_one(i) for i in range(batch_count))
    )
    translation_by_index: dict[int, str] = {}
    for mapped in batch_results:
        for idx, text in mapped:
            translation_by_index[idx] = text

    new_entries = [
        SrtEntry(
            index=e.index,
            start_ms=e.start_ms,
            end_ms=e.end_ms,
            text=translation_by_index.get(e.index, e.text),
        )
        for e in entries
    ]
    return build_srt(new_entries)
