from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session, get_settings, require_passphrase
from app.models import AppSetting, VideoImsSpeechJob
from app.schemas import (
    ImsSpeechJobCreateRequest,
    ImsSpeechJobItemOut,
    ImsSpeechJobOut,
    ImsSpeechJobSummary,
    SubtitleEraseAbortMultipartRequest,
    SubtitleEraseAbortMultipartResponse,
    SubtitleEraseCompleteMultipartRequest,
    SubtitleEraseCompleteMultipartResponse,
    SubtitleEraseMultipartPartInfo,
    SubtitleEraseMultipartUploadUrlRequest,
    SubtitleEraseMultipartUploadUrlResponse,
    SubtitleEraseUploadEntry,
    SubtitleEraseUploadUrlRequest,
    SubtitleEraseUploadUrlResponse,
)
from app.services.aliyun_oss_client import AliyunOSSClient
from app.services.ims_speech_runner import run_ims_speech_job
from app.services.ims_subtitle_style import (
    ADAPTIVE_STYLE_MODE,
    adaptive_fe_canvas,
    build_adaptive_subtitle_config,
)

router = APIRouter(
    prefix="/ims-speech-translation",
    tags=["ims-speech-translation"],
)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")
_TRANSLATION_ARTIFACT_FIELDS = (
    "media_url",
    "media_id",
    "translated_audio_url",
    "translated_audio_media_id",
    "subtitle_url",
    "subtitle_signed_url",
    "fix_subtitle_url",
    "fix_subtitle_media_id",
    "bilingual_subtitle_url",
    "bilingual_subtitle_media_id",
    "speech_translation_job_id",
)
_STOP_MESSAGE = "用户停止本地跟踪；阿里云任务可能仍在执行并产生费用"
_SETTINGS_KEY = "ims_speech_form_params"


def _safe_filename(name: str) -> str:
    base = name.strip().replace("\\", "/").split("/")[-1] or "video"
    return _SAFE_NAME.sub("_", base)


def _spawn_runner(
    request: Request,
    job_id: str,
    *,
    only_indices: list[int] | None = None,
) -> None:
    state = request.app.state

    async def _runner() -> None:
        try:
            await run_ims_speech_job(
                state.db,
                state.settings,
                job_id,
                only_indices=only_indices,
                global_rate_limiter=state.ims_rate_limiter,
            )
        finally:
            state.ims_speech_tasks.pop(job_id, None)

    previous = state.ims_speech_tasks.get(job_id)
    if previous is not None and not previous.done():
        raise HTTPException(status_code=409, detail="任务已在运行")
    state.ims_speech_tasks[job_id] = asyncio.create_task(_runner())


def _loads(value: str | None, fallback):
    try:
        return json.loads(value) if value else fallback
    except json.JSONDecodeError:
        return fallback


def _counts(items: list[dict]) -> tuple[int, int, int]:
    return (
        sum(1 for item in items if item.get("status") == "succeeded"),
        sum(1 for item in items if item.get("status") == "partial_failed"),
        sum(1 for item in items if item.get("status") == "failed"),
    )


def _job_to_out(job: VideoImsSpeechJob) -> ImsSpeechJobOut:
    items = _loads(job.items_json, [])
    target_languages = _loads(job.target_langs_json, [])
    succeeded, partial_failed, failed = _counts(items)
    return ImsSpeechJobOut(
        id=job.id,
        title=job.title,
        drama_count=job.drama_count,
        video_count=job.video_count,
        source_language=job.source_language,
        target_languages=target_languages,
        text_source=job.text_source,
        config=_loads(job.config_json, {}),
        items=[ImsSpeechJobItemOut(**item) for item in items],
        original_filenames=_loads(job.original_filenames_json, None),
        output_oss_prefix=job.output_oss_prefix,
        status=job.status,
        progress_message=job.progress_message,
        error_message=job.error_message,
        succeeded_count=succeeded,
        partial_failed_count=partial_failed,
        failed_count=failed,
        submitted_at=job.submitted_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _job_to_summary(job: VideoImsSpeechJob) -> ImsSpeechJobSummary:
    items = _loads(job.items_json, [])
    succeeded, partial_failed, failed = _counts(items)
    return ImsSpeechJobSummary(
        id=job.id,
        title=job.title,
        drama_count=job.drama_count,
        video_count=job.video_count,
        source_language=job.source_language,
        target_languages=_loads(job.target_langs_json, []),
        text_source=job.text_source,
        status=job.status,
        succeeded_count=succeeded,
        partial_failed_count=partial_failed,
        failed_count=failed,
        error_message=job.error_message,
        created_at=job.created_at,
    )


@router.post(
    "/upload-url",
    response_model=SubtitleEraseUploadUrlResponse,
    dependencies=[Depends(require_passphrase)],
)
async def create_upload_urls(
    payload: SubtitleEraseUploadUrlRequest,
    settings=Depends(get_settings),
) -> SubtitleEraseUploadUrlResponse:
    if not payload.files:
        raise HTTPException(status_code=400, detail="文件列表不能为空")
    try:
        oss = AliyunOSSClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job_id = payload.job_id or str(uuid.uuid4())
    expires_in = 3600
    prefix = settings.oss_ims_speech_input_prefix.rstrip("/") or "ims-speech-input"
    entries: list[SubtitleEraseUploadEntry] = []
    for index, spec in enumerate(payload.files):
        key = f"{prefix}/{job_id}/{index:02d}-{_safe_filename(spec.filename)}"
        result = oss.presign_put(
            key,
            content_type=spec.content_type,
            expires_in=expires_in,
        )
        entries.append(
            SubtitleEraseUploadEntry(
                filename=spec.filename,
                presigned_url=result.presigned_url,
                public_url=result.public_url,
                oss_uri=result.oss_uri,
                key=result.key,
            )
        )
    return SubtitleEraseUploadUrlResponse(
        job_id=job_id,
        expires_in=expires_in,
        entries=entries,
    )


@router.post(
    "/upload-multipart-url",
    response_model=SubtitleEraseMultipartUploadUrlResponse,
    dependencies=[Depends(require_passphrase)],
)
async def create_multipart_upload_urls(
    payload: SubtitleEraseMultipartUploadUrlRequest,
    settings=Depends(get_settings),
) -> SubtitleEraseMultipartUploadUrlResponse:
    try:
        oss = AliyunOSSClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job_id = payload.job_id or str(uuid.uuid4())
    prefix = settings.oss_ims_speech_input_prefix.rstrip("/") or "ims-speech-input"
    key = f"{prefix}/{job_id}/{payload.index:02d}-{_safe_filename(payload.filename)}"
    expires_in = 3600
    try:
        result = oss.presign_multipart_put(
            key,
            content_type=payload.content_type,
            file_size=payload.file_size,
            expires_in=expires_in,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"init multipart failed: {exc}",
        ) from exc
    return SubtitleEraseMultipartUploadUrlResponse(
        job_id=job_id,
        upload_id=result.upload_id,
        key=result.key,
        oss_uri=result.oss_uri,
        public_url=result.public_url,
        part_size=8 * 1024 * 1024,
        parts=[
            SubtitleEraseMultipartPartInfo(
                part_number=part.part_number,
                offset=part.offset,
                size=part.size,
                presigned_url=part.presigned_url,
            )
            for part in result.parts
        ],
        expires_in=expires_in,
    )


@router.post(
    "/complete-multipart",
    response_model=SubtitleEraseCompleteMultipartResponse,
    dependencies=[Depends(require_passphrase)],
)
async def complete_multipart(
    payload: SubtitleEraseCompleteMultipartRequest,
    settings=Depends(get_settings),
) -> SubtitleEraseCompleteMultipartResponse:
    try:
        oss = AliyunOSSClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    sorted_parts = sorted(payload.parts, key=lambda part: part.part_number)
    expected = list(range(1, len(sorted_parts) + 1))
    if [part.part_number for part in sorted_parts] != expected:
        raise HTTPException(status_code=400, detail="part_number 不连续")
    try:
        public_url, oss_uri = oss.complete_multipart(
            payload.key,
            payload.upload_id,
            [
                {"part_number": part.part_number, "etag": part.etag}
                for part in sorted_parts
            ],
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"complete failed: {exc}") from exc
    return SubtitleEraseCompleteMultipartResponse(
        public_url=public_url,
        oss_uri=oss_uri,
    )


@router.post(
    "/abort-multipart",
    response_model=SubtitleEraseAbortMultipartResponse,
    dependencies=[Depends(require_passphrase)],
)
async def abort_multipart(
    payload: SubtitleEraseAbortMultipartRequest,
    settings=Depends(get_settings),
) -> SubtitleEraseAbortMultipartResponse:
    try:
        oss = AliyunOSSClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    oss.abort_multipart(payload.key, payload.upload_id)
    return SubtitleEraseAbortMultipartResponse(ok=True)


@router.post(
    "",
    response_model=ImsSpeechJobOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_passphrase)],
)
async def create_ims_speech_job(
    payload: ImsSpeechJobCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> ImsSpeechJobOut:
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    if await session.get(VideoImsSpeechJob, payload.job_id):
        raise HTTPException(status_code=409, detail="job_id 已存在")
    for item in payload.items:
        if not item.oss_uri.startswith("oss://"):
            raise HTTPException(status_code=400, detail=f"非法的 OSS 地址: {item.oss_uri}")

    target_languages = payload.target_languages
    items: list[dict] = []
    for index, spec in enumerate(payload.items):
        items.append(
            {
                "index": index,
                "drama_index": spec.drama_index,
                "episode_index": spec.episode_index,
                "filename": spec.filename,
                "input_oss_uri": spec.oss_uri,
                "input_public_url": spec.public_url,
                "ims_job_id": None,
                "ims_status": None,
                "detext_video_url": None,
                "detext_video_media_id": None,
                "translations": {
                    language: {"status": "pending", "error": None}
                    for language in target_languages
                },
                "stage": "pending",
                "status": "pending",
                "error": None,
            }
        )
    subtitle_config = build_adaptive_subtitle_config(
        bilingual=payload.bilingual_subtitle,
        subtitle_enabled=payload.subtitle_enabled,
        font_color=payload.font_color,
        font_color_opacity=payload.font_color_opacity,
        subtitle_y=payload.subtitle_y,
    )
    config = {
        "style_mode": ADAPTIVE_STYLE_MODE,
        "fe_canvas": adaptive_fe_canvas(),
        "subtitle_config": subtitle_config,
        "detext_mode": payload.detext_mode,
        "detext_areas": (
            [area.as_list() for area in payload.detext_areas]
            if payload.detext_areas
            else None
        ),
        "ocr_area": payload.ocr_area.as_list() if payload.ocr_area else None,
        "bilingual_subtitle": payload.bilingual_subtitle,
        "subtitle_enabled": payload.subtitle_enabled,
        "skip_song": payload.skip_song,
        "font_color": payload.font_color,
        "font_color_opacity": payload.font_color_opacity,
        "subtitle_y": payload.subtitle_y,
    }
    output_prefix = (
        f"oss://{settings.aliyun_oss_bucket}/"
        f"{settings.oss_ims_speech_output_prefix.strip('/')}/"
        f"{payload.job_id}/"
    )
    job = VideoImsSpeechJob(
        id=payload.job_id,
        title=title,
        drama_count=len({item["drama_index"] for item in items}),
        video_count=len(items),
        source_language=payload.source_language,
        target_langs_json=json.dumps(target_languages, ensure_ascii=False),
        text_source=payload.text_source,
        config_json=json.dumps(config, ensure_ascii=False),
        items_json=json.dumps(items, ensure_ascii=False),
        original_filenames_json=(
            json.dumps(payload.original_filenames, ensure_ascii=False)
            if payload.original_filenames
            else None
        ),
        output_oss_prefix=output_prefix,
        status="pending",
        progress_message="排队中",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    response = _job_to_out(job)
    _spawn_runner(request, job.id)
    return response


@router.get(
    "/settings",
    response_model=dict,
    dependencies=[Depends(require_passphrase)],
)
async def get_ims_speech_settings(
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await session.get(AppSetting, _SETTINGS_KEY)
    if row is None:
        return {}
    return _loads(row.value, {})


@router.put(
    "/settings",
    response_model=dict,
    dependencies=[Depends(require_passphrase)],
)
async def save_ims_speech_settings(
    payload: dict,
    session: AsyncSession = Depends(get_session),
) -> dict:
    value = json.dumps(payload, ensure_ascii=False)
    row = await session.get(AppSetting, _SETTINGS_KEY)
    if row is None:
        session.add(AppSetting(key=_SETTINGS_KEY, value=value))
    else:
        row.value = value
    await session.commit()
    return payload


@router.get("/{job_id}", response_model=ImsSpeechJobOut)
async def get_ims_speech_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> ImsSpeechJobOut:
    job = await session.get(VideoImsSpeechJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _job_to_out(job)


@router.post(
    "/{job_id}/stop",
    response_model=ImsSpeechJobOut,
    dependencies=[Depends(require_passphrase)],
)
async def stop_ims_speech_job(
    job_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ImsSpeechJobOut:
    job = await session.get(VideoImsSpeechJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status not in {"pending", "running"}:
        raise HTTPException(
            status_code=400,
            detail=f"只有 pending/running 状态的任务才能停止（当前: {job.status}）",
        )

    task = request.app.state.ims_speech_tasks.get(job_id)
    if task is not None and not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=5)
        except (asyncio.CancelledError, TimeoutError):
            pass

    await session.refresh(job)
    items = _loads(job.items_json, [])
    for item in items:
        if item.get("status") in {"pending", "running"}:
            item["status"] = "failed"
            item["stage"] = "stopped"
            item["error"] = _STOP_MESSAGE
        for translation in (item.get("translations") or {}).values():
            if translation.get("status") in {"pending", "running"}:
                translation["status"] = "failed"
                translation["error"] = _STOP_MESSAGE
    job.items_json = json.dumps(items, ensure_ascii=False)
    job.status = "failed"
    job.progress_message = "已停止本地跟踪"
    job.error_message = _STOP_MESSAGE
    job.completed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(job)
    return _job_to_out(job)


@router.post(
    "/{job_id}/retry",
    response_model=ImsSpeechJobOut,
    dependencies=[Depends(require_passphrase)],
)
async def retry_ims_speech_job(
    job_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ImsSpeechJobOut:
    job = await session.get(VideoImsSpeechJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status in {"pending", "running"}:
        raise HTTPException(status_code=400, detail="任务仍在运行，不能重试")

    items = _loads(job.items_json, [])
    retry_indices: list[int] = []
    for index, item in enumerate(items):
        translations = item.get("translations") or {}
        failed = [
            value
            for value in translations.values()
            if value.get("status") != "succeeded"
        ]
        if not failed:
            continue
        retry_indices.append(index)
        item["ims_job_id"] = None
        item["ims_status"] = None
        item["stage"] = "pending"
        item["status"] = "pending"
        item["error"] = None
        for translation in failed:
            for field in _TRANSLATION_ARTIFACT_FIELDS:
                translation[field] = None
            translation["status"] = "pending"
            translation["error"] = None

    if not retry_indices:
        raise HTTPException(status_code=400, detail="没有可重试的失败语言")

    job.items_json = json.dumps(items, ensure_ascii=False)
    job.status = "pending"
    job.progress_message = "排队重试失败语言"
    job.error_message = None
    job.completed_at = None
    await session.commit()
    await session.refresh(job)
    response = _job_to_out(job)
    _spawn_runner(request, job.id, only_indices=retry_indices)
    return response


@router.get("", response_model=list[ImsSpeechJobSummary])
async def list_ims_speech_jobs(
    limit: int = 20,
    offset: int = 0,
    q: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[ImsSpeechJobSummary]:
    stmt = select(VideoImsSpeechJob)
    if q and q.strip():
        stmt = stmt.where(VideoImsSpeechJob.title.ilike(f"%{q.strip()}%"))
    stmt = stmt.order_by(VideoImsSpeechJob.created_at.desc()).limit(limit).offset(offset)
    rows = await session.scalars(stmt)
    return [_job_to_summary(job) for job in rows]
