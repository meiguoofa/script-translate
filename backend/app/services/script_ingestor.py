from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Script, ScriptLine
from app.services.dialogue_extractor import extract_script_lines
from app.services.lang_detect import detect_language
from app.services.script_parser import parse_text_content


@dataclass
class IngestedScript:
    script_id: str
    title: str
    line_count: int
    source_lang: str | None


async def ingest_text_into_script(
    session: AsyncSession,
    *,
    title: str,
    raw_text: str,
    source_type: str = "video_restore",
    raw_file_path: str | None = None,
    script_id: str | None = None,
) -> IngestedScript:
    """Normalize text, extract lines, and persist `Script` + `ScriptLine` rows.

    Caller is responsible for committing the surrounding transaction.
    """

    sid = script_id or str(uuid.uuid4())
    normalized_text = parse_text_content(raw_text or "")
    extracted_lines = extract_script_lines(normalized_text)

    script = Script(
        id=sid,
        title=title,
        source_lang=detect_language(normalized_text),
        source_type=source_type,
        raw_text=normalized_text,
        raw_file_path=raw_file_path,
    )
    session.add(script)

    for line in extracted_lines:
        session.add(
            ScriptLine(
                id=str(uuid.uuid4()),
                script_id=sid,
                line_no=line.line_no,
                raw_line=line.raw_line,
                speaker=line.speaker,
                parenthetical=line.parenthetical,
                dialogue=line.dialogue,
                is_dialogue=line.is_dialogue,
            )
        )

    return IngestedScript(
        script_id=sid,
        title=title,
        line_count=len(extracted_lines),
        source_lang=script.source_lang,
    )
