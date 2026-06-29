from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.db import Database
from app.llm.registry import ProviderRegistry
from app.models import VideoSubtitleJob
from app.services.ffmpeg_burn import burn_subtitles, probe_video_size
from app.services.srt_utils import parse_srt, srt_to_ass
from app.services.subtitle_translator import translate_srt
from app.services.tos_client import parse_tos_uri
from app.services.tos_singapore_client import TOSSingaporeClient
from app.services.video_ocr_client import VideoOCRClient

logger = logging.getLogger("video_subtitle_runner")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(name: str) -> str:
    base = name.strip().replace("\\", "/").split("/")[-1] or "video"
    return _SAFE_NAME.sub("_", base)


async def _load_snapshot(db: Database, job_id: str) -> dict | None:
    async with await db.session() as session:
        job = await session.get(VideoSubtitleJob, job_id)
        if job is None:
            return None
        return {
            "id": job.id,
            "title": job.title,
            "subtitle_source": job.subtitle_source,
            "enable_translate": job.enable_translate,
            "enable_burn": job.enable_burn,
            "placement_mode": job.placement_mode,
            "target_lang": job.target_lang,
            "model_provider": job.model_provider,
            "model_name": job.model_name,
            "items": json.loads(job.items_json or "[]"),
            "output_tos_prefix": job.output_tos_prefix,
        }


async def _persist_items(db: Database, job_id: str, items: list[dict]) -> None:
    async with await db.session() as session:
        job = await session.get(VideoSubtitleJob, job_id)
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
        job = await session.get(VideoSubtitleJob, job_id)
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


def _build_output_key(prefix: str, index: int, filename: str, ext: str) -> str:
    safe = _safe_filename(filename)
    # 去掉原扩展名，加新的
    safe = re.sub(r"\.[^.]+$", "", safe) or safe
    return f"{prefix.strip('/')}/{index:02d}-{safe}.{ext}"


async def _run_item(
    db: Database,
    job_id: str,
    tos: TOSSingaporeClient,
    ocr: VideoOCRClient,
    registry: ProviderRegistry | None,
    settings: Settings,
    snapshot: dict,
    items: list[dict],
    index: int,
) -> None:
    item = items[index]
    output_prefix_key = snapshot["output_tos_prefix"]
    # output_tos_prefix 形如 "tos://bucket/subtitle-output/{job_id}/"，需要抽出 key 部分
    if output_prefix_key.startswith("tos://"):
        _, key = parse_tos_uri(output_prefix_key)
        output_prefix_key = key.rstrip("/")
    enable_translate = snapshot["enable_translate"]
    enable_burn = snapshot["enable_burn"]
    placement_mode = snapshot["placement_mode"]

    tmp_dir = Path(tempfile.mkdtemp(prefix=f"subtitle-{job_id}-{index}-"))
    input_video_tmp = tmp_dir / f"{index:02d}-input.mp4"

    # ===== 阶段 1：字幕提取（VIAPI 直接从阿里云 OSS 拉取，零后端带宽）=====
    item["status"] = "extracting"
    item["error"] = None
    await _persist_items(db, job_id, items)

    try:
        # 用户已把视频上传到阿里云上海 OSS，VIAPI 可直接拉取该 URL
        oss_url = item.get("input_oss_public_url") or ""
        if not oss_url.startswith("http"):
            raise RuntimeError(f"缺少 OSS 公网 URL: {oss_url}")

        submit = await asyncio.to_thread(ocr.submit_subtitle_ocr, oss_url)
        item["viapi_job_id"] = submit.job_id
        item["viapi_status"] = "PROCESSING"
        await _persist_items(db, job_id, items)

        final = await asyncio.to_thread(
            ocr.wait_for_subtitle_ocr,
            submit.job_id,
            poll_interval_seconds=settings.viapi_poll_interval_seconds,
            timeout_seconds=settings.viapi_poll_timeout_seconds,
        )
        item["viapi_status"] = final.status
        srt_text = final.srt_text
        if not srt_text:
            raise RuntimeError("VIAPI 未返回字幕文本")
        item["srt_text"] = srt_text

        # 上传 SRT 到新加坡 TOS（内网）
        srt_key = _build_output_key(output_prefix_key, index, item["filename"], "srt")
        srt_tmp = tmp_dir / f"{index:02d}.srt"
        srt_tmp.write_text(srt_text, encoding="utf-8")
        await asyncio.to_thread(
            tos.upload_file, srt_key, str(srt_tmp), "application/x-subrip"
        )
        item["srt_tos_uri"] = tos.tos_uri(srt_key)
        item["srt_tos_public_url"] = tos.public_url(srt_key)
        item["status"] = "extracted"
        await _persist_items(db, job_id, items)
    except Exception as exc:  # noqa: BLE001
        logger.exception("subtitle extract %s/%d failed", job_id, index)
        item["status"] = "failed"
        item["error"] = f"字幕提取失败: {exc}"
        await _persist_items(db, job_id, items)
        return

    # ===== 阶段 2：翻译 =====
    current_srt_text = item["srt_text"]
    if enable_translate:
        item["status"] = "translating"
        await _persist_items(db, job_id, items)
        try:
            if registry is None:
                raise RuntimeError("翻译注册表未初始化")
            translated = await translate_srt(
                current_srt_text,
                registry=registry,
                model_provider=snapshot["model_provider"],
                model_name=snapshot["model_name"],
                target_lang=snapshot["target_lang"] or "",
                batch_size=settings.batch_size,
            )
            item["translated_srt_text"] = translated
            # 上传译文 SRT
            tr_key = _build_output_key(
                output_prefix_key, index, item["filename"], f"{snapshot['target_lang']}.srt"
            )
            tr_tmp = tmp_dir / f"{index:02d}-translated.srt"
            tr_tmp.write_text(translated, encoding="utf-8")
            await asyncio.to_thread(
                tos.upload_file, tr_key, str(tr_tmp), "application/x-subrip"
            )
            item["translated_srt_tos_uri"] = tos.tos_uri(tr_key)
            item["translated_srt_tos_public_url"] = tos.public_url(tr_key)
            current_srt_text = translated
            item["status"] = "translated"
            await _persist_items(db, job_id, items)
        except Exception as exc:  # noqa: BLE001
            logger.exception("subtitle translate %s/%d failed", job_id, index)
            item["status"] = "failed"
            item["error"] = f"翻译失败: {exc}"
            await _persist_items(db, job_id, items)
            return

    # ===== 阶段 3：烧字幕到视频 =====
    if enable_burn:
        item["status"] = "burning"
        await _persist_items(db, job_id, items)
        try:
            # 从新加坡 TOS 内网拉原视频到本地
            _, input_key = parse_tos_uri(item["input_tos_uri"])
            await asyncio.to_thread(
                tos.download_object_to_file, input_key, str(input_video_tmp)
            )
            # 探测尺寸
            video_w, video_h = await asyncio.to_thread(probe_video_size, str(input_video_tmp))

            # 生成 ASS
            entries = parse_srt(current_srt_text)
            ass_text = srt_to_ass(
                entries,
                video_w=video_w,
                video_h=video_h,
                placement_mode=placement_mode,
            )
            ass_tmp = tmp_dir / f"{index:02d}.ass"
            ass_tmp.write_text(ass_text, encoding="utf-8")

            # 烧字幕
            output_video_tmp = tmp_dir / f"{index:02d}-output.mp4"
            await asyncio.to_thread(
                burn_subtitles,
                str(input_video_tmp),
                str(ass_tmp),
                str(output_video_tmp),
                placement_mode=placement_mode,
                video_w=video_w,
                video_h=video_h,
            )

            # 上传到 TOS
            out_key = _build_output_key(output_prefix_key, index, item["filename"], "mp4")
            await asyncio.to_thread(
                tos.upload_file, out_key, str(output_video_tmp), "video/mp4"
            )
            item["output_video_tos_uri"] = tos.tos_uri(out_key)
            item["output_video_tos_public_url"] = tos.public_url(out_key)
        except Exception as exc:  # noqa: BLE001
            logger.exception("subtitle burn %s/%d failed", job_id, index)
            item["status"] = "failed"
            item["error"] = f"烧字幕失败: {exc}"
            await _persist_items(db, job_id, items)
            return

    item["status"] = "succeeded"
    item["error"] = None
    await _persist_items(db, job_id, items)


async def run_video_subtitle_job(
    db: Database,
    settings: Settings,
    registry: ProviderRegistry,
    job_id: str,
    *,
    only_indices: list[int] | None = None,
) -> None:
    """Top-level background task for video subtitle extraction/translation/burn."""

    snapshot = await _load_snapshot(db, job_id)
    if snapshot is None:
        logger.warning("subtitle job %s 不存在，跳过", job_id)
        return

    try:
        tos = TOSSingaporeClient(settings)
        ocr = VideoOCRClient(settings)
    except RuntimeError as exc:
        await _set_job_fields(
            db,
            job_id,
            status="failed",
            error_message=str(exc),
            completed_at=datetime.now(timezone.utc),
        )
        return

    items: list[dict] = snapshot["items"]
    indices = only_indices if only_indices is not None else list(range(len(items)))
    if not indices:
        logger.warning("subtitle job %s 无可处理的 item", job_id)
        return

    await _set_job_fields(
        db,
        job_id,
        status="running",
        progress_message=f"开始处理 {len(indices)} 个视频",
        submitted_at=datetime.now(timezone.utc),
    )

    # videorecog 接口 QPS=2，并发上限收到 2
    sem = asyncio.Semaphore(2)

    async def _bounded(idx: int) -> None:
        async with sem:
            await _run_item(
                db, job_id, tos, ocr, registry, settings, snapshot, items, idx
            )

    await asyncio.gather(*(_bounded(idx) for idx in indices))

    succeeded = sum(1 for it in items if it.get("status") == "succeeded")
    failed = sum(1 for it in items if it.get("status") == "failed")
    overall = "completed" if succeeded > 0 else "failed"
    await _set_job_fields(
        db,
        job_id,
        status=overall,
        progress_message=f"成功 {succeeded}/{len(items)}，失败 {failed}",
        completed_at=datetime.now(timezone.utc),
    )
