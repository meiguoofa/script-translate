from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session, get_settings, require_passphrase
from app.models import AppSetting, VideoBaiduVodJob
from app.schemas import (
    BaiduVodAbortMultipartRequest,
    BaiduVodAbortMultipartResponse,
    BaiduVodCompleteMultipartRequest,
    BaiduVodCompleteMultipartResponse,
    BaiduVodJobCreateRequest,
    BaiduVodJobItemOut,
    BaiduVodJobOut,
    BaiduVodJobSummary,
    BaiduVodMultipartPartInfo,
    BaiduVodMultipartUploadUrlRequest,
    BaiduVodMultipartUploadUrlResponse,
    BaiduVodRerunRequest,
    BaiduVodRuntimeLimitsOut,
    BaiduVodUploadEntry,
    BaiduVodUploadUrlRequest,
    BaiduVodUploadUrlResponse,
)
from app.config import Settings
from app.services.baidu_bos_client import BaiduBOSClient
from app.services.baidu_vod_runner import run_baidu_vod_job
from app.services.zombie_cleanup import ABORT_ERROR_MSG

router = APIRouter(prefix="/baidu-vod", tags=["baidu-vod"])

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(name: str) -> str:
    base = name.strip().replace("\\", "/").split("/")[-1] or "video"
    return _SAFE_NAME.sub("_", base)


def _build_subtitle_config(payload) -> dict:
    """构造 subtitleConfig。

    fontConfig 嵌套在 text type 下(如 "dialog"),百度 API 要求 camelCase 键;
    扁平 snake_case 会被百度忽略,导致译文烧录位置/样式退回默认,
    译文落在原字幕擦除区上方(出现"译文压在黑矩形上"的视觉问题)。
    desubtitle_enabled=False 时不发 desubtitleConfig(关闭擦除)。
    """
    font = payload.font_config
    subtitle_config: dict = {
        "recognitionType": payload.recognition_type,
        "textTypeList": payload.text_type_list,
        "targetSubtitleCompose": payload.target_subtitle_compose,
        "fontConfig": {
            "dialog": {
                "padding": font.padding,
                "color": "#00000000",  # 透明背景,避免译文带黑框
                "font": {
                    "family": font.family,
                    "alignment": font.alignment,
                    "size": font.size,
                    "bold": font.bold,
                    "color": font.color,
                    "outlineThickness": font.outline_thickness,
                    "outlineColor": font.outline_color,
                },
            },
        },
    }
    if payload.desubtitle_enabled:
        subtitle_config["desubtitleConfig"] = {
            "modelType": payload.desubtitle_model,
            "desubtitleType": payload.desubtitle_type,
        }
    if payload.ocr_area_list:
        subtitle_config["ocrConfig"] = {
            "areaList": [a.model_dump() for a in payload.ocr_area_list],
        }
    return subtitle_config


def _items_counts(items: list[dict]) -> tuple[int, int]:
    succeeded = sum(1 for it in items if it.get("status") == "succeeded")
    failed = sum(1 for it in items if it.get("status") == "failed")
    return succeeded, failed


def _items_stats(items: list[dict]) -> dict:
    succeeded = sum(1 for it in items if it.get("status") == "succeeded")
    failed = sum(1 for it in items if it.get("status") == "failed")
    registered = sum(1 for it in items if it.get("baidu_media_id"))
    total_duration = sum(float(it.get("duration_seconds") or 0) for it in items)
    return {
        "succeeded_count": succeeded,
        "failed_count": failed,
        "registered_count": registered,
        "total_duration_seconds": total_duration,
    }


def _parse_target_langs(job: VideoBaiduVodJob) -> list[str]:
    try:
        langs = json.loads(job.target_langs_json or "[]")
        if isinstance(langs, list) and langs:
            return [str(x) for x in langs if str(x).strip()]
    except json.JSONDecodeError:
        pass
    return []


def _item_translations_to_out(translations: dict | None) -> dict[str, dict]:
    if not isinstance(translations, dict):
        return {}
    out: dict[str, dict] = {}
    for lang, t in translations.items():
        if not isinstance(t, dict):
            continue
        out[lang] = {
            "baidu_task_id": t.get("baidu_task_id"),
            "status": t.get("status", "pending"),
            "stage": t.get("stage", "pending"),
            "error": t.get("error"),
            "final_video_url": t.get("final_video_url"),
            "desubtitle_video_url": t.get("desubtitle_video_url"),
            "cover_url": t.get("cover_url"),
            "source_srt_url": t.get("source_srt_url"),
            "target_srt_url": t.get("target_srt_url"),
        }
    return out


def _job_to_out(job: VideoBaiduVodJob) -> BaiduVodJobOut:
    try:
        items = json.loads(job.items_json or "[]")
    except Exception:
        items = []
    try:
        filenames = json.loads(job.original_filenames_json) if job.original_filenames_json else None
    except Exception:
        filenames = None
    succeeded, failed = _items_counts(items)
    stats = _items_stats(items)
    items_out: list[BaiduVodJobItemOut] = []
    for it in items:
        items_out.append(
            BaiduVodJobItemOut(
                index=it.get("index", 0),
                drama_index=it.get("drama_index", 0),
                episode_index=it.get("episode_index", 0),
                filename=it.get("filename", ""),
                input_oss_uri=it.get("input_oss_uri", ""),
                input_public_url=it.get("input_public_url", ""),
                input_bos_key=it.get("input_bos_key"),
                input_bos_uri=it.get("input_bos_uri"),
                baidu_media_id=it.get("baidu_media_id"),
                baidu_upload_task_id=it.get("baidu_upload_task_id"),
                duration_seconds=it.get("duration_seconds"),
                warning=it.get("warning"),
                translations=_item_translations_to_out(it.get("translations")),
                stage=it.get("stage", "pending"),
                status=it.get("status", "pending"),
                error=it.get("error"),
            )
        )
    try:
        translation_config = json.loads(job.translation_config_json or "{}")
        subtitle_config = json.loads(job.subtitle_config_json or "{}")
    except json.JSONDecodeError:
        translation_config = {}
        subtitle_config = {}
    return BaiduVodJobOut(
        id=job.id,
        title=job.title,
        drama_count=job.drama_count,
        video_count=job.video_count,
        baidu_project_id=job.baidu_project_id,
        project_type=job.project_type,
        source_language=job.source_language,
        target_langs=_parse_target_langs(job),
        translation_config=translation_config,
        subtitle_config=subtitle_config,
        qps=job.qps,
        items=items_out,
        original_filenames=filenames,
        output_bos_prefix=job.output_bos_prefix,
        status=job.status,
        progress_message=job.progress_message,
        error_message=job.error_message,
        succeeded_count=succeeded,
        failed_count=failed,
        registered_count=stats["registered_count"],
        total_duration_seconds=stats["total_duration_seconds"],
        submitted_at=job.submitted_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _job_to_summary(job: VideoBaiduVodJob) -> BaiduVodJobSummary:
    try:
        items = json.loads(job.items_json or "[]")
    except Exception:
        items = []
    succeeded, failed = _items_counts(items)
    stats = _items_stats(items)
    return BaiduVodJobSummary(
        id=job.id,
        title=job.title,
        drama_count=job.drama_count,
        video_count=job.video_count,
        project_type=job.project_type,
        source_language=job.source_language,
        target_langs=_parse_target_langs(job),
        status=job.status,
        succeeded_count=succeeded,
        failed_count=failed,
        registered_count=stats["registered_count"],
        total_duration_seconds=stats["total_duration_seconds"],
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post(
    "/upload-url",
    response_model=BaiduVodUploadUrlResponse,
    dependencies=[Depends(require_passphrase)],
)
async def create_upload_urls(
    payload: BaiduVodUploadUrlRequest,
    settings=Depends(get_settings),
) -> BaiduVodUploadUrlResponse:
    if not payload.files:
        raise HTTPException(status_code=400, detail="文件列表不能为空")
    try:
        bos = BaiduBOSClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job_id = payload.job_id or str(uuid.uuid4())
    expires_in = 3600
    entries: list[BaiduVodUploadEntry] = []
    prefix = settings.baidu_vod_input_prefix.rstrip("/") or "baidu-vod-input"
    for index, spec in enumerate(payload.files):
        safe = _safe_filename(spec.filename)
        key = f"{prefix}/{job_id}/{index:02d}-{safe}"
        result = bos.presign_put(key, content_type=spec.content_type, expires_in=expires_in)
        entries.append(
            BaiduVodUploadEntry(
                filename=spec.filename,
                presigned_url=result.presigned_url,
                public_url=result.public_url,
                bos_uri=result.bos_uri,
                key=result.key,
            )
        )
    return BaiduVodUploadUrlResponse(job_id=job_id, expires_in=expires_in, entries=entries)


@router.post(
    "/upload-multipart-url",
    response_model=BaiduVodMultipartUploadUrlResponse,
    dependencies=[Depends(require_passphrase)],
)
async def create_multipart_upload(
    payload: BaiduVodMultipartUploadUrlRequest,
    settings=Depends(get_settings),
) -> BaiduVodMultipartUploadUrlResponse:
    try:
        bos = BaiduBOSClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job_id = payload.job_id or str(uuid.uuid4())
    safe = _safe_filename(payload.filename)
    prefix = settings.baidu_vod_input_prefix.rstrip("/") or "baidu-vod-input"
    key = f"{prefix}/{job_id}/{payload.index:02d}-{safe}"
    expires_in = 3600
    try:
        result = bos.presign_multipart_put(
            key, content_type=payload.content_type, file_size=payload.file_size,
            expires_in=expires_in,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"init multipart failed: {exc}") from exc
    return BaiduVodMultipartUploadUrlResponse(
        job_id=job_id,
        upload_id=result.upload_id,
        key=result.key,
        bos_uri=result.bos_uri,
        public_url=result.public_url,
        part_size=8 * 1024 * 1024,
        parts=[
            BaiduVodMultipartPartInfo(
                part_number=p.part_number, offset=p.offset, size=p.size,
                presigned_url=p.presigned_url,
            )
            for p in result.parts
        ],
        expires_in=expires_in,
    )


@router.post(
    "/complete-multipart",
    response_model=BaiduVodCompleteMultipartResponse,
    dependencies=[Depends(require_passphrase)],
)
async def complete_multipart(
    payload: BaiduVodCompleteMultipartRequest,
    settings=Depends(get_settings),
) -> BaiduVodCompleteMultipartResponse:
    try:
        bos = BaiduBOSClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    sorted_parts = sorted(payload.parts, key=lambda p: p.part_number)
    expected = list(range(1, len(sorted_parts) + 1))
    if [p.part_number for p in sorted_parts] != expected:
        raise HTTPException(status_code=400, detail="part_number 不连续")
    try:
        public_url, bos_uri = bos.complete_multipart(
            payload.key, payload.upload_id,
            [{"part_number": p.part_number, "etag": p.etag} for p in sorted_parts],
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"complete failed: {exc}") from exc
    return BaiduVodCompleteMultipartResponse(public_url=public_url, bos_uri=bos_uri)


@router.post(
    "/abort-multipart",
    response_model=BaiduVodAbortMultipartResponse,
    dependencies=[Depends(require_passphrase)],
)
async def abort_multipart(
    payload: BaiduVodAbortMultipartRequest,
    settings=Depends(get_settings),
) -> BaiduVodAbortMultipartResponse:
    try:
        bos = BaiduBOSClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    bos.abort_multipart(payload.key, payload.upload_id)
    return BaiduVodAbortMultipartResponse(ok=True)


@router.post(
    "",
    response_model=BaiduVodJobOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_passphrase)],
)
async def create_baidu_vod_job(
    payload: BaiduVodJobCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> BaiduVodJobOut:
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    if not payload.items:
        raise HTTPException(status_code=400, detail="视频列表不能为空")
    for it in payload.items:
        if not it.oss_uri.startswith("bos://"):
            raise HTTPException(status_code=400, detail=f"非法的视频 bos_uri: {it.oss_uri}")

    existing = await session.get(VideoBaiduVodJob, payload.job_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="job_id 已存在")

    output_bos_prefix = (
        f"bos://{settings.baidu_bos_bucket}/"
        f"{settings.baidu_vod_input_prefix.strip('/') or 'baidu-vod-input'}/"
        f"{payload.job_id}/"
    )

    items: list[dict] = []
    for index, spec in enumerate(payload.items):
        items.append({
            "index": index,
            "drama_index": spec.drama_index,
            "episode_index": spec.episode_index,
            "filename": spec.filename,
            "input_oss_uri": spec.oss_uri,
            "input_public_url": spec.public_url,
            "input_bos_key": spec.key,
            "input_bos_uri": spec.oss_uri,
            "baidu_media_id": None,
            "baidu_upload_task_id": None,
            "duration_seconds": None,
            "warning": None,
            "translations": {},
            "stage": "pending",
            "status": "pending",
            "error": None,
        })

    drama_count = len({it["drama_index"] for it in items})

    translation_config = {
        "translationTypeList": payload.translation_type_list,
        "voiceMode": payload.voice_mode,
        "voiceList": payload.voice_list,
    }
    subtitle_config = _build_subtitle_config(payload)

    job = VideoBaiduVodJob(
        id=payload.job_id,
        title=title,
        drama_count=drama_count,
        video_count=len(payload.items),
        baidu_project_id=None,  # runner 创建
        project_type=payload.project_type,
        source_language=payload.source_language,
        target_langs_json=json.dumps(payload.target_langs, ensure_ascii=False),
        translation_config_json=json.dumps(translation_config, ensure_ascii=False),
        subtitle_config_json=json.dumps(subtitle_config, ensure_ascii=False),
        items_json=json.dumps(items, ensure_ascii=False),
        original_filenames_json=(
            json.dumps(payload.original_filenames, ensure_ascii=False)
            if payload.original_filenames else None
        ),
        output_bos_prefix=output_bos_prefix,
        qps=settings.baidu_vod_global_qps,
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    state = request.app.state

    async def _runner() -> None:
        await run_baidu_vod_job(
            state.db,
            state.settings,
            state.baidu_vod_governor,
            job.id,
        )

    background_tasks.add_task(_runner)
    return _job_to_out(job)


# ===== 表单参数持久化 =====
SETTINGS_KEY = "baidu_vod_form_params"


@router.get(
    "/settings",
    response_model=dict,
    dependencies=[Depends(require_passphrase)],
)
async def get_baidu_vod_settings(
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await session.get(AppSetting, SETTINGS_KEY)
    if row is None:
        return {}
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return {}


@router.get(
    "/runtime-limits",
    response_model=BaiduVodRuntimeLimitsOut,
    dependencies=[Depends(require_passphrase)],
)
async def get_baidu_vod_runtime_limits(request: Request) -> BaiduVodRuntimeLimitsOut:
    return BaiduVodRuntimeLimitsOut(
        **request.app.state.baidu_vod_governor.runtime_limits
    )


@router.put(
    "/settings",
    response_model=dict,
    dependencies=[Depends(require_passphrase)],
)
async def save_baidu_vod_settings(
    payload: dict,
    session: AsyncSession = Depends(get_session),
) -> dict:
    value = json.dumps(payload, ensure_ascii=False)
    row = await session.get(AppSetting, SETTINGS_KEY)
    if row is None:
        row = AppSetting(key=SETTINGS_KEY, value=value)
        session.add(row)
    else:
        row.value = value
    await session.commit()
    return payload


@router.get("/{job_id}", response_model=BaiduVodJobOut)
async def get_baidu_vod_job(
    job_id: str, session: AsyncSession = Depends(get_session)
) -> BaiduVodJobOut:
    job = await session.get(VideoBaiduVodJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _job_to_out(job)


@router.post(
    "/{job_id}/stop",
    response_model=BaiduVodJobOut,
    dependencies=[Depends(require_passphrase)],
)
async def stop_running_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> BaiduVodJobOut:
    job = await session.get(VideoBaiduVodJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status != "running":
        raise HTTPException(
            status_code=400, detail=f"只有 running 状态的任务才能停止(当前: {job.status})"
        )
    job.status = "failed"
    job.error_message = ABORT_ERROR_MSG
    if job.completed_at is None:
        job.completed_at = datetime.now(timezone.utc)
    items: list[dict] = json.loads(job.items_json or "[]")
    for it in items:
        if it.get("status") == "running":
            it["status"] = "failed"
            it["error"] = ABORT_ERROR_MSG
            if isinstance(it.get("translations"), dict):
                for t in it["translations"].values():
                    if t.get("status") == "running":
                        t["status"] = "failed"
                        t["error"] = ABORT_ERROR_MSG
    job.items_json = json.dumps(items, ensure_ascii=False)
    await session.commit()
    await session.refresh(job)
    return _job_to_out(job)


@router.post(
    "/{job_id}/retry",
    response_model=BaiduVodJobOut,
    dependencies=[Depends(require_passphrase)],
)
async def retry_failed_items(
    job_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> BaiduVodJobOut:
    job = await session.get(VideoBaiduVodJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    items: list[dict] = json.loads(job.items_json or "[]")
    failed_indices = [i for i, it in enumerate(items) if it.get("status") == "failed"]
    if not failed_indices:
        raise HTTPException(status_code=400, detail="没有可重试的失败项")

    # 只重置失败语言的失败 task,保留 media_id(不重新 fetch)
    for idx in failed_indices:
        it = items[idx]
        if not isinstance(it.get("translations"), dict):
            it["translations"] = {}
        # 如果 fetch_media 失败(没有 baidu_media_id),清掉旧 upload_task_id,
        # runner 会重新走 fetch_media 流程(用 presigned GET URL)。
        if not it.get("baidu_media_id"):
            it["baidu_upload_task_id"] = None
        for lang, t in it["translations"].items():
            if t.get("status") == "failed":
                # 清旧 task 产物,保留 media_id
                for f in ("baidu_task_id", "final_video_url", "desubtitle_video_url",
                          "cover_url", "source_srt_url", "target_srt_url"):
                    t[f] = None
                t["status"] = "pending"
                t["stage"] = "pending"
                t["error"] = None
        it["status"] = "pending"
        it["stage"] = "pending"
        it["error"] = None
    job.items_json = json.dumps(items, ensure_ascii=False)
    job.status = "pending"
    job.progress_message = "排队中"
    job.error_message = None
    job.completed_at = None
    job.qps = settings.baidu_vod_global_qps
    await session.commit()
    await session.refresh(job)

    state = request.app.state

    async def _runner() -> None:
        await run_baidu_vod_job(
            state.db,
            state.settings,
            state.baidu_vod_governor,
            job.id,
            only_indices=failed_indices,
        )

    background_tasks.add_task(_runner)
    return _job_to_out(job)


@router.post(
    "/{job_id}/rerun-all",
    response_model=BaiduVodJobOut,
    dependencies=[Depends(require_passphrase)],
)
async def rerun_all_items(
    job_id: str,
    payload: BaiduVodRerunRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> BaiduVodJobOut:
    job = await session.get(VideoBaiduVodJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status not in ("completed", "failed"):
        raise HTTPException(status_code=400, detail="只有已完成或失败的任务才能重新运行")

    job.project_type = payload.project_type
    job.source_language = payload.source_language
    job.target_langs_json = json.dumps(payload.target_langs, ensure_ascii=False)
    translation_config = {
        "translationTypeList": payload.translation_type_list,
        "voiceMode": payload.voice_mode,
        "voiceList": payload.voice_list,
    }
    subtitle_config = _build_subtitle_config(payload)
    job.translation_config_json = json.dumps(translation_config, ensure_ascii=False)
    job.subtitle_config_json = json.dumps(subtitle_config, ensure_ascii=False)
    job.qps = settings.baidu_vod_global_qps

    # force_reregister=True 时清 media_id(重新 fetch);否则保留
    items: list[dict] = json.loads(job.items_json or "[]")
    new_langs = set(payload.target_langs)
    for item in items:
        if not isinstance(item.get("translations"), dict):
            item["translations"] = {}
        if payload.force_reregister:
            item["baidu_media_id"] = None
            item["baidu_upload_task_id"] = None
        # 删除不在新 target_langs 中的旧语言产物
        for old_lang in list(item["translations"].keys()):
            if old_lang not in new_langs:
                del item["translations"][old_lang]
        # 重置保留语言的 translations(重新提交 task)
        for lang in payload.target_langs:
            t = item["translations"].setdefault(lang, {})
            for f in ("baidu_task_id", "final_video_url", "desubtitle_video_url",
                      "cover_url", "source_srt_url", "target_srt_url"):
                t[f] = None
            t["status"] = "pending"
            t["stage"] = "pending"
            t["error"] = None
        item["status"] = "pending"
        item["stage"] = "pending"
        item["error"] = None
    job.items_json = json.dumps(items, ensure_ascii=False)
    job.status = "pending"
    job.progress_message = "排队中"
    job.error_message = None
    job.submitted_at = None
    job.completed_at = None
    await session.commit()
    await session.refresh(job)

    state = request.app.state

    async def _runner() -> None:
        await run_baidu_vod_job(
            state.db,
            state.settings,
            state.baidu_vod_governor,
            job.id,
        )

    background_tasks.add_task(_runner)
    return _job_to_out(job)


@router.get("", response_model=list[BaiduVodJobSummary])
async def list_baidu_vod_jobs(
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> list[BaiduVodJobSummary]:
    rows = await session.scalars(
        select(VideoBaiduVodJob)
        .order_by(VideoBaiduVodJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_job_to_summary(j) for j in rows]
