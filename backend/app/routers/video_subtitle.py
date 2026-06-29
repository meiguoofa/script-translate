import json
import re
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session, get_settings, require_passphrase
from app.models import VideoSubtitleJob
from app.schemas import (
    SubtitleJobCreateRequest,
    SubtitleJobItemOut,
    SubtitleJobOut,
    SubtitleJobSummary,
    SubtitleUploadEntry,
    SubtitleUploadUrlRequest,
    SubtitleUploadUrlResponse,
)
from app.services.aliyun_oss_client import AliyunOSSClient
from app.services.tos_singapore_client import TOSSingaporeClient
from app.services.video_subtitle_runner import run_video_subtitle_job

RETRY_FIELDS = (
    "viapi_job_id",
    "viapi_status",
    "srt_tos_uri",
    "srt_tos_public_url",
    "srt_text",
    "translated_srt_tos_uri",
    "translated_srt_tos_public_url",
    "translated_srt_text",
    "output_video_tos_uri",
    "output_video_tos_public_url",
    "error",
)

router = APIRouter(prefix="/subtitle", tags=["subtitle"])

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(name: str) -> str:
    base = name.strip().replace("\\", "/").split("/")[-1] or "video"
    return _SAFE_NAME.sub("_", base)


def _items_counts(items: list[dict]) -> tuple[int, int]:
    succeeded = sum(1 for it in items if it.get("status") == "succeeded")
    failed = sum(1 for it in items if it.get("status") == "failed")
    return succeeded, failed


def _job_to_out(job: VideoSubtitleJob) -> SubtitleJobOut:
    try:
        items = json.loads(job.items_json or "[]")
    except Exception:
        items = []
    try:
        filenames = (
            json.loads(job.original_filenames_json)
            if job.original_filenames_json
            else None
        )
    except Exception:
        filenames = None
    succeeded, failed = _items_counts(items)
    items_out: list[SubtitleJobItemOut] = []
    for it in items:
        items_out.append(
            SubtitleJobItemOut(
                index=it.get("index", 0),
                filename=it.get("filename", ""),
                input_oss_uri=it.get("input_oss_uri", ""),
                input_oss_public_url=it.get("input_oss_public_url", ""),
                input_tos_uri=it.get("input_tos_uri", ""),
                input_tos_public_url=it.get("input_tos_public_url", ""),
                viapi_job_id=it.get("viapi_job_id"),
                viapi_status=it.get("viapi_status"),
                srt_tos_uri=it.get("srt_tos_uri"),
                srt_tos_public_url=it.get("srt_tos_public_url"),
                translated_srt_tos_uri=it.get("translated_srt_tos_uri"),
                translated_srt_tos_public_url=it.get("translated_srt_tos_public_url"),
                output_video_tos_uri=it.get("output_video_tos_uri"),
                output_video_tos_public_url=it.get("output_video_tos_public_url"),
                status=it.get("status", "pending"),
                error=it.get("error"),
            )
        )
    return SubtitleJobOut(
        id=job.id,
        title=job.title,
        video_count=job.video_count,
        subtitle_source=job.subtitle_source,
        enable_translate=job.enable_translate,
        enable_burn=job.enable_burn,
        placement_mode=job.placement_mode,
        target_lang=job.target_lang,
        model_provider=job.model_provider,
        model_name=job.model_name,
        items=items_out,
        original_filenames=filenames,
        output_tos_prefix=job.output_tos_prefix,
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


def _job_to_summary(job: VideoSubtitleJob) -> SubtitleJobSummary:
    try:
        items = json.loads(job.items_json or "[]")
    except Exception:
        items = []
    succeeded, failed = _items_counts(items)
    return SubtitleJobSummary(
        id=job.id,
        title=job.title,
        video_count=job.video_count,
        subtitle_source=job.subtitle_source,
        enable_translate=job.enable_translate,
        enable_burn=job.enable_burn,
        status=job.status,
        succeeded_count=succeeded,
        failed_count=failed,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post(
    "/upload-url",
    response_model=SubtitleUploadUrlResponse,
    dependencies=[Depends(require_passphrase)],
)
async def create_upload_urls(
    payload: SubtitleUploadUrlRequest,
    settings=Depends(get_settings),
) -> SubtitleUploadUrlResponse:
    """为每个文件生成两组预签名 PUT URL：
    - 阿里云上海 OSS：VIAPI 字幕 OCR 直接拉取
    - 新加坡 TOS：后端烧录视频源 + 产物存储
    用户浏览器并发上传两路（上行流量免费）。
    """
    if not payload.files:
        raise HTTPException(status_code=400, detail="文件列表不能为空")
    try:
        oss = AliyunOSSClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        tos = TOSSingaporeClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job_id = str(uuid.uuid4())
    expires_in = 3600
    entries: list[SubtitleUploadEntry] = []
    oss_prefix = settings.oss_super_res_upload_prefix.rstrip("/") or "super-resolution-input"
    # OSS 用独立 prefix，避免和超分辨混
    oss_prefix = "subtitle-input"
    tos_prefix = settings.tos_subtitle_input_prefix.rstrip("/") or "subtitle-input"
    for index, spec in enumerate(payload.files):
        safe = _safe_filename(spec.filename)
        oss_key = f"{oss_prefix}/{job_id}/{index:02d}-{safe}"
        tos_key = f"{tos_prefix}/{job_id}/{index:02d}-{safe}"
        oss_result = oss.presign_put(oss_key, content_type=spec.content_type, expires_in=expires_in)
        tos_result = tos.presign_put(tos_key, content_type=spec.content_type, expires_in=expires_in)
        entries.append(
            SubtitleUploadEntry(
                filename=spec.filename,
                oss_presigned_url=oss_result.presigned_url,
                oss_public_url=oss_result.public_url,
                oss_uri=oss_result.oss_uri,
                oss_key=oss_result.key,
                tos_presigned_url=tos_result.presigned_url,
                tos_public_url=tos_result.public_url,
                tos_uri=tos_result.tos_uri,
                tos_key=tos_result.key,
            )
        )
    return SubtitleUploadUrlResponse(job_id=job_id, expires_in=expires_in, entries=entries)


@router.post(
    "",
    response_model=SubtitleJobOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_passphrase)],
)
async def create_subtitle_job(
    payload: SubtitleJobCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> SubtitleJobOut:
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    if not payload.items:
        raise HTTPException(status_code=400, detail="视频列表不能为空")
    for it in payload.items:
        if not it.oss_uri.startswith("oss://"):
            raise HTTPException(status_code=400, detail=f"非法的视频 oss_uri: {it.oss_uri}")
        if not it.tos_uri.startswith("tos://"):
            raise HTTPException(status_code=400, detail=f"非法的视频 tos_uri: {it.tos_uri}")
    if payload.enable_translate:
        if not (payload.target_lang and payload.model_provider and payload.model_name):
            raise HTTPException(
                status_code=400,
                detail="启用翻译时 target_lang / model_provider / model_name 必填",
            )

    existing = await session.get(VideoSubtitleJob, payload.job_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="job_id 已存在")

    output_prefix = (
        f"tos://{settings.tos_sg_bucket}/"
        f"{settings.tos_subtitle_output_prefix.strip('/') or 'subtitle-output'}/"
        f"{payload.job_id}/"
    )

    items: list[dict] = []
    for index, spec in enumerate(payload.items):
        items.append(
            {
                "index": index,
                "filename": spec.filename,
                # 输入：OSS（VIAPI 用）+ 新加坡 TOS（烧录源）
                "input_oss_uri": spec.oss_uri,
                "input_oss_public_url": spec.oss_public_url,
                "input_tos_uri": spec.tos_uri,
                "input_tos_public_url": spec.tos_public_url,
                # VIAPI
                "viapi_job_id": None,
                "viapi_status": None,
                # SRT 产物
                "srt_tos_uri": None,
                "srt_tos_public_url": None,
                "srt_text": None,
                # 译文 SRT
                "translated_srt_tos_uri": None,
                "translated_srt_tos_public_url": None,
                "translated_srt_text": None,
                # 输出视频
                "output_video_tos_uri": None,
                "output_video_tos_public_url": None,
                "status": "pending",
                "error": None,
            }
        )

    job = VideoSubtitleJob(
        id=payload.job_id,
        title=title,
        video_count=len(payload.items),
        subtitle_source=payload.subtitle_source,
        enable_translate=payload.enable_translate,
        enable_burn=payload.enable_burn,
        placement_mode=payload.placement_mode,
        target_lang=payload.target_lang,
        model_provider=payload.model_provider,
        model_name=payload.model_name,
        items_json=json.dumps(items, ensure_ascii=False),
        original_filenames_json=(
            json.dumps(payload.original_filenames, ensure_ascii=False)
            if payload.original_filenames
            else None
        ),
        output_tos_prefix=output_prefix,
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    state = request.app.state

    async def _runner() -> None:
        await run_video_subtitle_job(state.db, state.settings, state.registry, job.id)

    background_tasks.add_task(_runner)
    return _job_to_out(job)


@router.get("/{job_id}", response_model=SubtitleJobOut)
async def get_subtitle_job(
    job_id: str, session: AsyncSession = Depends(get_session)
) -> SubtitleJobOut:
    job = await session.get(VideoSubtitleJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _job_to_out(job)


@router.post(
    "/{job_id}/retry",
    response_model=SubtitleJobOut,
    dependencies=[Depends(require_passphrase)],
)
async def retry_failed_items(
    job_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> SubtitleJobOut:
    """重试 job 中 status=failed 的 item。succeeded 的保留不动。"""

    job = await session.get(VideoSubtitleJob, job_id)
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
        await run_video_subtitle_job(
            state.db, state.settings, state.registry, job.id, only_indices=failed_indices
        )

    background_tasks.add_task(_runner)
    return _job_to_out(job)


@router.get("", response_model=list[SubtitleJobSummary])
async def list_subtitle_jobs(
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> list[SubtitleJobSummary]:
    rows = await session.scalars(
        select(VideoSubtitleJob)
        .order_by(VideoSubtitleJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_job_to_summary(j) for j in rows]
