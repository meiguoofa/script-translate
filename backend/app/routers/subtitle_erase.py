import json
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session, get_settings, require_passphrase
from app.models import AppSetting, VideoSubtitleEraseJob
from app.schemas import (
    SubtitleEraseAbortMultipartRequest,
    SubtitleEraseAbortMultipartResponse,
    SubtitleEraseCompleteMultipartRequest,
    SubtitleEraseCompleteMultipartResponse,
    SubtitleEraseJobCreateRequest,
    SubtitleEraseJobItemOut,
    SubtitleEraseJobOut,
    SubtitleEraseJobSummary,
    SubtitleEraseMultipartPartInfo,
    SubtitleEraseMultipartUploadUrlRequest,
    SubtitleEraseMultipartUploadUrlResponse,
    SubtitleEraseRerunRequest,
    SubtitleEraseUploadEntry,
    SubtitleEraseUploadUrlRequest,
    SubtitleEraseUploadUrlResponse,
)
from app.services.aliyun_oss_client import AliyunOSSClient
from app.services.subtitle_erase_translate_runner import (
    RETRY_FIELDS,
    TRANSLATION_FIELDS,
    run_subtitle_erase_translate_job,
)
from app.services.zombie_cleanup import ABORT_ERROR_MSG

router = APIRouter(prefix="/subtitle-erase", tags=["subtitle-erase"])

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(name: str) -> str:
    base = name.strip().replace("\\", "/").split("/")[-1] or "video"
    return _SAFE_NAME.sub("_", base)


def _oss_uri_to_public_url(oss_uri: str | None, settings) -> str | None:
    """`oss://bucket/key` -> 公开可读的 HTTPS URL。

    字幕擦除输出 bucket 已配置公开读取(与 clean_video_public_url 同前缀),
    因此 SRT 等产物可直接构造 public URL 供前端下载,无需 presigned GET。
    """

    if not oss_uri or not oss_uri.startswith("oss://"):
        return None
    try:
        _, key = AliyunOSSClient.parse_oss_uri(oss_uri)
    except ValueError:
        return None
    if not key:
        return None
    encoded = "/".join(quote(p, safe="") for p in key.split("/"))
    return f"https://{settings.aliyun_oss_bucket}.{settings.aliyun_oss_endpoint}/{encoded}"


def _items_counts(items: list[dict]) -> tuple[int, int]:
    succeeded = sum(1 for it in items if it.get("status") == "succeeded")
    failed = sum(1 for it in items if it.get("status") == "failed")
    return succeeded, failed


def _items_stats(items: list[dict]) -> dict:
    """汇总统计: 成功/失败/已擦除/已提取字幕/总时长。"""
    succeeded = sum(1 for it in items if it.get("status") == "succeeded")
    failed = sum(1 for it in items if it.get("status") == "failed")
    detexted = sum(1 for it in items if it.get("clean_video_oss_uri"))
    captioned = sum(1 for it in items if it.get("cleaned_srt_oss_uri"))
    total_duration = sum(float(it.get("duration_seconds") or 0) for it in items)
    return {
        "succeeded_count": succeeded,
        "failed_count": failed,
        "detexted_count": detexted,
        "captioned_count": captioned,
        "total_duration_seconds": total_duration,
    }


def _parse_target_langs_for_out(job: VideoSubtitleEraseJob) -> list[str]:
    """从 target_langs_json 解析,失败回退到旧 target_lang 单字段。"""
    if job.target_langs_json:
        try:
            langs = json.loads(job.target_langs_json)
            if isinstance(langs, list) and langs:
                return [str(x) for x in langs if str(x).strip()]
        except json.JSONDecodeError:
            pass
    if job.target_lang:
        return [job.target_lang]
    return []


def _item_translations_to_out(translations: dict | None, settings) -> dict[str, dict]:
    """items_json 内 translations 嵌套 -> SubtitleEraseTranslationItemOut 兼容 dict。"""
    if not isinstance(translations, dict):
        return {}
    out: dict[str, dict] = {}
    for lang, t in translations.items():
        if not isinstance(t, dict):
            continue
        out[lang] = {
            "translated_srt_oss_uri": t.get("translated_srt_oss_uri"),
            "translated_srt_public_url": _oss_uri_to_public_url(
                t.get("translated_srt_oss_uri"), settings
            ),
            "output_video_oss_uri": t.get("output_video_oss_uri"),
            "output_public_url": t.get("output_public_url"),
            "translation_job_id": t.get("translation_job_id"),
            "translation_status": t.get("translation_status"),
            "mps_job_id": t.get("mps_job_id"),
            "burn_ass_oss_uri": t.get("burn_ass_oss_uri"),
            "output_video_tos_uri": t.get("output_video_tos_uri"),
            "output_video_tos_public_url": t.get("output_video_tos_public_url"),
            "output_video_bj_tos_uri": t.get("output_video_bj_tos_uri"),
            "output_video_bj_tos_public_url": t.get("output_video_bj_tos_public_url"),
            "bj_fetch_error": t.get("bj_fetch_error"),
            "stage": t.get("stage", "pending"),
            "status": t.get("status", "pending"),
            "error": t.get("error"),
        }
    return out


def _job_to_out(job: VideoSubtitleEraseJob, settings) -> SubtitleEraseJobOut:
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
    stats = _items_stats(items)
    items_out: list[SubtitleEraseJobItemOut] = []
    for it in items:
        items_out.append(
            SubtitleEraseJobItemOut(
                index=it.get("index", 0),
                drama_index=it.get("drama_index", 0),
                episode_index=it.get("episode_index", 0),
                filename=it.get("filename", ""),
                input_oss_uri=it.get("input_oss_uri", ""),
                input_public_url=it.get("input_public_url", ""),
                caption_job_id=it.get("caption_job_id"),
                caption_status=it.get("caption_status"),
                source_srt_oss_uri=it.get("source_srt_oss_uri"),
                source_srt_public_url=_oss_uri_to_public_url(
                    it.get("source_srt_oss_uri"), settings
                ),
                cleaned_srt_oss_uri=it.get("cleaned_srt_oss_uri"),
                cleaned_srt_public_url=_oss_uri_to_public_url(
                    it.get("cleaned_srt_oss_uri"), settings
                ),
                detext_job_id=it.get("detext_job_id"),
                detext_status=it.get("detext_status"),
                clean_video_oss_uri=it.get("clean_video_oss_uri"),
                clean_video_public_url=it.get("clean_video_public_url"),
                warning=it.get("warning"),
                translations=_item_translations_to_out(it.get("translations"), settings),
                duration_seconds=it.get("duration_seconds"),
                stage=it.get("stage", "pending"),
                status=it.get("status", "pending"),
                error=it.get("error"),
            )
        )
    return SubtitleEraseJobOut(
        id=job.id,
        title=job.title,
        drama_count=job.drama_count,
        video_count=job.video_count,
        detext_mode=job.detext_mode,
        translate_mode=job.translate_mode,
        burn_mode=job.burn_mode,
        placement_mode=job.placement_mode,
        source_lang=job.source_lang,
        target_langs=_parse_target_langs_for_out(job),
        model_provider=job.model_provider,
        model_name=job.model_name,
        qps=job.qps,
        caption_fps=job.caption_fps,
        caption_lang=job.caption_lang,
        caption_track=job.caption_track,
        caption_roi=job.caption_roi,
        caption_sep=job.caption_sep,
        detext_limit_region=job.detext_limit_region,
        burn_font_size=job.burn_font_size,
        burn_font_color=job.burn_font_color,
        burn_font_color_opacity=float(job.burn_font_color_opacity),
        burn_x=float(job.burn_x),
        burn_y=float(job.burn_y),
        burn_text_width=float(job.burn_text_width),
        items=items_out,
        original_filenames=filenames,
        output_oss_prefix=job.output_oss_prefix,
        output_tos_prefix=job.output_tos_prefix,
        status=job.status,
        progress_message=job.progress_message,
        error_message=job.error_message,
        succeeded_count=succeeded,
        failed_count=failed,
        detexted_count=stats["detexted_count"],
        captioned_count=stats["captioned_count"],
        total_duration_seconds=stats["total_duration_seconds"],
        submitted_at=job.submitted_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _job_to_summary(job: VideoSubtitleEraseJob) -> SubtitleEraseJobSummary:
    try:
        items = json.loads(job.items_json or "[]")
    except Exception:
        items = []
    succeeded, failed = _items_counts(items)
    stats = _items_stats(items)
    return SubtitleEraseJobSummary(
        id=job.id,
        title=job.title,
        drama_count=job.drama_count,
        video_count=job.video_count,
        detext_mode=job.detext_mode,
        translate_mode=job.translate_mode,
        burn_mode=job.burn_mode,
        target_langs=_parse_target_langs_for_out(job),
        status=job.status,
        succeeded_count=succeeded,
        failed_count=failed,
        detexted_count=stats["detexted_count"],
        captioned_count=stats["captioned_count"],
        total_duration_seconds=stats["total_duration_seconds"],
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
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
    entries: list[SubtitleEraseUploadEntry] = []
    prefix = settings.oss_subtitle_erase_input_prefix.rstrip("/") or "subtitle-erase-input"
    for index, spec in enumerate(payload.files):
        safe = _safe_filename(spec.filename)
        key = f"{prefix}/{job_id}/{index:02d}-{safe}"
        result = oss.presign_put(key, content_type=spec.content_type, expires_in=expires_in)
        entries.append(
            SubtitleEraseUploadEntry(
                filename=spec.filename,
                presigned_url=result.presigned_url,
                public_url=result.public_url,
                oss_uri=result.oss_uri,
                key=result.key,
            )
        )
    return SubtitleEraseUploadUrlResponse(job_id=job_id, expires_in=expires_in, entries=entries)


@router.post(
    "/upload-multipart-url",
    response_model=SubtitleEraseMultipartUploadUrlResponse,
    dependencies=[Depends(require_passphrase)],
)
async def create_multipart_upload_urls(
    payload: SubtitleEraseMultipartUploadUrlRequest,
    settings=Depends(get_settings),
) -> SubtitleEraseMultipartUploadUrlResponse:
    """大文件分片上传：init_multipart + 为每个 part 签 PUT URL。

    前端按 parts 切片并发 PUT 到 OSS，全部成功后调 /complete-multipart。
    """
    try:
        oss = AliyunOSSClient(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job_id = payload.job_id or str(uuid.uuid4())
    safe = _safe_filename(payload.filename)
    prefix = settings.oss_subtitle_erase_input_prefix.rstrip("/") or "subtitle-erase-input"
    key = f"{prefix}/{job_id}/{payload.index:02d}-{safe}"
    expires_in = 3600
    try:
        result = oss.presign_multipart_put(
            key,
            content_type=payload.content_type,
            file_size=payload.file_size,
            expires_in=expires_in,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"init multipart failed: {exc}") from exc
    return SubtitleEraseMultipartUploadUrlResponse(
        job_id=job_id,
        upload_id=result.upload_id,
        key=result.key,
        oss_uri=result.oss_uri,
        public_url=result.public_url,
        part_size=8 * 1024 * 1024,
        parts=[
            SubtitleEraseMultipartPartInfo(
                part_number=p.part_number,
                offset=p.offset,
                size=p.size,
                presigned_url=p.presigned_url,
            )
            for p in result.parts
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

    sorted_parts = sorted(payload.parts, key=lambda p: p.part_number)
    expected = list(range(1, len(sorted_parts) + 1))
    if [p.part_number for p in sorted_parts] != expected:
        raise HTTPException(status_code=400, detail="part_number 不连续")
    try:
        public_url, oss_uri = oss.complete_multipart(
            payload.key,
            payload.upload_id,
            [
                {"part_number": p.part_number, "etag": p.etag}
                for p in sorted_parts
            ],
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"complete failed: {exc}") from exc
    return SubtitleEraseCompleteMultipartResponse(public_url=public_url, oss_uri=oss_uri)


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
    response_model=SubtitleEraseJobOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_passphrase)],
)
async def create_subtitle_erase_job(
    payload: SubtitleEraseJobCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> SubtitleEraseJobOut:
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    if not payload.items:
        raise HTTPException(status_code=400, detail="视频列表不能为空")
    for it in payload.items:
        if not it.oss_uri.startswith("oss://"):
            raise HTTPException(status_code=400, detail=f"非法的视频 oss_uri: {it.oss_uri}")
    if payload.translate_mode == "llm":
        if not (payload.model_provider and payload.model_name):
            raise HTTPException(
                status_code=400,
                detail="LLM 翻译模式必须提供 model_provider 和 model_name",
            )
    if payload.translate_mode == "aliyun":
        if not payload.source_lang:
            raise HTTPException(
                status_code=400,
                detail="阿里云翻译模式必须提供 source_lang",
            )
        if payload.source_lang == "auto":
            raise HTTPException(
                status_code=400,
                detail="阿里云翻译模式不支持源语言 'auto'：IMS 字幕级翻译必须明确源语言。请选择具体语言，或切换为 LLM 翻译模式",
            )
    if payload.burn_mode == "aliyun":
        # aliyun 烧录需要 IMS SubmitVideoTranslationJob，源语言规则同 aliyun 翻译模式
        if not payload.source_lang or payload.source_lang == "auto":
            raise HTTPException(
                status_code=400,
                detail="阿里云烧录模式（IMS）必须明确 source_lang，不能为 auto",
            )
    # 矛盾组合：aliyun 翻译 + local 烧录。IMS 翻译是和烧录一体的 API，
    # 不可能"IMS 翻译完 SRT 再本地烧录"——IMS 不单独提供翻译 SRT 文本的服务。
    # 真正的边界：translate_mode=aliyun 时只能 burn_mode=aliyun（IMS 一体）；
    # burn_mode=local 时必须 translate_mode=llm（LLM 译 SRT 后本地 ffmpeg 烧录）。
    if payload.translate_mode == "aliyun" and payload.burn_mode == "local":
        raise HTTPException(
            status_code=400,
            detail="阿里云翻译模式必须搭配阿里云烧录（IMS 一体）；本机烧录请选 LLM 翻译模式",
        )

    existing = await session.get(VideoSubtitleEraseJob, payload.job_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="job_id 已存在")

    output_oss_prefix = (
        f"oss://{settings.aliyun_oss_bucket}/"
        f"{settings.oss_subtitle_erase_output_prefix.strip('/') or 'subtitle-erase-output'}/"
        f"{payload.job_id}/"
    )
    output_tos_prefix = (
        f"tos://{settings.tos_sg_bucket}/"
        f"{settings.oss_subtitle_erase_output_prefix.strip('/') or 'subtitle-erase-output'}/"
        f"{payload.job_id}/"
    )

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
                # 跨语言共享产物(擦除 + 字幕提取)
                "caption_job_id": None,
                "caption_status": None,
                "source_srt_oss_uri": None,
                "cleaned_srt_oss_uri": None,
                "detext_job_id": None,
                "detext_status": None,
                "clean_video_oss_uri": None,
                "clean_video_public_url": None,
                "warning": None,
                # 每语言独立产物
                "translations": {},
                # 视频时长(秒),阶段 0 用 ffprobe 探测后填充
                "duration_seconds": None,
                # item 级汇总状态
                "stage": "pending",
                "status": "pending",
                "error": None,
            }
        )

    drama_count = len({it["drama_index"] for it in items})

    job = VideoSubtitleEraseJob(
        id=payload.job_id,
        title=title,
        drama_count=drama_count,
        video_count=len(payload.items),
        detext_mode=payload.detext_mode,
        translate_mode=payload.translate_mode,
        burn_mode=payload.burn_mode,
        placement_mode=payload.placement_mode,
        source_lang=payload.source_lang,
        target_lang=payload.target_langs[0] if payload.target_langs else None,
        target_langs_json=json.dumps(payload.target_langs, ensure_ascii=False),
        model_provider=payload.model_provider,
        model_name=payload.model_name,
        qps=payload.qps,
        caption_fps=payload.caption_fps,
        caption_lang=payload.caption_lang,
        caption_track=payload.caption_track,
        caption_roi=payload.caption_roi,
        caption_sep=payload.caption_sep,
        detext_limit_region=payload.detext_limit_region,
        burn_font_size=payload.burn_font_size,
        burn_font_color=payload.burn_font_color,
        burn_font_color_opacity=payload.burn_font_color_opacity,
        burn_x=payload.burn_x,
        burn_y=payload.burn_y,
        burn_text_width=payload.burn_text_width,
        items_json=json.dumps(items, ensure_ascii=False),
        original_filenames_json=(
            json.dumps(payload.original_filenames, ensure_ascii=False)
            if payload.original_filenames
            else None
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
        await run_subtitle_erase_translate_job(
            state.db,
            state.settings,
            state.registry,
            job.id,
            global_rate_limiter=state.ims_rate_limiter,
        )

    background_tasks.add_task(_runner)
    return _job_to_out(job, settings)


# ===== 表单参数持久化（服务器端，不依赖浏览器 localStorage） =====
# 注意：/settings 必须在 /{job_id} 路由之前声明，否则 FastAPI 会把
# "settings" 当成 job_id 匹配到 GET /{job_id}，返回 404 任务不存在。

SETTINGS_KEY = "subtitle_erase_form_params"


@router.get(
    "/settings",
    response_model=dict,
    dependencies=[Depends(require_passphrase)],
)
async def get_subtitle_erase_settings(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """读取上次保存的表单参数。无记录返回空 dict。"""

    row = await session.get(AppSetting, SETTINGS_KEY)
    if row is None:
        return {}
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return {}


@router.put(
    "/settings",
    response_model=dict,
    dependencies=[Depends(require_passphrase)],
)
async def save_subtitle_erase_settings(
    payload: dict,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """保存表单参数（覆盖式）。前端防抖调用，避免频繁请求。"""

    value = json.dumps(payload, ensure_ascii=False)
    row = await session.get(AppSetting, SETTINGS_KEY)
    if row is None:
        row = AppSetting(key=SETTINGS_KEY, value=value)
        session.add(row)
    else:
        row.value = value
    await session.commit()
    return payload


@router.get("/{job_id}", response_model=SubtitleEraseJobOut)
async def get_subtitle_erase_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> SubtitleEraseJobOut:
    job = await session.get(VideoSubtitleEraseJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _job_to_out(job, settings)


@router.post(
    "/{job_id}/stop",
    response_model=SubtitleEraseJobOut,
    dependencies=[Depends(require_passphrase)],
)
async def stop_running_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> SubtitleEraseJobOut:
    """强制停止 running 状态的任务，标记为 failed 后可调 /retry 重试。"""
    job = await session.get(VideoSubtitleEraseJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status != "running":
        raise HTTPException(
            status_code=400, detail=f"只有 running 状态的任务才能停止（当前: {job.status}）"
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
            # translations 内 running 的也标 failed
            if isinstance(it.get("translations"), dict):
                for t in it["translations"].values():
                    if t.get("status") == "running":
                        t["status"] = "failed"
                        t["error"] = ABORT_ERROR_MSG
    job.items_json = json.dumps(items, ensure_ascii=False)
    await session.commit()
    await session.refresh(job)
    return _job_to_out(job, settings)


@router.post(
    "/{job_id}/retry",
    response_model=SubtitleEraseJobOut,
    dependencies=[Depends(require_passphrase)],
)
async def retry_failed_items(
    job_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> SubtitleEraseJobOut:
    job = await session.get(VideoSubtitleEraseJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    items: list[dict] = json.loads(job.items_json or "[]")
    failed_indices = [i for i, it in enumerate(items) if it.get("status") == "failed"]
    if not failed_indices:
        raise HTTPException(status_code=400, detail="没有可重试的失败项")

    # 只重置失败语言的 translations 子项,保留跨语言共享产物(擦除/字幕提取)
    # 这样 retry 不会重复付费跑擦除和字幕提取
    for idx in failed_indices:
        it = items[idx]
        if not isinstance(it.get("translations"), dict):
            it["translations"] = {}
        for lang, t in it["translations"].items():
            if t.get("status") == "failed":
                for f in TRANSLATION_FIELDS:
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
    await session.commit()
    await session.refresh(job)

    state = request.app.state

    async def _runner() -> None:
        await run_subtitle_erase_translate_job(
            state.db,
            state.settings,
            state.registry,
            job.id,
            only_indices=failed_indices,
            global_rate_limiter=state.ims_rate_limiter,
        )

    background_tasks.add_task(_runner)
    return _job_to_out(job, settings)


@router.post(
    "/{job_id}/rerun-all",
    response_model=SubtitleEraseJobOut,
    dependencies=[Depends(require_passphrase)],
)
async def rerun_all_items(
    job_id: str,
    payload: SubtitleEraseRerunRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
) -> SubtitleEraseJobOut:
    """修改参数并重新运行所有集数（包括已成功的集数）。"""
    job = await session.get(VideoSubtitleEraseJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status not in ("completed", "failed"):
        raise HTTPException(status_code=400, detail="只有已完成或失败的任务才能重新运行")

    # 参数校验（与创建时相同）
    if payload.translate_mode == "llm" and not (payload.model_provider and payload.model_name):
        raise HTTPException(status_code=400, detail="LLM 翻译模式必须提供 model_provider 和 model_name")
    if payload.translate_mode == "aliyun" and (not payload.source_lang or payload.source_lang == "auto"):
        raise HTTPException(status_code=400, detail="阿里云翻译模式必须明确 source_lang，不能为 auto")
    if payload.burn_mode == "aliyun" and (not payload.source_lang or payload.source_lang == "auto"):
        raise HTTPException(status_code=400, detail="阿里云烧录模式必须明确 source_lang，不能为 auto")
    if payload.translate_mode == "aliyun" and payload.burn_mode == "local":
        raise HTTPException(status_code=400, detail="阿里云翻译模式必须搭配阿里云烧录（IMS 一体）")

    # 更新 job 可变参数
    job.detext_mode = payload.detext_mode
    job.translate_mode = payload.translate_mode
    job.burn_mode = payload.burn_mode
    job.placement_mode = payload.placement_mode
    job.source_lang = payload.source_lang
    job.target_lang = payload.target_langs[0] if payload.target_langs else None
    job.target_langs_json = json.dumps(payload.target_langs, ensure_ascii=False)
    job.model_provider = payload.model_provider
    job.model_name = payload.model_name
    job.qps = payload.qps
    job.caption_fps = payload.caption_fps
    job.caption_lang = payload.caption_lang
    job.caption_track = payload.caption_track
    job.caption_roi = payload.caption_roi
    job.caption_sep = payload.caption_sep
    job.detext_limit_region = payload.detext_limit_region
    job.burn_font_size = payload.burn_font_size
    job.burn_font_color = payload.burn_font_color
    job.burn_font_color_opacity = payload.burn_font_color_opacity
    job.burn_x = payload.burn_x
    job.burn_y = payload.burn_y
    job.burn_text_width = payload.burn_text_width

    # 重置所有 items:
    # - force_redetext=True: 清擦除产物(clean_video_oss_uri, detext_*)
    # - force_recaption=True: 清字幕提取产物(source_srt_oss_uri, cleaned_srt_oss_uri, caption_*)
    # - 默认: 共享产物保留(自动复用)
    # - translations 始终重置(用户可能改了 target_langs 或烧录参数)
    # 新增的 target_langs 中,之前没跑过的语言会自动开始;之前跑过的语言被重置重跑
    items: list[dict] = json.loads(job.items_json or "[]")
    new_langs = set(payload.target_langs)
    for item in items:
        if not isinstance(item.get("translations"), dict):
            item["translations"] = {}
        if payload.force_redetext:
            for f in ("detext_job_id", "detext_status", "clean_video_oss_uri", "clean_video_public_url"):
                item[f] = None
        if payload.force_recaption:
            for f in ("caption_job_id", "caption_status", "source_srt_oss_uri", "cleaned_srt_oss_uri"):
                item[f] = None
        item["warning"] = None
        # 删除不在新 target_langs 中的旧语言产物
        for old_lang in list(item["translations"].keys()):
            if old_lang not in new_langs:
                del item["translations"][old_lang]
        # 重置保留语言的 translations(参数可能变了,需重跑)
        for lang in payload.target_langs:
            t = item["translations"].setdefault(lang, {})
            for f in TRANSLATION_FIELDS:
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
        await run_subtitle_erase_translate_job(
            state.db,
            state.settings,
            state.registry,
            job.id,
            global_rate_limiter=state.ims_rate_limiter,
        )

    background_tasks.add_task(_runner)
    return _job_to_out(job, settings)


@router.get("", response_model=list[SubtitleEraseJobSummary])
async def list_subtitle_erase_jobs(
    limit: int = 20,
    offset: int = 0,
    q: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[SubtitleEraseJobSummary]:
    stmt = select(VideoSubtitleEraseJob)
    if q and q.strip():
        stmt = stmt.where(VideoSubtitleEraseJob.title.ilike(f"%{q.strip()}%"))
    stmt = stmt.order_by(VideoSubtitleEraseJob.created_at.desc()).limit(limit).offset(offset)
    rows = await session.scalars(stmt)
    return [_job_to_summary(j) for j in rows]
