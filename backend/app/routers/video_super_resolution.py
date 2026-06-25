import json
import re
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session, get_settings, require_passphrase
from app.models import VideoSuperResolutionJob
from app.schemas import (
    SuperResJobCreateRequest,
    SuperResJobItemOut,
    SuperResJobOut,
    SuperResJobSummary,
    SuperResUploadEntry,
    SuperResUploadUrlRequest,
    SuperResUploadUrlResponse,
)
from app.services.aliyun_oss_client import AliyunOSSClient
from app.services.video_super_resolution_runner import run_video_super_resolution_job

RETRY_FIELDS = (
    "viapi_job_id",
    "viapi_status",
    "raw_output_url",
    "output_oss_uri",
    "output_public_url",
    "error",
)


router = APIRouter(prefix="/super-resolution", tags=["super-resolution"])

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(name: str) -> str:
    base = name.strip().replace("\\", "/").split("/")[-1] or "video"
    return _SAFE_NAME.sub("_", base)


def _items_counts(items: list[dict]) -> tuple[int, int]:
    succeeded = sum(1 for it in items if it.get("status") == "succeeded")
    failed = sum(1 for it in items if it.get("status") == "failed")
    return succeeded, failed


def _job_to_out(job: VideoSuperResolutionJob) -> SuperResJobOut:
    try:
        items = json.loads(job.items_json or "[]")
    except Exception:
        items = []
    try:
        filenames = (
            json.loads(job.original_filenames_json) if job.original_filenames_json else None
        )
    except Exception:
        filenames = None
    succeeded, failed = _items_counts(items)
    items_out: list[SuperResJobItemOut] = []
    for it in items:
        items_out.append(
            SuperResJobItemOut(
                index=it.get("index", 0),
                filename=it.get("filename", ""),
                input_oss_uri=it.get("input_oss_uri", ""),
                input_public_url=it.get("input_public_url", ""),
                viapi_job_id=it.get("viapi_job_id"),
                viapi_status=it.get("viapi_status"),
                raw_output_url=it.get("raw_output_url"),
                output_oss_uri=it.get("output_oss_uri"),
                output_public_url=it.get("output_public_url"),
                status=it.get("status", "pending"),
                error=it.get("error"),
            )
        )
    return SuperResJobOut(
        id=job.id,
        title=job.title,
        video_count=job.video_count,
        bit_rate=job.bit_rate,
        items=items_out,
        original_filenames=filenames,
        output_oss_prefix=job.output_oss_prefix,
        status=job.status,
        progress_message=job.progress_message,
        error_message=job.error_message,
        succeeded_count=succeeded,
        failed_count=failed,
        submitted_at=job.submitted_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _job_to_summary(job: VideoSuperResolutionJob) -> SuperResJobSummary:
    try:
        items = json.loads(job.items_json or "[]")
    except Exception:
        items = []
    succeeded, failed = _items_counts(items)
    return SuperResJobSummary(
        id=job.id,
        title=job.title,
        video_count=job.video_count,
        bit_rate=job.bit_rate,
        status=job.status,
        succeeded_count=succeeded,
        failed_count=failed,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post(
    "/upload-url",
    response_model=SuperResUploadUrlResponse,
    dependencies=[Depends(require_passphrase)],
)
async def create_upload_urls(
    payload: SuperResUploadUrlRequest,
    settings=Depends(get_settings),
) -> SuperResUploadUrlResponse:
    if not payload.files:
        raise HTTPException(status_code=400, detail="文件列表不能为空")
    try:
        oss = AliyunOSSClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job_id = str(uuid.uuid4())
    expires_in = 3600
    entries: list[SuperResUploadEntry] = []
    prefix = settings.oss_super_res_upload_prefix.rstrip("/") or "super-resolution-input"
    for index, spec in enumerate(payload.files):
        safe = _safe_filename(spec.filename)
        key = f"{prefix}/{job_id}/{index:02d}-{safe}"
        result = oss.presign_put(key, content_type=spec.content_type, expires_in=expires_in)
        entries.append(
            SuperResUploadEntry(
                filename=spec.filename,
                presigned_url=result.presigned_url,
                public_url=result.public_url,
                oss_uri=result.oss_uri,
                key=result.key,
            )
        )
    return SuperResUploadUrlResponse(job_id=job_id, expires_in=expires_in, entries=entries)


@router.post(
    "",
    response_model=SuperResJobOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_passphrase)],
)
async def create_super_resolution_job(
    payload: SuperResJobCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> SuperResJobOut:
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    if not payload.items:
        raise HTTPException(status_code=400, detail="视频列表不能为空")
    if not (1 <= payload.bit_rate <= 20):
        raise HTTPException(status_code=400, detail="bit_rate 必须在 1-20 之间")
    for it in payload.items:
        if not it.oss_uri.startswith("oss://"):
            raise HTTPException(status_code=400, detail=f"非法的视频 oss_uri: {it.oss_uri}")

    existing = await session.get(VideoSuperResolutionJob, payload.job_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="job_id 已存在")

    output_prefix = (
        f"oss://{settings.aliyun_oss_bucket}/"
        f"{settings.oss_super_res_output_prefix.strip('/') or 'super-resolution-output'}/"
        f"{payload.job_id}/"
    )

    items: list[dict] = []
    for index, spec in enumerate(payload.items):
        items.append(
            {
                "index": index,
                "filename": spec.filename,
                "input_oss_uri": spec.oss_uri,
                "input_public_url": spec.public_url,
                "viapi_job_id": None,
                "viapi_status": None,
                "raw_output_url": None,
                "output_oss_uri": None,
                "output_public_url": None,
                "status": "pending",
                "error": None,
            }
        )

    job = VideoSuperResolutionJob(
        id=payload.job_id,
        title=title,
        video_count=len(payload.items),
        bit_rate=payload.bit_rate,
        items_json=json.dumps(items, ensure_ascii=False),
        original_filenames_json=(
            json.dumps(payload.original_filenames, ensure_ascii=False)
            if payload.original_filenames
            else None
        ),
        output_oss_prefix=output_prefix,
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    state = request.app.state

    async def _runner() -> None:
        await run_video_super_resolution_job(state.db, state.settings, job.id)

    background_tasks.add_task(_runner)
    return _job_to_out(job)


@router.get("/{job_id}", response_model=SuperResJobOut)
async def get_super_resolution_job(
    job_id: str, session: AsyncSession = Depends(get_session)
) -> SuperResJobOut:
    job = await session.get(VideoSuperResolutionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _job_to_out(job)


@router.post(
    "/{job_id}/retry",
    response_model=SuperResJobOut,
    dependencies=[Depends(require_passphrase)],
)
async def retry_failed_items(
    job_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> SuperResJobOut:
    """重试 job 中 status=failed 的 item。succeeded 的保留不动。"""

    job = await session.get(VideoSuperResolutionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    items: list[dict] = json.loads(job.items_json or "[]")
    failed_indices = [i for i, it in enumerate(items) if it.get("status") == "failed"]
    if not failed_indices:
        raise HTTPException(status_code=400, detail="没有可重试的失败项")

    for idx in failed_indices:
        items[idx]["status"] = "pending"
        for f in RETRY_FIELDS:
            items[idx][f] = None
    job.items_json = json.dumps(items, ensure_ascii=False)
    job.status = "running"
    job.error_message = None
    job.completed_at = None
    await session.commit()
    await session.refresh(job)

    state = request.app.state

    async def _runner() -> None:
        await run_video_super_resolution_job(
            state.db, state.settings, job.id, only_indices=failed_indices
        )

    background_tasks.add_task(_runner)
    return _job_to_out(job)


@router.get("", response_model=list[SuperResJobSummary])
async def list_super_resolution_jobs(
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> list[SuperResJobSummary]:
    rows = await session.scalars(
        select(VideoSuperResolutionJob)
        .order_by(VideoSuperResolutionJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_job_to_summary(j) for j in rows]
