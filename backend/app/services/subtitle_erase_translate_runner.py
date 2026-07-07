from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.db import Database
from app.llm.registry import ProviderRegistry
from app.models import VideoSubtitleEraseJob
from app.services.aliyun_oss_client import AliyunOSSClient
from app.services.ffmpeg_burn import burn_subtitles, probe_video_size
from app.services.ims_client import IMSClient
from app.services.mps_client import MPSClient
from app.services.rate_limiter import RateLimiter
from app.services.srt_cleaner import clean_srt
from app.services.srt_utils import parse_srt, srt_to_ass
from app.services.subtitle_translator import translate_srt
from app.services.tos_fetch_client import TOSFetchClient
from app.services.tos_singapore_client import TOSSingaporeClient

logger = logging.getLogger("subtitle_erase_translate_runner")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(name: str) -> str:
    base = name.strip().replace("\\", "/").split("/")[-1] or "video"
    return _SAFE_NAME.sub("_", base)


def _strip_ext(name: str) -> str:
    return re.sub(r"\.[^.]+$", "", name) or name


# items_json 中需要 reset 的中间字段
RETRY_FIELDS = (
    "caption_job_id",
    "caption_status",
    "source_srt_oss_uri",
    "cleaned_srt_oss_uri",
    "translated_srt_oss_uri",
    "detext_job_id",
    "detext_status",
    "clean_video_oss_uri",
    "translation_job_id",
    "translation_status",
    "output_video_oss_uri",
    "output_public_url",
    "output_video_tos_uri",
    "output_video_tos_public_url",
    "output_video_bj_tos_uri",
    "output_video_bj_tos_public_url",
    "bj_fetch_error",
    "mps_job_id",
    "burn_ass_oss_uri",
    "error",
)


async def _load_snapshot(db: Database, job_id: str) -> dict | None:
    async with await db.session() as session:
        job = await session.get(VideoSubtitleEraseJob, job_id)
        if job is None:
            return None
        return {
            "id": job.id,
            "title": job.title,
            "detext_mode": job.detext_mode,
            "translate_mode": job.translate_mode,
            "burn_mode": job.burn_mode,
            "placement_mode": job.placement_mode,
            "source_lang": job.source_lang,
            "target_lang": job.target_lang,
            "model_provider": job.model_provider,
            "model_name": job.model_name,
            "qps": job.qps,
            "caption_fps": job.caption_fps,
            "caption_lang": job.caption_lang,
            "caption_track": job.caption_track,
            "caption_roi": job.caption_roi,
            "caption_sep": job.caption_sep,
            "detext_limit_region": job.detext_limit_region,
            "burn_font_size": job.burn_font_size,
            "burn_font_color": job.burn_font_color,
            "burn_font_color_opacity": float(job.burn_font_color_opacity),
            "burn_x": float(job.burn_x),
            "burn_y": float(job.burn_y),
            "burn_text_width": float(job.burn_text_width),
            "items": json.loads(job.items_json or "[]"),
            "output_oss_prefix": job.output_oss_prefix,
            "output_tos_prefix": job.output_tos_prefix or "",
        }


_persist_locks: dict[str, asyncio.Lock] = {}


def _get_persist_lock(job_id: str) -> asyncio.Lock:
    lock = _persist_locks.get(job_id)
    if lock is None:
        lock = asyncio.Lock()
        _persist_locks[job_id] = lock
    return lock


async def _persist_items(db: Database, job_id: str, items: list[dict]) -> None:
    # 多 episode 并发时，每个 episode 都会调 _persist_items，需要加锁防止后写覆盖前写
    async with _get_persist_lock(job_id):
        async with await db.session() as session:
            job = await session.get(VideoSubtitleEraseJob, job_id)
            if job is None:
                return
            job.items_json = json.dumps(items, ensure_ascii=False)
            await session.commit()


async def _set_job_fields(
    db: Database,
    job_id: str,
    *,
    status: str | None = None,
    progress_message: str | None = None,
    error_message: str | None = None,
    submitted_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> None:
    async with await db.session() as session:
        job = await session.get(VideoSubtitleEraseJob, job_id)
        if job is None:
            return
        if status is not None:
            job.status = status
        if progress_message is not None:
            job.progress_message = progress_message
        if error_message is not None:
            job.error_message = error_message
        if submitted_at is not None:
            job.submitted_at = submitted_at
        if completed_at is not None:
            job.completed_at = completed_at
        await session.commit()


def _output_key(prefix: str, drama_index: int, episode_index: int, filename: str, ext: str) -> str:
    safe = _safe_filename(filename)
    safe = _strip_ext(safe)
    return f"{prefix.rstrip('/')}/drama-{drama_index:02d}/ep{episode_index:02d}-{safe}.{ext}"


def _parse_roi(roi_str: str | None) -> list[list[float]] | None:
    if not roi_str:
        return None
    try:
        parsed = json.loads(roi_str)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        logger.warning("非法 ROI JSON: %s", roi_str)
    return None


def _parse_limit_region(region_str: str | None) -> list[list[float]] | None:
    return _parse_roi(region_str)


def _output_tos_key(prefix: str, drama_index: int, episode_index: int, filename: str, ext: str) -> str:
    """TOS 输出 key：{prefix}/drama-{di}/ep{ei}-{filename}.{ext}"""

    safe = _safe_filename(filename)
    safe = _strip_ext(safe)
    return f"{prefix.rstrip('/')}/drama-{drama_index:02d}/ep{episode_index:02d}-{safe}.{ext}"


async def _burn_local_and_upload_tos(
    db: Database,
    job_id: str,
    items: list[dict],
    index: int,
    settings: Settings,
    snapshot: dict,
    clean_mp4_oss: str,
    srt_for_burn_text: str,
    drama_index: int,
    episode_index: int,
    filename: str,
    name_prefix: str,
) -> None:
    """本地 ffmpeg 烧录 → 上传 TOS 新加坡 → 删本地临时文件。"""

    item = items[index]
    oss = AliyunOSSClient(settings)
    try:
        tos = TOSSingaporeClient(settings)
    except RuntimeError as exc:
        raise RuntimeError(f"TOS 新加坡客户端初始化失败: {exc}") from exc

    # 北京 TOS fetch client（best-effort，失败不影响 SG 上传和 item 成功）
    try:
        tos_bj = TOSFetchClient(settings)
    except RuntimeError as exc:
        logger.warning("TOS 北京 fetch client 初始化失败，跨区域复制禁用: %s", exc)
        tos_bj = None

    tmp_dir = Path(tempfile.mkdtemp(prefix=f"burn-{job_id}-{index}-"))
    try:
        input_video_tmp = tmp_dir / f"{index:02d}-input.mp4"
        ass_tmp = tmp_dir / f"{index:02d}.ass"
        output_video_tmp = tmp_dir / f"{index:02d}-output.mp4"

        # 1. 从 OSS 下载 clean.mp4 到本地
        _, clean_mp4_key = AliyunOSSClient.parse_oss_uri(clean_mp4_oss)
        await asyncio.to_thread(oss.download_object_to_file, clean_mp4_key, str(input_video_tmp))

        # 2. 探测宽高
        video_w, video_h = await asyncio.to_thread(probe_video_size, str(input_video_tmp))

        # 3. SRT → ASS（用用户自定义烧录参数）
        entries = parse_srt(srt_for_burn_text)
        ass_text = srt_to_ass(
            entries,
            video_w=video_w,
            video_h=video_h,
            placement_mode=snapshot["placement_mode"],
            font_size=snapshot["burn_font_size"],
            font_color=snapshot["burn_font_color"],
            font_color_opacity=snapshot["burn_font_color_opacity"],
            pos_x_ratio=snapshot["burn_x"],
            pos_y_ratio=snapshot["burn_y"],
            text_width_ratio=snapshot["burn_text_width"],
        )
        ass_tmp.write_text(ass_text, encoding="utf-8")

        # 4. ffmpeg 烧录
        await asyncio.to_thread(
            burn_subtitles,
            str(input_video_tmp),
            str(ass_tmp),
            str(output_video_tmp),
            placement_mode=snapshot["placement_mode"],
            video_w=video_w,
            video_h=video_h,
        )

        # 5. 上传到 TOS 新加坡（内网，零带宽）
        output_tos_prefix = snapshot.get("output_tos_prefix") or ""
        if output_tos_prefix.startswith("tos://"):
            _, output_tos_key_prefix = _parse_tos_uri(output_tos_prefix)
        else:
            output_tos_key_prefix = output_tos_prefix.rstrip("/")

        out_key = _output_tos_key(
            output_tos_key_prefix, drama_index, episode_index, filename, "mp4"
        )
        await asyncio.to_thread(tos.upload_file, out_key, str(output_video_tmp), "video/mp4")
        item["output_video_tos_uri"] = tos.tos_uri(out_key)
        item["output_video_tos_public_url"] = tos.public_url(out_key)
        item["translation_status"] = None  # 本地烧录无 IMS 任务
        await _persist_items(db, job_id, items)

        # 5.5 跨区域复制 SG → 北京 TOS（best-effort，失败不影响 item 成功）
        if tos_bj is not None:
            try:
                sg_public_url = item["output_video_tos_public_url"]
                bj_tos_uri, bj_public_url, _bj_size = await asyncio.to_thread(
                    tos_bj.fetch_from_url, out_key, sg_public_url
                )
                item["output_video_bj_tos_uri"] = bj_tos_uri
                item["output_video_bj_tos_public_url"] = bj_public_url
                item["bj_fetch_error"] = None
            except Exception as bj_exc:  # noqa: BLE001
                logger.warning(
                    "BJ fetch failed for %s/%d (SG URL still works): %s",
                    job_id, index, str(bj_exc)[:300]
                )
                item["output_video_bj_tos_uri"] = None
                item["output_video_bj_tos_public_url"] = None
                item["bj_fetch_error"] = str(bj_exc)[:500]
            await _persist_items(db, job_id, items)
    finally:
        # 6. 删除本地临时文件（无论成功失败都删）
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _parse_tos_uri(tos_uri: str) -> tuple[str, str]:
    """`tos://bucket/key1/key2` → (bucket, "key1/key2")。"""

    if not tos_uri.startswith("tos://"):
        raise ValueError(f"非法 TOS URI: {tos_uri}")
    rest = tos_uri[len("tos://"):]
    parts = rest.split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""
    return bucket, key


async def _probe_oss_video_size(oss: AliyunOSSClient, oss_uri: str) -> tuple[int, int]:
    """用 ffprobe 直接探 OSS 公网 HTTPS URL 的视频宽高（不下载到本地）。"""
    _, key = AliyunOSSClient.parse_oss_uri(oss_uri)
    url = oss.public_url(key)
    return await asyncio.to_thread(probe_video_size, url)


async def _run_episode(
    db: Database,
    job_id: str,
    ims: IMSClient,
    oss: AliyunOSSClient,
    registry: ProviderRegistry | None,
    settings: Settings,
    snapshot: dict,
    items: list[dict],
    index: int,
) -> None:
    """单集流水线：提取 → 擦除 → 清洗 → 翻译 → 烧录 → 输出。"""

    item = items[index]
    drama_index = item.get("drama_index", 0)
    episode_index = item.get("episode_index", 0)
    filename = item.get("filename", "")
    input_oss_uri = item["input_oss_uri"]

    output_prefix_uri = snapshot["output_oss_prefix"].rstrip("/")
    if output_prefix_uri.startswith("oss://"):
        _, output_prefix_key = AliyunOSSClient.parse_oss_uri(output_prefix_uri)
    else:
        output_prefix_key = output_prefix_uri

    input_bucket, input_key = AliyunOSSClient.parse_oss_uri(input_oss_uri)
    # IMS 要求 OSS URI 形如 oss://bucket/key
    input_oss_for_ims = input_oss_uri

    target_lang = snapshot["target_lang"]
    source_srt_oss = (
        f"oss://{oss.bucket_name}/"
        f"{_output_key(output_prefix_key, drama_index, episode_index, filename, 'source.srt')}"
    )
    cleaned_srt_oss = (
        f"oss://{oss.bucket_name}/"
        f"{_output_key(output_prefix_key, drama_index, episode_index, filename, 'clean.srt')}"
    )
    translated_srt_name = f"{target_lang}.srt"
    translated_srt_oss = (
        f"oss://{oss.bucket_name}/"
        f"{_output_key(output_prefix_key, drama_index, episode_index, filename, translated_srt_name)}"
    )
    clean_mp4_oss = (
        f"oss://{oss.bucket_name}/"
        f"{_output_key(output_prefix_key, drama_index, episode_index, filename, 'clean.mp4')}"
    )
    output_mp4_oss = (
        f"oss://{oss.bucket_name}/"
        f"{_output_key(output_prefix_key, drama_index, episode_index, filename, 'output.mp4')}"
    )

    name_prefix = f"{job_id[:8]}-d{drama_index:02d}-e{episode_index:02d}"

    # ===== 阶段 1：并行提交字幕提取 + 字幕擦除 =====
    item["stage"] = "extracting"
    item["status"] = "running"
    item["error"] = None
    await _persist_items(db, job_id, items)

    roi = _parse_roi(snapshot.get("caption_roi"))
    limit_region = _parse_limit_region(snapshot.get("detext_limit_region"))
    detext_model_id = "algo-video-detext-new" if snapshot["detext_mode"] == "advanced" else None

    try:
        caption_submit, detext_submit = await asyncio.gather(
            ims.submit_caption_extraction(
                input_oss_uri=input_oss_for_ims,
                output_srt_oss_uri=source_srt_oss,
                name=f"{name_prefix}-cap",
                fps=snapshot["caption_fps"],
                lang=snapshot["caption_lang"],
                track=snapshot["caption_track"],
                roi=roi,
                sep=snapshot["caption_sep"],
            ),
            ims.submit_video_detext(
                input_oss_uri=input_oss_for_ims,
                output_mp4_oss_uri=clean_mp4_oss,
                name=f"{name_prefix}-detext",
                model_id=detext_model_id,
                limit_region=limit_region,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("submit %s/%d failed", job_id, index)
        item["status"] = "failed"
        item["error"] = f"提交失败: {exc}"
        await _persist_items(db, job_id, items)
        return

    item["caption_job_id"] = caption_submit.job_id
    item["caption_status"] = "PROCESSING"
    item["detext_job_id"] = detext_submit.job_id
    item["detext_status"] = "PROCESSING"
    await _persist_items(db, job_id, items)

    # ===== 阶段 2：并行轮询两个 IProduction 任务 =====
    try:
        caption_final, detext_final = await asyncio.gather(
            ims.wait_for_iproduction_job(
                caption_submit.job_id,
                poll_interval_seconds=settings.ims_poll_interval_seconds,
                timeout_seconds=settings.ims_poll_timeout_seconds,
            ),
            ims.wait_for_iproduction_job(
                detext_submit.job_id,
                poll_interval_seconds=settings.ims_poll_interval_seconds,
                timeout_seconds=settings.ims_poll_timeout_seconds,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("iproduction poll %s/%d failed", job_id, index)
        item["status"] = "failed"
        item["error"] = f"提取/擦除任务失败: {exc}"
        await _persist_items(db, job_id, items)
        return

    item["caption_status"] = caption_final.status
    item["detext_status"] = detext_final.status
    item["source_srt_oss_uri"] = source_srt_oss
    item["clean_video_oss_uri"] = clean_mp4_oss
    await _persist_items(db, job_id, items)

    # ===== 阶段 3：下载源 SRT → 清洗 → 上传 clean SRT =====
    item["stage"] = "cleaning"
    await _persist_items(db, job_id, items)

    try:
        _, source_srt_key = AliyunOSSClient.parse_oss_uri(source_srt_oss)
        source_srt_text = await asyncio.to_thread(oss.get_object_text, source_srt_key)
        cleaned_srt_text = clean_srt(source_srt_text)
        _, cleaned_srt_key = AliyunOSSClient.parse_oss_uri(cleaned_srt_oss)
        await asyncio.to_thread(oss.put_object_text, cleaned_srt_key, cleaned_srt_text)
        item["cleaned_srt_oss_uri"] = cleaned_srt_oss
        await _persist_items(db, job_id, items)
    except Exception as exc:  # noqa: BLE001
        logger.exception("srt clean %s/%d failed", job_id, index)
        item["status"] = "failed"
        item["error"] = f"SRT 清洗失败: {exc}"
        await _persist_items(db, job_id, items)
        return

    # ===== 阶段 4：翻译 =====
    item["stage"] = "translating"
    await _persist_items(db, job_id, items)

    srt_for_burn_oss = cleaned_srt_oss
    srt_for_burn_text = cleaned_srt_text
    source_lang_for_ims = snapshot.get("source_lang") or "auto"
    # target_lang already defined above

    if snapshot["translate_mode"] == "llm":
        try:
            if registry is None:
                raise RuntimeError("翻译注册表未初始化")
            if not (snapshot.get("model_provider") and snapshot.get("model_name")):
                raise RuntimeError("LLM 翻译模式缺少 model_provider / model_name")

            translated_text = await translate_srt(
                cleaned_srt_text,
                registry=registry,
                model_provider=snapshot["model_provider"],
                model_name=snapshot["model_name"],
                target_lang=target_lang,
                batch_size=settings.batch_size,
            )
            _, translated_srt_key = AliyunOSSClient.parse_oss_uri(translated_srt_oss)
            await asyncio.to_thread(oss.put_object_text, translated_srt_key, translated_text)
            item["translated_srt_oss_uri"] = translated_srt_oss
            srt_for_burn_oss = translated_srt_oss
            srt_for_burn_text = translated_text
            # LLM 已翻译好，让 IMS 只做烧录（SourceLang = TargetLang）
            source_lang_for_ims = target_lang
            await _persist_items(db, job_id, items)
        except Exception as exc:  # noqa: BLE001
            logger.exception("llm translate %s/%d failed", job_id, index)
            item["status"] = "failed"
            item["error"] = f"LLM 翻译失败: {exc}"
            await _persist_items(db, job_id, items)
            return

    # ===== 阶段 5：烧录 =====
    item["stage"] = "burning"
    await _persist_items(db, job_id, items)

    if snapshot["burn_mode"] == "local":
        # 本地 ffmpeg 烧录 → 上传 TOS 新加坡 → 删本地临时文件
        try:
            await _burn_local_and_upload_tos(
                db, job_id, items, index, settings, snapshot,
                clean_mp4_oss, srt_for_burn_text,
                drama_index, episode_index, filename, name_prefix,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("local burn %s/%d failed", job_id, index)
            item["status"] = "failed"
            item["error"] = f"本地烧录失败: {exc}"
            await _persist_items(db, job_id, items)
            return
    elif snapshot["burn_mode"] == "mps":
        # MPS 烧录：clean.mp4 + ASS → SubmitJobs → output.mp4 直写 OSS
        try:
            video_w, video_h = await _probe_oss_video_size(oss, clean_mp4_oss)
            entries = parse_srt(srt_for_burn_text)
            ass_text = srt_to_ass(
                entries,
                video_w=video_w,
                video_h=video_h,
                placement_mode=snapshot["placement_mode"],
                font_size=snapshot["burn_font_size"],
                font_color=snapshot["burn_font_color"],
                font_color_opacity=snapshot["burn_font_color_opacity"],
                pos_x_ratio=snapshot["burn_x"],
                pos_y_ratio=snapshot["burn_y"],
                text_width_ratio=snapshot["burn_text_width"],
            )
            burn_ass_oss = (
                f"oss://{oss.bucket_name}/"
                f"{_output_key(output_prefix_key, drama_index, episode_index, filename, 'burn.ass')}"
            )
            _, ass_key = AliyunOSSClient.parse_oss_uri(burn_ass_oss)
            await asyncio.to_thread(oss.put_object_text, ass_key, ass_text)
            item["burn_ass_oss_uri"] = burn_ass_oss
            await _persist_items(db, job_id, items)

            mps = MPSClient(settings)
            mps_submit = await mps.submit_subtitle_burn(
                input_oss_uri=clean_mp4_oss,
                subtitle_oss_uri=burn_ass_oss,
                output_oss_uri=output_mp4_oss,
                title=f"{name_prefix}-mps-burn",
            )
            item["mps_job_id"] = mps_submit.job_id
            await _persist_items(db, job_id, items)

            final = await mps.wait_for_job(
                mps_submit.job_id,
                poll_interval_seconds=settings.ims_poll_interval_seconds,
                timeout_seconds=settings.ims_poll_timeout_seconds,
            )
            item["translation_status"] = None  # MPS 无 IMS 翻译任务
            item["output_video_oss_uri"] = output_mp4_oss
            item["output_public_url"] = oss.public_url(
                AliyunOSSClient.parse_oss_uri(output_mp4_oss)[1]
            )
            # TOS 字段在 mps 模式下永远 None（输出直落 OSS）
            item["output_video_tos_uri"] = None
            item["output_video_tos_public_url"] = None
            item["output_video_bj_tos_uri"] = None
            item["output_video_bj_tos_public_url"] = None
            item["bj_fetch_error"] = None
        except Exception as exc:  # noqa: BLE001
            logger.exception("mps burn %s/%d failed", job_id, index)
            item["status"] = "failed"
            item["error"] = f"MPS 烧录失败: {exc}"
            await _persist_items(db, job_id, items)
            return
    elif snapshot["burn_mode"] == "aliyun":
        # aliyun 烧录（IMS SubmitVideoTranslationJob）
        try:
            video_media_id = await ims.register_media(
                input_url=clean_mp4_oss,
                media_type="video",
                title=f"{name_prefix}-video",
                business_type="subtitles",
            )

            translation_submit = await ims.submit_video_translation(
                title=f"{name_prefix}-trans",
                video_media_id=video_media_id,
                subtitle_media_id=None,
                subtitle_oss_url=srt_for_burn_oss,
                output_mp4_oss=output_mp4_oss,
                source_lang=source_lang_for_ims,
                target_lang=target_lang,
                burn_font_size=snapshot["burn_font_size"],
                burn_font_color=snapshot["burn_font_color"],
                burn_font_color_opacity=snapshot["burn_font_color_opacity"],
                burn_x=snapshot["burn_x"],
                burn_y=snapshot["burn_y"],
                burn_text_width=snapshot["burn_text_width"],
            )
            item["translation_job_id"] = translation_submit.job_id
            item["translation_status"] = "Processing"
            await _persist_items(db, job_id, items)

            final = await ims.wait_for_smart_handle_job(
                translation_submit.job_id,
                poll_interval_seconds=settings.ims_poll_interval_seconds,
                timeout_seconds=settings.ims_poll_timeout_seconds,
            )
            item["translation_status"] = final.state
            item["output_video_oss_uri"] = output_mp4_oss
            item["output_public_url"] = oss.public_url(
                AliyunOSSClient.parse_oss_uri(output_mp4_oss)[1]
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("video translation %s/%d failed", job_id, index)
            item["status"] = "failed"
            item["error"] = f"烧录失败: {exc}"
            await _persist_items(db, job_id, items)
            return
    else:
        item["status"] = "failed"
        item["error"] = f"未知 burn_mode: {snapshot['burn_mode']}"
        await _persist_items(db, job_id, items)
        return

    item["stage"] = "done"
    item["status"] = "succeeded"
    item["error"] = None
    await _persist_items(db, job_id, items)


async def run_subtitle_erase_translate_job(
    db: Database,
    settings: Settings,
    registry: ProviderRegistry,
    job_id: str,
    *,
    only_indices: list[int] | None = None,
) -> None:
    """后台任务入口：编排多剧 + 单剧顺序。"""

    snapshot = await _load_snapshot(db, job_id)
    if snapshot is None:
        logger.warning("subtitle-erase job %s 不存在，跳过", job_id)
        return

    try:
        oss = AliyunOSSClient(settings)
    except RuntimeError as exc:
        await _set_job_fields(
            db, job_id, status="failed", error_message=str(exc),
            completed_at=datetime.now(timezone.utc),
        )
        return

    rate_limiter = RateLimiter(snapshot["qps"])
    ims = IMSClient(settings, rate_limiter=rate_limiter)

    items: list[dict] = snapshot["items"]
    indices = only_indices if only_indices is not None else list(range(len(items)))
    if not indices:
        logger.warning("subtitle-erase job %s 无可处理的 item", job_id)
        return

    # 按剧分组（保持每剧内 episode 顺序）
    dramas: dict[int, list[int]] = defaultdict(list)
    for idx in indices:
        dramas[items[idx].get("drama_index", 0)].append(idx)

    await _set_job_fields(
        db, job_id, status="running",
        progress_message=f"开始处理 {len(dramas)} 部剧 / {len(indices)} 集",
        submitted_at=datetime.now(timezone.utc),
    )

    async def _run_drama(drama_index: int, episode_indices: list[int]) -> None:
        # 同一剧内 episode 并发处理；多剧之间也并行（受 RateLimiter 限流）
        await asyncio.gather(
            *(_run_episode(db, job_id, ims, oss, registry, settings, snapshot, items, ep_idx)
              for ep_idx in episode_indices)
        )

    await asyncio.gather(*(_run_drama(di, eidx) for di, eidx in dramas.items()))

    succeeded = sum(1 for it in items if it.get("status") == "succeeded")
    failed = sum(1 for it in items if it.get("status") == "failed")
    overall = "completed" if succeeded > 0 else "failed"
    await _set_job_fields(
        db, job_id, status=overall,
        progress_message=f"成功 {succeeded}/{len(items)}，失败 {failed}",
        completed_at=datetime.now(timezone.utc),
    )
