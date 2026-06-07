import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.deps import get_session, get_settings
from app.models import GeneratedDoc, Script, TranslationLine, TranslationVersion
from app.services.doc_generator import generate_docx


router = APIRouter(prefix="/translations", tags=["downloads"])


@router.get("/{version_id}/download")
async def download_translation(version_id: str, session: AsyncSession = Depends(get_session), settings=Depends(get_settings)):
    version = await session.scalar(
        select(TranslationVersion)
        .where(TranslationVersion.id == version_id)
        .options(
            selectinload(TranslationVersion.lines).selectinload(TranslationLine.line),
            selectinload(TranslationVersion.generated_docs),
            selectinload(TranslationVersion.script).selectinload(Script.lines),
        )
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Translation version not found.")
    if version.status != "done":
        raise HTTPException(status_code=409, detail="Translation is not ready for download.")

    title_slug = version.script.title.replace(" ", "-")
    existing_doc = version.generated_docs[0] if version.generated_docs else None
    filename = existing_doc.filename if existing_doc else f"{title_slug}-{version.target_lang}-{version.model_provider}.docx"
    relative_path = Path(existing_doc.file_path) if existing_doc else Path("generated") / version.id / filename
    absolute_path = settings.storage_path / relative_path
    generate_docx(
        [line.rendered_line for line in sorted(version.lines, key=lambda item: item.line.line_no if item.line else 0)],
        absolute_path,
    )

    if existing_doc is None:
        generated = GeneratedDoc(
            id=str(uuid.uuid4()),
            version_id=version.id,
            file_path=str(relative_path),
            filename=filename,
        )
        session.add(generated)
        await session.commit()
    return FileResponse(absolute_path, filename=filename)
