import json
import re
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session, get_settings, require_passphrase
from app.models import PromptTemplate, VideoScriptJob
from app.schemas import (
    VideoJobCreateRequest,
    VideoJobOut,
    VideoJobSummary,
    VideoUploadEntry,
    VideoUploadUrlRequest,
    VideoUploadUrlResponse,
)
from app.services.tos_client import TOSClient
from app.services.video_script_runner import run_video_script_job


router = APIRouter(prefix="/video-jobs", tags=["video-jobs"])


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(name: str) -> str:
    base = name.strip().replace("\\", "/").split("/")[-1]
    if not base:
        base = "video"
    return _SAFE_NAME.sub("_", base)


def _job_to_out(job: VideoScriptJob) -> VideoJobOut:
    try:
        urls = json.loads(job.video_urls_json) if job.video_urls_json else []
    except Exception:
        urls = []
    try:
        filenames = (
            json.loads(job.original_filenames_json) if job.original_filenames_json else None
        )
    except Exception:
        filenames = None
    preview = None
    if job.generated_script_text:
        lines = [ln for ln in job.generated_script_text.splitlines() if ln.strip()]
        preview = lines[:80]
    return VideoJobOut(
        id=job.id,
        title=job.title,
        video_count=job.video_count,
        video_urls=urls,
        original_filenames=filenames,
        prompt_template_id=job.prompt_template_id,
        prompt_template_name=job.prompt_template_name,
        output_tos_path=job.output_tos_path,
        las_task_id=job.las_task_id,
        status=job.status,
        progress_message=job.progress_message,
        error_message=job.error_message,
        generated_script_id=job.generated_script_id,
        generated_script_preview=preview,
        submitted_at=job.submitted_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _job_to_summary(job: VideoScriptJob) -> VideoJobSummary:
    return VideoJobSummary(
        id=job.id,
        title=job.title,
        video_count=job.video_count,
        prompt_template_name=job.prompt_template_name,
        status=job.status,
        generated_script_id=job.generated_script_id,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post(
    "/upload-url",
    response_model=VideoUploadUrlResponse,
    dependencies=[Depends(require_passphrase)],
)
async def create_upload_urls(
    payload: VideoUploadUrlRequest,
    settings=Depends(get_settings),
) -> VideoUploadUrlResponse:
    if not payload.files:
        raise HTTPException(status_code=400, detail="文件列表不能为空")
    try:
        tos = TOSClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job_id = str(uuid.uuid4())
    expires_in = 3600
    entries: list[VideoUploadEntry] = []
    prefix = settings.tos_upload_prefix.rstrip("/") or "uploads"
    for index, spec in enumerate(payload.files):
        safe = _safe_filename(spec.filename)
        key = f"{prefix}/{job_id}/{index:02d}-{safe}"
        result = tos.presign_put(key, content_type=spec.content_type, expires_in=expires_in)
        entries.append(
            VideoUploadEntry(
                filename=spec.filename,
                presigned_url=result.presigned_url,
                public_url=result.public_url,
                tos_uri=result.tos_uri,
                key=result.key,
            )
        )
    return VideoUploadUrlResponse(job_id=job_id, expires_in=expires_in, entries=entries)


@router.post(
    "",
    response_model=VideoJobOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_passphrase)],
)
async def create_video_job(
    payload: VideoJobCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> VideoJobOut:
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    if not payload.video_urls:
        raise HTTPException(status_code=400, detail="视频 URL 列表不能为空")
    for url in payload.video_urls:
        if not url.startswith("tos://"):
            raise HTTPException(status_code=400, detail=f"非法的视频 URL: {url}")

    template = await session.get(PromptTemplate, payload.prompt_template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="提示词不存在")

    existing = await session.get(VideoScriptJob, payload.job_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="job_id 已存在")

    output_tos_path = (
        f"tos://{settings.tos_bucket}/"
        f"{settings.tos_output_prefix.strip('/') or 'output'}/{payload.job_id}"
    )
    job = VideoScriptJob(
        id=payload.job_id,
        title=title,
        video_count=len(payload.video_urls),
        video_urls_json=json.dumps(payload.video_urls, ensure_ascii=False),
        original_filenames_json=(
            json.dumps(payload.original_filenames, ensure_ascii=False)
            if payload.original_filenames
            else None
        ),
        prompt_template_id=template.id,
        prompt_template_name=template.name,
        custom_script_prompt=template.content,
        output_tos_path=output_tos_path,
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    state = request.app.state

    async def _runner() -> None:
        await run_video_script_job(state.db, state.settings, job.id)

    background_tasks.add_task(_runner)
    return _job_to_out(job)


@router.post(
    "/{job_id}/retry",
    response_model=VideoJobOut,
    dependencies=[Depends(require_passphrase)],
)
async def retry_video_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> VideoJobOut:
    """重置 failed 任务状态后重跑。复用同一 job_id、视频 URL、提示词、output_tos_path。"""

    job = await session.get(VideoScriptJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status != "failed":
        raise HTTPException(
            status_code=400,
            detail=f"只有失败的任务才能重试（当前: {job.status}）",
        )

    job.status = "pending"
    job.error_message = None
    job.progress_message = None
    job.las_task_id = None
    job.submitted_at = None
    job.completed_at = None
    job.generated_script_text = None
    job.generated_script_id = None
    await session.commit()
    await session.refresh(job)

    state = request.app.state

    async def _runner() -> None:
        await run_video_script_job(state.db, state.settings, job.id)

    background_tasks.add_task(_runner)
    return _job_to_out(job)


@router.get("/{job_id}", response_model=VideoJobOut)
async def get_video_job(job_id: str, session: AsyncSession = Depends(get_session)) -> VideoJobOut:
    job = await session.get(VideoScriptJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _job_to_out(job)


@router.get("", response_model=list[VideoJobSummary])
async def list_video_jobs(
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> list[VideoJobSummary]:
    rows = await session.scalars(
        select(VideoScriptJob)
        .order_by(VideoScriptJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_job_to_summary(j) for j in rows]
