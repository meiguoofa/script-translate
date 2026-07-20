"""Starling 短剧翻配路由。

接口面对齐 subtitle_erase，前缀 /starling-drama：
- POST /upload-url             单 PUT 上传 URL
- POST /upload-multipart-url   分片上传初始化
- POST /complete-multipart     完成分片
- POST /abort-multipart        取消分片
- POST ""                       创建任务 + BackgroundTasks
- GET  ""                       列表
- GET  /{job_id}                详情
- POST /{job_id}/retry         重试失败子任务
- POST /{job_id}/stop          停止任务
- GET  /settings                表单参数持久化（复用 AppSetting）
- PUT  /settings                保存表单参数
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session, get_settings, require_passphrase
from app.models import AppSetting, StarlingDramaJob
from app.schemas import (
    StarlingDramaAbortMultipartRequest,
    StarlingDramaAbortMultipartResponse,
    StarlingDramaCompleteMultipartRequest,
    StarlingDramaCompleteMultipartResponse,
    StarlingDramaJobCreateRequest,
    StarlingDramaJobItemOut,
    StarlingDramaJobOut,
    StarlingDramaJobSummary,
    StarlingDramaMultipartPartInfo,
    StarlingDramaMultipartUploadUrlRequest,
    StarlingDramaMultipartUploadUrlResponse,
    StarlingDramaRerunRequest,
    StarlingDramaTranslationOut,
    StarlingDramaUploadEntry,
    StarlingDramaUploadUrlRequest,
    StarlingDramaUploadUrlResponse,
)
from app.services.starling_drama_runner import run_starling_drama_job
from app.services.tos_starling_client import TOSStarlingClient

router = APIRouter(prefix="/starling-drama", tags=["starling-drama"])

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")
_SETTINGS_KEY = "starling_drama_form"


def _safe_filename(name: str) -> str:
    base = name.strip().replace("\\", "/").split("/")[-1] or "video"
    return _SAFE_NAME.sub("_", base)


def _tos_uri_to_public_url(tos_uri: str | None, settings) -> str | None:
    """tos://bucket/key -> 公开 HTTPS URL（Starling 北京桶）。"""
    if not tos_uri or not tos_uri.startswith("tos://"):
        return None
    rest = tos_uri[len("tos://"):]
    parts = rest.split("/", 1)
    if len(parts) < 2 or not parts[1]:
        return None
    key = parts[1]
    encoded = "/".join(quote(p, safe="") for p in key.split("/"))
    return f"https://{settings.tos_starling_bucket}.{settings.tos_starling_public_endpoint}/{encoded}"


def _items_counts(items: list[dict]) -> tuple[int, int]:
    succeeded = sum(1 for it in items if it.get("status") == "succeeded")
    failed = sum(1 for it in items if it.get("status") == "failed")
    return succeeded, failed


def _parse_target_langs(job: StarlingDramaJob) -> list[str]:
    if job.target_langs_json:
        try:
            lst = json.loads(job.target_langs_json)
            if isinstance(lst, list) and lst:
                return [str(x) for x in lst if str(x).strip()]
        except json.JSONDecodeError:
            pass
    return []


def _item_translations_to_out(translations: dict | None) -> dict[str, StarlingDramaTranslationOut]:
    if not isinstance(translations, dict):
        return {}
    out: dict[str, StarlingDramaTranslationOut] = {}
    for lang, t in translations.items():
        if not isinstance(t, dict):
            continue
        out[lang] = StarlingDramaTranslationOut(
            starling_subtask_id=t.get("starling_subtask_id"),
            ai_flow_status=t.get("ai_flow_status"),
            submit_status=t.get("submit_status"),
            suppression_status=t.get("suppression_status"),
            products=t.get("products", {}) or {},
            error_message=t.get("error_message"),
        )
    return out


def _job_to_out(job: StarlingDramaJob, settings) -> StarlingDramaJobOut:
    try:
        items = json.loads(job.items_json or "[]")
    except Exception:
        items = []
    succeeded, failed = _items_counts(items)
    items_out: list[StarlingDramaJobItemOut] = []
    for it in items:
        source_tos_uri = it.get("source_tos_uri") or it.get("source_oss_uri") or ""
        source_video_url = it.get("source_video_url") or _tos_uri_to_public_url(source_tos_uri, settings)
        items_out.append(
            StarlingDramaJobItemOut(
                drama_index=it.get("drama_index", 0),
                episode_number=it.get("episode_number", it.get("episode_index", 0)),
                source_filename=it.get("source_filename") or it.get("filename") or "",
                source_oss_uri=source_tos_uri,
                source_video_url=source_video_url,
                duration_ms=it.get("duration_ms"),
                width=it.get("width"),
                height=it.get("height"),
                starling_video_id=it.get("starling_video_id"),
                upload_batch_id=it.get("upload_batch_id"),
                upload_status=it.get("upload_status"),
                translations=_item_translations_to_out(it.get("translations")),
                status=it.get("status", "pending"),
                error=it.get("error"),
            )
        )
    try:
        original_filenames = json.loads(job.original_filenames_json) if job.original_filenames_json else None
    except Exception:
        original_filenames = None
    return StarlingDramaJobOut(
        id=job.id,
        title=job.title,
        drama_name=job.drama_name,
        source_lang=job.source_lang,
        target_langs=_parse_target_langs(job),
        starling_project_id=job.starling_project_id,
        starling_task_id=job.starling_task_id,
        subtitle_removal_mode=job.subtitle_removal_mode,
        burn_target_subtitle=job.burn_target_subtitle,
        subtitle_style_template=job.subtitle_style_template,
        dubbing_enabled=job.dubbing_enabled,
        dubbing_speaker_mode=job.dubbing_speaker_mode,
        dubbing_emotion_mode=job.dubbing_emotion_mode,
        dubbing_preserve_bg_audio=job.dubbing_preserve_bg_audio,
        workflow_mode=job.workflow_mode,
        max_retry_count=job.max_retry_count,
        items=items_out,
        original_filenames=original_filenames,
        output_oss_prefix=job.output_oss_prefix,
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


def _job_to_summary(job: StarlingDramaJob) -> StarlingDramaJobSummary:
    try:
        items = json.loads(job.items_json or "[]")
    except Exception:
        items = []
    succeeded, failed = _items_counts(items)
    return StarlingDramaJobSummary(
        id=job.id,
        title=job.title,
        drama_name=job.drama_name,
        source_lang=job.source_lang,
        target_langs=_parse_target_langs(job),
        status=job.status,
        progress_message=job.progress_message,
        error_message=job.error_message,
        succeeded_count=succeeded,
        failed_count=failed,
        submitted_at=job.submitted_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
    )


# ---------- 上传 URL ----------

@router.post(
    "/upload-url",
    response_model=StarlingDramaUploadUrlResponse,
    dependencies=[Depends(require_passphrase)],
)
async def create_upload_urls(
    payload: StarlingDramaUploadUrlRequest,
    settings=Depends(get_settings),
) -> StarlingDramaUploadUrlResponse:
    if not payload.files:
        raise HTTPException(status_code=400, detail="文件列表不能为空")
    try:
        tos = TOSStarlingClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job_id = payload.job_id or str(uuid.uuid4())
    expires_in = 3600
    entries: list[StarlingDramaUploadEntry] = []
    prefix = settings.tos_starling_input_prefix.rstrip("/") or "starling-input"
    for index, spec in enumerate(payload.files):
        safe = _safe_filename(spec.filename)
        key = f"{prefix}/{job_id}/{index:02d}-{safe}"
        result = tos.presign_put(key, content_type=spec.content_type, expires_in=expires_in)
        entries.append(
            StarlingDramaUploadEntry(
                filename=spec.filename,
                presigned_url=result.presigned_url,
                public_url=result.public_url,
                oss_uri=result.tos_uri,  # 字段名保留 oss_uri 与前端 schema 对齐
                key=result.key,
            )
        )
    return StarlingDramaUploadUrlResponse(job_id=job_id, expires_in=expires_in, entries=entries)


@router.post(
    "/upload-multipart-url",
    response_model=StarlingDramaMultipartUploadUrlResponse,
    dependencies=[Depends(require_passphrase)],
)
async def create_multipart_upload_urls(
    payload: StarlingDramaMultipartUploadUrlRequest,
    settings=Depends(get_settings),
) -> StarlingDramaMultipartUploadUrlResponse:
    try:
        tos = TOSStarlingClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job_id = payload.job_id or str(uuid.uuid4())
    safe = _safe_filename(payload.filename)
    prefix = settings.tos_starling_input_prefix.rstrip("/") or "starling-input"
    key = f"{prefix}/{job_id}/{payload.index:02d}-{safe}"
    expires_in = 3600
    try:
        result, info = tos.presign_multipart_put(
            key,
            content_type=payload.content_type,
            file_size=payload.file_size,
            expires_in=expires_in,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"init multipart failed: {exc}") from exc
    return StarlingDramaMultipartUploadUrlResponse(
        job_id=job_id,
        upload_id=info["upload_id"],
        key=result.key,
        oss_uri=result.tos_uri,
        public_url=result.public_url,
        part_size=info["part_size"],
        parts=[
            StarlingDramaMultipartPartInfo(
                part_number=p["part_number"],
                offset=p["offset"],
                size=p["size"],
                presigned_url=p["presigned_url"],
            )
            for p in info["parts"]
        ],
        expires_in=expires_in,
    )


@router.post(
    "/complete-multipart",
    response_model=StarlingDramaCompleteMultipartResponse,
    dependencies=[Depends(require_passphrase)],
)
async def complete_multipart(
    payload: StarlingDramaCompleteMultipartRequest,
    settings=Depends(get_settings),
) -> StarlingDramaCompleteMultipartResponse:
    try:
        tos = TOSStarlingClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        tos.complete_multipart(
            payload.key,
            payload.upload_id,
            [(p.part_number, p.etag) for p in payload.parts],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"complete multipart failed: {exc}") from exc
    return StarlingDramaCompleteMultipartResponse(
        public_url=tos.public_url(payload.key),
        oss_uri=tos.tos_uri(payload.key),
    )


@router.post(
    "/abort-multipart",
    response_model=StarlingDramaAbortMultipartResponse,
    dependencies=[Depends(require_passphrase)],
)
async def abort_multipart(
    payload: StarlingDramaAbortMultipartRequest,
    settings=Depends(get_settings),
) -> StarlingDramaAbortMultipartResponse:
    try:
        tos = TOSStarlingClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    tos.abort_multipart(payload.key, payload.upload_id)
    return StarlingDramaAbortMultipartResponse(ok=True)


# ---------- 任务创建/查询/重试/停止 ----------

@router.post(
    "",
    response_model=StarlingDramaJobOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_passphrase)],
)
async def create_starling_drama_job(
    payload: StarlingDramaJobCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> StarlingDramaJobOut:
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    if not payload.drama_name.strip():
        raise HTTPException(status_code=400, detail="短剧名称不能为空")
    if not payload.items:
        raise HTTPException(status_code=400, detail="视频列表不能为空")
    for it in payload.items:
        if not it.oss_uri.startswith("tos://") and not it.oss_uri.startswith("oss://"):
            raise HTTPException(status_code=400, detail=f"非法的视频 oss_uri: {it.oss_uri}")
    if not settings.starling_access_key_id or not settings.starling_secret_access_key:
        raise HTTPException(
            status_code=503,
            detail="Starling 凭证未配置（STARLING_ACCESS_KEY_ID/SECRET_ACCESS_KEY）",
        )

    existing = await session.get(StarlingDramaJob, payload.job_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="job_id 已存在")

    output_tos_prefix = (
        f"tos://{settings.tos_starling_bucket}/"
        f"{payload.job_id}/"
    )
    output_oss_prefix = output_tos_prefix  # 兼容字段

    items: list[dict] = []
    for index, spec in enumerate(payload.items):
        items.append({
            "drama_index": spec.drama_index,
            "episode_number": spec.episode_index,
            "source_filename": spec.filename,
            "source_tos_uri": spec.oss_uri if spec.oss_uri.startswith("tos://") else None,
            "source_oss_uri": spec.oss_uri,  # 兼容旧字段
            "source_video_url": spec.public_url,
            "duration_ms": None,
            "width": None,
            "height": None,
            "starling_video_id": None,
            "upload_batch_id": None,
            "upload_status": None,
            "translations": {
                lang: {
                    "starling_subtask_id": None,
                    "ai_flow_status": None,
                    "submit_status": None,
                    "suppression_status": None,
                    "products": {},
                    "error_message": None,
                }
                for lang in payload.target_langs
            },
            "status": "pending",
            "error": None,
        })

    job = StarlingDramaJob(
        id=payload.job_id,
        title=title,
        drama_name=payload.drama_name.strip(),
        source_lang=payload.source_lang,
        target_langs_json=json.dumps(payload.target_langs, ensure_ascii=False),
        starling_project_id=None,
        starling_task_id=None,
        subtitle_removal_mode=payload.subtitle_removal_mode,
        burn_target_subtitle=payload.burn_target_subtitle,
        subtitle_style_template=payload.subtitle_style_template,
        dubbing_enabled=payload.dubbing_enabled,
        dubbing_speaker_mode=payload.dubbing_speaker_mode,
        dubbing_emotion_mode=payload.dubbing_emotion_mode,
        dubbing_preserve_bg_audio=payload.dubbing_preserve_bg_audio,
        workflow_mode=payload.workflow_mode,
        max_retry_count=payload.max_retry_count,
        items_json=json.dumps(items, ensure_ascii=False),
        original_filenames_json=(
            json.dumps(payload.original_filenames, ensure_ascii=False)
            if payload.original_filenames else None
        ),
        output_oss_prefix=output_oss_prefix,
        output_tos_prefix=output_tos_prefix,
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    state = request.app.state

    async def _runner() -> None:
        await run_starling_drama_job(state.db, state.settings, job.id)

    background_tasks.add_task(_runner)
    return _job_to_out(job, settings)


@router.get(
    "",
    response_model=list[StarlingDramaJobSummary],
    dependencies=[Depends(require_passphrase)],
)
async def list_starling_drama_jobs(
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
    limit: int = 100,
    offset: int = 0,
) -> list[StarlingDramaJobSummary]:
    stmt = (
        select(StarlingDramaJob)
        .order_by(StarlingDramaJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    jobs = result.scalars().all()
    return [_job_to_summary(j) for j in jobs]


# ---------- 表单参数持久化（必须在 /{job_id} 之前注册） ----------

@router.get(
    "/settings",
    dependencies=[Depends(require_passphrase)],
)
async def get_starling_drama_settings(
    session: AsyncSession = Depends(get_session),
) -> dict:
    setting = await session.get(AppSetting, _SETTINGS_KEY)
    if setting is None:
        return {}
    try:
        return json.loads(setting.value)
    except json.JSONDecodeError:
        return {}


@router.put(
    "/settings",
    dependencies=[Depends(require_passphrase)],
)
async def save_starling_drama_settings(
    payload: dict,
    session: AsyncSession = Depends(get_session),
) -> dict:
    setting = await session.get(AppSetting, _SETTINGS_KEY)
    value = json.dumps(payload, ensure_ascii=False)
    if setting is None:
        setting = AppSetting(key=_SETTINGS_KEY, value=value)
        session.add(setting)
    else:
        setting.value = value
    await session.commit()
    return payload


@router.get(
    "/{job_id}",
    response_model=StarlingDramaJobOut,
    dependencies=[Depends(require_passphrase)],
)
async def get_starling_drama_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> StarlingDramaJobOut:
    job = await session.get(StarlingDramaJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _job_to_out(job, settings)


@router.post(
    "/{job_id}/retry",
    response_model=StarlingDramaJobOut,
    dependencies=[Depends(require_passphrase)],
)
async def retry_starling_drama_job(
    job_id: str,
    payload: StarlingDramaRerunRequest | None = None,
    background_tasks: BackgroundTasks = None,
    request: Request = None,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> StarlingDramaJobOut:
    job = await session.get(StarlingDramaJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status not in ("failed", "completed"):
        raise HTTPException(status_code=409, detail=f"任务状态 {job.status} 不可重试")

    # 重置 items：保留已成功的，重置失败的
    items = json.loads(job.items_json or "[]")
    target_langs = _parse_target_langs(job)
    episode_filter = set(payload.episode_indexes) if payload and payload.episode_indexes else None
    for it in items:
        if episode_filter is not None and it.get("episode_number") not in episode_filter:
            continue
        if it.get("status") == "failed":
            it["status"] = "pending"
            it["error"] = None
            it["starling_video_id"] = None
            it["upload_batch_id"] = None
            it["upload_status"] = None
            for lang in target_langs:
                t = it.setdefault("translations", {}).setdefault(lang, {})
                t["starling_subtask_id"] = None
                t["ai_flow_status"] = None
                t["submit_status"] = None
                t["suppression_status"] = None
                t["products"] = {}
                t["error_message"] = None
    job.items_json = json.dumps(items, ensure_ascii=False)
    job.status = "pending"
    job.progress_message = "重试中"
    job.error_message = None
    job.completed_at = None
    await session.commit()
    await session.refresh(job)

    state = request.app.state

    async def _runner() -> None:
        await run_starling_drama_job(state.db, state.settings, job.id)

    background_tasks.add_task(_runner)
    return _job_to_out(job, settings)


@router.post(
    "/{job_id}/stop",
    response_model=StarlingDramaJobOut,
    dependencies=[Depends(require_passphrase)],
)
async def stop_starling_drama_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> StarlingDramaJobOut:
    job = await session.get(StarlingDramaJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status not in ("pending", "running"):
        raise HTTPException(status_code=409, detail=f"任务状态 {job.status} 不可停止")
    job.status = "failed"
    job.error_message = "用户主动停止"
    job.completed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(job)
    return _job_to_out(job, settings)
