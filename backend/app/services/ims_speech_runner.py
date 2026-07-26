from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.db import Database
from app.models import VideoImsSpeechJob
from app.services.ims_client import IMSClient
from app.services.ims_subtitle_style import (
    ADAPTIVE_STYLE_MODE,
    adaptive_fe_canvas,
    build_adaptive_subtitle_config,
)
from app.services.rate_limiter import RateLimiter

logger = logging.getLogger("ims_speech_runner")

_persist_locks: dict[str, asyncio.Lock] = {}
_job_semaphore: asyncio.Semaphore | None = None
_job_semaphore_limit: int | None = None
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _persist_lock(job_id: str) -> asyncio.Lock:
    lock = _persist_locks.get(job_id)
    if lock is None:
        lock = asyncio.Lock()
        _persist_locks[job_id] = lock
    return lock


def _get_job_semaphore(settings: Settings) -> asyncio.Semaphore:
    global _job_semaphore, _job_semaphore_limit
    limit = settings.max_concurrent_ims_speech_jobs
    if _job_semaphore is None or _job_semaphore_limit != limit:
        _job_semaphore = asyncio.Semaphore(limit)
        _job_semaphore_limit = limit
    return _job_semaphore


async def _load_snapshot(db: Database, job_id: str) -> dict | None:
    async with await db.session() as session:
        job = await session.get(VideoImsSpeechJob, job_id)
        if job is None:
            return None
        return {
            "id": job.id,
            "title": job.title,
            "source_language": job.source_language,
            "target_languages": json.loads(job.target_langs_json or "[]"),
            "text_source": job.text_source,
            "config": json.loads(job.config_json or "{}"),
            "items": json.loads(job.items_json or "[]"),
            "output_oss_prefix": job.output_oss_prefix,
        }


async def _persist_items(db: Database, job_id: str, items: list[dict]) -> None:
    async with _persist_lock(job_id):
        async with await db.session() as session:
            job = await session.get(VideoImsSpeechJob, job_id)
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
        job = await session.get(VideoImsSpeechJob, job_id)
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


def _output_uri(
    snapshot: dict,
    item: dict,
    target_languages: list[str],
) -> str:
    stem = _SAFE_NAME.sub("_", Path(item["filename"]).stem) or "episode"
    language_suffix = ""
    if len(snapshot["target_languages"]) > 1:
        language_suffix = (
            "-{language_id}"
            if len(target_languages) > 1
            else f"-{target_languages[0]}"
        )
    return (
        f"{snapshot['output_oss_prefix'].rstrip('/')}/"
        f"d{int(item.get('drama_index', 0)) + 1:02d}-"
        f"e{int(item.get('episode_index', 0)) + 1:03d}-"
        f"{stem}{language_suffix}.mp4"
    )


def _summarize_item_status(item: dict) -> str:
    translations = item.get("translations") or {}
    statuses = [value.get("status") for value in translations.values()]
    if statuses and all(value == "succeeded" for value in statuses):
        return "succeeded"
    if any(value == "succeeded" for value in statuses):
        return "partial_failed"
    return "failed"


def _subtitle_submission_config(config: dict) -> tuple[dict | None, dict]:
    style_mode = config.get("style_mode")
    if style_mode is None:
        return None, {
            "FontSize": config.get("font_size", 72),
            "FontColor": config.get("font_color", "#FFFFFF"),
            "FontColorOpacity": config.get("font_color_opacity", 1),
            "X": config.get("subtitle_x", 0.5),
            "Y": config.get("subtitle_y", 0.82),
            "TextWidth": config.get("text_width", 0.9),
            "Alignment": "Center",
            "BorderStyle": 1,
            "Outline": 2,
        }
    if style_mode != ADAPTIVE_STYLE_MODE:
        raise ValueError(f"不支持的 IMS 字幕样式版本: {style_mode}")
    frozen_canvas = config.get("fe_canvas")
    frozen_subtitle = config.get("subtitle_config")
    if isinstance(frozen_canvas, dict) and isinstance(frozen_subtitle, dict):
        return dict(frozen_canvas), dict(frozen_subtitle)
    return adaptive_fe_canvas(), build_adaptive_subtitle_config(
        bilingual=bool(config.get("bilingual_subtitle")),
        subtitle_enabled=bool(config.get("subtitle_enabled", True)),
        font_color=config.get("font_color", "#FFFFFF"),
        font_color_opacity=float(config.get("font_color_opacity", 1)),
        subtitle_y=float(config.get("subtitle_y", 0.76)),
    )


async def _run_item(
    db: Database,
    settings: Settings,
    ims: IMSClient,
    snapshot: dict,
    items: list[dict],
    index: int,
    episode_semaphore: asyncio.Semaphore,
) -> None:
    async with episode_semaphore:
        item = items[index]
        translations = item.setdefault("translations", {})
        requested_languages = [
            language
            for language in snapshot["target_languages"]
            if translations.get(language, {}).get("status") != "succeeded"
        ]
        if not requested_languages:
            item["status"] = "succeeded"
            item["stage"] = "done"
            item["error"] = None
            await _persist_items(db, snapshot["id"], items)
            return

        for language in requested_languages:
            translation = translations.setdefault(language, {})
            translation["status"] = "running"
            translation["error"] = None
        item["status"] = "running"
        item["stage"] = "submitting"
        item["error"] = None
        await _persist_items(db, snapshot["id"], items)

        try:
            output_video_oss_uri = _output_uri(
                snapshot,
                item,
                requested_languages,
            )
            if item.get("ims_job_id"):
                ims_job_id = item["ims_job_id"]
            else:
                config = snapshot["config"]
                fe_canvas, subtitle_config = _subtitle_submission_config(config)
                submit = await ims.submit_speech_translation(
                    title=(
                        f"{snapshot['title']}-"
                        f"d{int(item.get('drama_index', 0)) + 1:02d}-"
                        f"e{int(item.get('episode_index', 0)) + 1:03d}"
                    ),
                    input_video_oss_uri=item["input_oss_uri"],
                    output_video_oss_uri=output_video_oss_uri,
                    source_language=snapshot["source_language"],
                    target_languages=requested_languages,
                    text_source=snapshot["text_source"],
                    detext_mode=config["detext_mode"],
                    detext_areas=config.get("detext_areas"),
                    ocr_area=config.get("ocr_area"),
                    bilingual_subtitle=bool(config.get("bilingual_subtitle")),
                    subtitle_enabled=bool(config.get("subtitle_enabled", True)),
                    fe_canvas=fe_canvas,
                    subtitle_config=subtitle_config,
                    skip_song=bool(config.get("skip_song")),
                )
                ims_job_id = submit.job_id
                item["ims_job_id"] = ims_job_id
            item["ims_status"] = "Executing"
            item["stage"] = "polling"
            await _persist_items(db, snapshot["id"], items)

            result = await ims.wait_for_speech_translation(
                ims_job_id,
                target_languages=requested_languages,
                output_video_oss_uri=output_video_oss_uri,
                poll_interval_seconds=settings.ims_poll_interval_seconds,
                timeout_seconds=settings.ims_poll_timeout_seconds,
            )
            item["ims_status"] = result.state
            if result.detext_video_url:
                item["detext_video_url"] = result.detext_video_url
            if result.detext_video_media_id:
                item["detext_video_media_id"] = result.detext_video_media_id
            for language in requested_languages:
                language_result = result.translations[language]
                translation = translations[language]
                translation.update(asdict(language_result))
                if language_result.media_url:
                    translation["status"] = "succeeded"
                    translation["error"] = None
                else:
                    translation["status"] = "failed"
                    translation["error"] = "IMS 完成但未返回该语言成片 URL"
            item["status"] = _summarize_item_status(item)
            item["stage"] = "done"
            item["error"] = (
                None
                if item["status"] == "succeeded"
                else "部分目标语言未返回有效成片"
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("IMS speech item failed job=%s index=%d", snapshot["id"], index)
            for language in requested_languages:
                if translations[language].get("status") != "succeeded":
                    translations[language]["status"] = "failed"
                    translations[language]["error"] = str(exc)[:1000]
            item["status"] = _summarize_item_status(item)
            item["stage"] = "done"
            item["error"] = str(exc)[:1000]
        finally:
            await asyncio.shield(_persist_items(db, snapshot["id"], items))


async def run_ims_speech_job(
    db: Database,
    settings: Settings,
    job_id: str,
    *,
    only_indices: list[int] | None = None,
    global_rate_limiter: RateLimiter | None = None,
) -> None:
    snapshot = await _load_snapshot(db, job_id)
    if snapshot is None:
        logger.warning("IMS speech job %s does not exist", job_id)
        return
    indices = only_indices if only_indices is not None else list(range(len(snapshot["items"])))
    if not indices:
        return

    async with _get_job_semaphore(settings):
        await _set_job_fields(
            db,
            job_id,
            status="running",
            progress_message=f"处理中：{len(indices)} 集",
            error_message="",
            submitted_at=datetime.now(timezone.utc),
        )
        ims = (
            IMSClient(settings, global_rate_limiter=global_rate_limiter)
            if global_rate_limiter is not None
            else IMSClient(settings)
        )
        episode_semaphore = asyncio.Semaphore(
            settings.max_concurrent_ims_speech_episodes
        )
        items = snapshot["items"]
        try:
            await asyncio.gather(
                *(
                    _run_item(
                        db,
                        settings,
                        ims,
                        snapshot,
                        items,
                        index,
                        episode_semaphore,
                    )
                    for index in indices
                )
            )
        except asyncio.CancelledError:
            await _set_job_fields(
                db,
                job_id,
                status="failed",
                progress_message="已停止本地跟踪；阿里云任务可能仍在执行",
                error_message="用户停止任务",
                completed_at=datetime.now(timezone.utc),
            )
            raise

        succeeded = sum(1 for item in items if item.get("status") == "succeeded")
        partial = sum(1 for item in items if item.get("status") == "partial_failed")
        failed = sum(1 for item in items if item.get("status") == "failed")
        successful_languages = sum(
            1
            for item in items
            for value in (item.get("translations") or {}).values()
            if value.get("status") == "succeeded"
        )
        await _set_job_fields(
            db,
            job_id,
            status="completed" if successful_languages else "failed",
            progress_message=(
                f"完成：成功 {succeeded}，部分失败 {partial}，失败 {failed}"
            ),
            error_message="" if successful_languages else "所有目标语言均处理失败",
            completed_at=datetime.now(timezone.utc),
        )
