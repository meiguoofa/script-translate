from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone

from app.config import Settings
from app.db import Database
from app.models import VideoSuperResolutionJob
from app.services.aliyun_oss_client import AliyunOSSClient
from app.services.viapi_client import VIAPIClient

logger = logging.getLogger("video_super_resolution_runner")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(name: str) -> str:
    base = name.strip().replace("\\", "/").split("/")[-1] or "video"
    return _SAFE_NAME.sub("_", base)


async def _load_snapshot(db: Database, job_id: str) -> dict | None:
    async with await db.session() as session:
        job = await session.get(VideoSuperResolutionJob, job_id)
        if job is None:
            return None
        return {
            "id": job.id,
            "title": job.title,
            "bit_rate": job.bit_rate,
            "items": json.loads(job.items_json or "[]"),
            "output_oss_prefix": job.output_oss_prefix,
        }


async def _persist_items(db: Database, job_id: str, items: list[dict]) -> None:
    async with await db.session() as session:
        job = await session.get(VideoSuperResolutionJob, job_id)
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
        job = await session.get(VideoSuperResolutionJob, job_id)
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


def _build_output_key(prefix: str, index: int, filename: str) -> str:
    safe = _safe_filename(filename)
    if not safe.lower().endswith(".mp4"):
        safe = f"{safe}.mp4"
    return f"{prefix.strip('/')}/{index:02d}-{safe}"


async def _run_item(
    db: Database,
    job_id: str,
    viapi: VIAPIClient,
    oss: AliyunOSSClient,
    output_prefix_key: str,
    items: list[dict],
    index: int,
    bit_rate: int,
    poll_interval_seconds: int,
    poll_timeout_seconds: int,
) -> None:
    item = items[index]
    item["status"] = "running"
    await _persist_items(db, job_id, items)

    # 阶段 1：submit。立即拿到 viapi_job_id 并落库，方便 UI 实时观察。
    try:
        submit = await asyncio.to_thread(
            viapi.submit_super_resolve_video, item["input_public_url"], bit_rate
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("super-resolve submit %s/%d failed", job_id, index)
        item["status"] = "failed"
        item["error"] = f"VIAPI 提交失败: {exc}"
        await _persist_items(db, job_id, items)
        return

    item["viapi_job_id"] = submit.job_id
    item["viapi_status"] = "PROCESSING"
    await _persist_items(db, job_id, items)

    # 阶段 2：轮询直到终态，然后转存到我们自己的 OSS。
    try:
        result = await asyncio.to_thread(
            _wait_and_upload_sync,
            viapi,
            oss,
            submit.job_id,
            output_prefix_key,
            index,
            item["filename"],
            poll_interval_seconds,
            poll_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("super-resolve poll/upload %s/%d failed", job_id, index)
        item["status"] = "failed"
        item["error"] = str(exc)
        await _persist_items(db, job_id, items)
        return

    item["viapi_status"] = result["viapi_status"]
    item["raw_output_url"] = result["raw_output_url"]
    item["output_oss_uri"] = result["output_oss_uri"]
    item["output_public_url"] = result["output_public_url"]
    item["status"] = "succeeded"
    item["error"] = None
    await _persist_items(db, job_id, items)


def _wait_and_upload_sync(
    viapi: VIAPIClient,
    oss: AliyunOSSClient,
    viapi_job_id: str,
    output_prefix_key: str,
    index: int,
    filename: str,
    poll_interval_seconds: int,
    poll_timeout_seconds: int,
) -> dict:
    final = viapi.wait_for_super_resolve_video(
        viapi_job_id,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=poll_timeout_seconds,
    )
    output_key = _build_output_key(output_prefix_key, index, filename)
    oss.put_object_from_url(output_key, final.output_video_url, content_type="video/mp4")
    return {
        "viapi_status": final.status,
        "raw_output_url": final.output_video_url,
        "output_key": output_key,
        "output_oss_uri": oss.oss_uri(output_key),
        "output_public_url": oss.public_url(output_key),
    }


async def run_video_super_resolution_job(
    db: Database,
    settings: Settings,
    job_id: str,
    *,
    only_indices: list[int] | None = None,
) -> None:
    """Top-level background task: for each item, call VIAPI SuperResolveVideo and re-upload.

    only_indices: 只跑指定 index 的 item（用于重试失败项）。None = 跑全部。
    """

    snapshot = await _load_snapshot(db, job_id)
    if snapshot is None:
        logger.warning("super-res job %s 不存在，跳过", job_id)
        return

    try:
        oss = AliyunOSSClient(settings)
        viapi = VIAPIClient(settings)
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
    bit_rate: int = snapshot["bit_rate"]
    # output_oss_prefix 形如 "oss://xzdl-video-super-resolution/super-resolution-output/{job_id}/"
    # _process_one_sync 内拼 key 时只关心 bucket 内的相对路径，所以这里抽 key 部分。
    output_prefix_uri = snapshot["output_oss_prefix"].rstrip("/")
    output_prefix_key = output_prefix_uri.split("/", 3)[3] if output_prefix_uri.startswith("oss://") else output_prefix_uri

    indices = only_indices if only_indices is not None else list(range(len(items)))
    if not indices:
        logger.warning("super-res job %s 无可处理的 item", job_id)
        return

    await _set_job_fields(
        db,
        job_id,
        status="running",
        progress_message=f"开始处理 {len(indices)} 个视频",
        submitted_at=datetime.now(timezone.utc),
    )

    # 阿里云 VIAPI SuperResolveVideo 接口 QPS=2，并发上限收到 2，
    # 避免 submit/poll 阶段瞬时触发 Throttling。
    sem = asyncio.Semaphore(2)

    async def _bounded(idx: int) -> None:
        async with sem:
            await _run_item(
                db,
                job_id,
                viapi,
                oss,
                output_prefix_key,
                items,
                idx,
                bit_rate,
                settings.viapi_poll_interval_seconds,
                settings.viapi_poll_timeout_seconds,
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
