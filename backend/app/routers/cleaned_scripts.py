import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session, get_settings
from app.models import CleanedScriptJob
from app.schemas import CleanedScriptCreateResponse, CleanedScriptDetail, CleanedScriptSummary
from app.services.doc_generator import generate_docx
from app.services.script_parser import parse_text_content
from app.services.translation_stripper import strip_translations_from_text
from app.services.uploaded_documents import parse_saved_document, save_uploaded_document

router = APIRouter(prefix="/cleaned-scripts", tags=["cleaned-scripts"])


def _title_slug(title: str) -> str:
    slug = title.strip().replace(" ", "-")
    return slug or "cleaned-script"


def _summary(job: CleanedScriptJob) -> CleanedScriptSummary:
    return CleanedScriptSummary.model_validate(job, from_attributes=True)


@router.post("", response_model=CleanedScriptCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_cleaned_script(
    title: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> CleanedScriptCreateResponse:
    job_id = str(uuid.uuid4())
    saved_upload = await save_uploaded_document(file, job_id, settings)
    original_text = parse_text_content(parse_saved_document(saved_upload.absolute_path))
    strip_result = strip_translations_from_text(original_text)

    output_filename = f"{_title_slug(title)}-clean.docx"
    relative_output_path = Path("generated") / "cleaned" / job_id / output_filename
    absolute_output_path = settings.storage_path / relative_output_path
    generate_docx(strip_result.cleaned_text.split("\n"), absolute_output_path)

    job = CleanedScriptJob(
        id=job_id,
        title=title,
        source_filename=saved_upload.filename,
        source_file_path=str(saved_upload.relative_path),
        source_type=saved_upload.source_type,
        original_text=original_text,
        cleaned_text=strip_result.cleaned_text,
        line_count=strip_result.line_count,
        stripped_count=strip_result.stripped_count,
        output_file_path=str(relative_output_path),
        output_filename=output_filename,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    return CleanedScriptCreateResponse.model_validate(job, from_attributes=True)


@router.get("", response_model=list[CleanedScriptSummary])
async def list_cleaned_scripts(
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> list[CleanedScriptSummary]:
    jobs = await session.scalars(
        select(CleanedScriptJob)
        .order_by(CleanedScriptJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_summary(job) for job in jobs]


@router.get("/{job_id}", response_model=CleanedScriptDetail)
async def get_cleaned_script(job_id: str, session: AsyncSession = Depends(get_session)) -> CleanedScriptDetail:
    job = await session.get(CleanedScriptJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Cleaned script not found.")

    summary = _summary(job).model_dump()
    return CleanedScriptDetail(**summary, cleaned_preview=job.cleaned_text.split("\n")[:80])


@router.get("/{job_id}/download")
async def download_cleaned_script(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
):
    job = await session.get(CleanedScriptJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Cleaned script not found.")

    relative_path = Path(job.output_file_path) if job.output_file_path else Path("generated") / "cleaned" / job.id / job.output_filename
    absolute_path = settings.storage_path / relative_path
    if not absolute_path.exists():
        generate_docx(job.cleaned_text.split("\n"), absolute_path)
        job.output_file_path = str(relative_path)
        session.add(job)
        await session.commit()

    return FileResponse(absolute_path, filename=job.output_filename)
