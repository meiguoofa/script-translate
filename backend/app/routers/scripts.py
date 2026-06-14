import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.deps import get_session, get_settings
from app.models import Script, ScriptLine, TranslationVersion
from app.schemas import ScriptCreateResponse, ScriptDetail, ScriptLineOut, ScriptSummary, TranslationVersionSummary
from app.services.script_ingestor import ingest_text_into_script
from app.services.uploaded_documents import parse_saved_document, save_uploaded_document


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
        saved_upload = await save_uploaded_document(file, script_id, settings)
        raw_text = parse_saved_document(saved_upload.absolute_path)
        raw_file_path = str(saved_upload.relative_path)
        source_type = saved_upload.source_type

    ingested = await ingest_text_into_script(
        session,
        title=title,
        raw_text=raw_text or "",
        source_type=source_type,
        raw_file_path=raw_file_path,
        script_id=script_id,
    )
    await session.commit()
    return ScriptCreateResponse(
        script_id=ingested.script_id,
        title=ingested.title,
        line_count=ingested.line_count,
        source_lang=ingested.source_lang,
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
