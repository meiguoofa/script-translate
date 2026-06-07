import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.deps import get_session, get_settings
from app.models import Script, ScriptLine, TranslationVersion
from app.schemas import ScriptCreateResponse, ScriptDetail, ScriptLineOut, ScriptSummary, TranslationVersionSummary
from app.services.dialogue_extractor import extract_script_lines
from app.services.lang_detect import detect_language
from app.services.script_parser import parse_text_content, parse_uploaded_file


router = APIRouter(prefix="/scripts", tags=["scripts"])


@router.post("", response_model=ScriptCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_script(
    title: str = Form(...),
    raw_text: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> ScriptCreateResponse:
    if not raw_text and not file:
        raise HTTPException(status_code=400, detail="Provide raw_text or a document upload.")
    if raw_text and file:
        raise HTTPException(status_code=400, detail="Provide either raw_text or file, not both.")

    script_id = str(uuid.uuid4())
    source_type = "paste"
    raw_file_path: str | None = None

    if file:
        uploads_path = settings.uploads_path / script_id
        uploads_path.mkdir(parents=True, exist_ok=True)
        destination = uploads_path / file.filename
        destination.write_bytes(await file.read())
        raw_text = parse_uploaded_file(destination)
        raw_file_path = str(destination.relative_to(settings.storage_path))
        suffix = Path(file.filename).suffix.lower()
        if suffix == ".docx":
            source_type = "upload_docx"
        elif suffix == ".doc":
            source_type = "upload_doc"
        else:
            source_type = "upload_txt"
    else:
        raw_text = parse_text_content(raw_text or "")

    normalized_text = parse_text_content(raw_text)
    extracted_lines = extract_script_lines(normalized_text)
    script = Script(
        id=script_id,
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
                script_id=script_id,
                line_no=line.line_no,
                raw_line=line.raw_line,
                speaker=line.speaker,
                parenthetical=line.parenthetical,
                dialogue=line.dialogue,
                is_dialogue=line.is_dialogue,
            )
        )

    await session.commit()
    return ScriptCreateResponse(
        script_id=script.id,
        title=script.title,
        line_count=len(extracted_lines),
        source_lang=script.source_lang,
    )


@router.get("", response_model=list[ScriptSummary])
async def list_scripts(
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> list[ScriptSummary]:
    rows = await session.execute(
        select(
            Script.id,
            Script.title,
            Script.source_lang,
            Script.source_type,
            Script.created_at,
            func.count(TranslationVersion.id).label("version_count"),
        )
        .outerjoin(TranslationVersion, TranslationVersion.script_id == Script.id)
        .group_by(Script.id)
        .order_by(Script.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [ScriptSummary(**row._mapping) for row in rows]


@router.get("/{script_id}", response_model=ScriptDetail)
async def get_script(script_id: str, session: AsyncSession = Depends(get_session)) -> ScriptDetail:
    script = await session.scalar(select(Script).where(Script.id == script_id).options(selectinload(Script.lines)))
    if script is None:
        raise HTTPException(status_code=404, detail="Script not found.")

    return ScriptDetail(
        id=script.id,
        title=script.title,
        source_lang=script.source_lang,
        source_type=script.source_type,
        created_at=script.created_at,
        lines=[ScriptLineOut.model_validate(line, from_attributes=True) for line in sorted(script.lines, key=lambda item: item.line_no)],
    )


@router.get("/{script_id}/versions", response_model=list[TranslationVersionSummary])
async def list_versions(script_id: str, session: AsyncSession = Depends(get_session)) -> list[TranslationVersionSummary]:
    versions = await session.scalars(
        select(TranslationVersion)
        .where(TranslationVersion.script_id == script_id)
        .order_by(TranslationVersion.created_at.desc())
    )
    return [TranslationVersionSummary.model_validate(version, from_attributes=True) for version in versions]
