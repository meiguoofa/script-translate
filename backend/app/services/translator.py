import math
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.llm.base import TranslationBatchLine
from app.llm.registry import ProviderRegistry
from app.models import Script, ScriptLine, TranslationLine, TranslationVersion
from app.services.cost_estimator import estimate_cost_rmb, estimate_tokens


@dataclass(slots=True)
class TranslationContext:
    settings: Settings
    registry: ProviderRegistry


def build_rendered_line(line: ScriptLine, translated_dialogue: str | None) -> str:
    if line.is_dialogue and translated_dialogue:
        return f"{line.raw_line}({translated_dialogue})"
    return line.raw_line


def build_batch_context(lines: list[ScriptLine], start: int, end: int) -> str:
    lower = max(0, start - 2)
    upper = min(len(lines), end + 2)
    context_lines = [line.raw_line for line in lines[lower:upper] if not line.is_dialogue and line.raw_line]
    return "\n".join(context_lines[:6])


async def run_translation(session: AsyncSession, version_id: str, context: TranslationContext) -> None:
    started_at = time.perf_counter()
    version = await session.scalar(
        select(TranslationVersion)
        .where(TranslationVersion.id == version_id)
        .options(selectinload(TranslationVersion.script).selectinload(Script.lines))
    )
    if version is None or version.script is None:
        return

    provider = context.registry.get_provider(version.model_provider)
    script_lines = sorted(version.script.lines, key=lambda line: line.line_no)
    dialogue_lines = [line for line in script_lines if line.is_dialogue and line.dialogue]

    try:
        translation_map: dict[str, str] = {}
        total_tokens = 0
        batch_count = max(1, math.ceil(len(dialogue_lines) / context.settings.batch_size))

        for batch_index in range(batch_count):
            start = batch_index * context.settings.batch_size
            end = start + context.settings.batch_size
            batch = dialogue_lines[start:end]
            batch_lines = [
                TranslationBatchLine(label=f"L{offset:03d}", line_id=line.id, text=line.dialogue or "")
                for offset, line in enumerate(batch, start=1)
            ]
            batch_context = build_batch_context(script_lines, start, end)
            result = await provider.translate_batch(
                model=version.model_name,
                target_lang=version.target_lang,
                context=batch_context,
                lines=batch_lines,
            )
            total_tokens += result.total_tokens or 0

            for input_line in batch_lines:
                translated = result.translations.get(input_line.label)
                if translated is None:
                    translated = input_line.text
                translation_map[input_line.line_id] = translated

        await session.execute(delete(TranslationLine).where(TranslationLine.version_id == version_id))
        for line in script_lines:
            translated_dialogue = translation_map.get(line.id)
            session.add(
                TranslationLine(
                    id=str(uuid.uuid4()),
                    version_id=version.id,
                    line_id=line.id,
                    translated_dialogue=translated_dialogue,
                    rendered_line=build_rendered_line(line, translated_dialogue),
                )
            )

        version.total_tokens = total_tokens or estimate_tokens(version.script.raw_text)
        version.cost = estimate_cost_rmb(version.total_tokens)
        version.duration_ms = int((time.perf_counter() - started_at) * 1000)
        version.status = "done"
        version.error_message = None
        await session.commit()
    except Exception as exc:
        version.status = "failed"
        version.error_message = str(exc)
        version.duration_ms = int((time.perf_counter() - started_at) * 1000)
        await session.commit()
