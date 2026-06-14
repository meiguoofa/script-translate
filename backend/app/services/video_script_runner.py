from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import Settings
from app.db import Database
from app.models import VideoScriptJob
from app.services.las_client import LASClient
from app.services.script_ingestor import ingest_text_into_script
from app.services.tos_client import TOSClient, filter_text_objects, parse_tos_uri

logger = logging.getLogger("video_script_runner")

TERMINAL_STATUSES = {"COMPLETED", "FAILED", "TIMEOUT"}


async def _set_status(
    db: Database,
    job_id: str,
    *,
    status: str | None = None,
    progress_message: str | None = None,
    error_message: str | None = None,
    las_task_id: str | None = None,
    submitted_at: datetime | None = None,
    completed_at: datetime | None = None,
    generated_script_text: str | None = None,
    generated_script_id: str | None = None,
) -> None:
    async with await db.session() as session:
        job = await session.get(VideoScriptJob, job_id)
        if job is None:
            return
        if status is not None:
            job.status = status
        if progress_message is not None:
            job.progress_message = progress_message
        if error_message is not None:
            job.error_message = error_message
        if las_task_id is not None:
            job.las_task_id = las_task_id
        if submitted_at is not None:
            job.submitted_at = submitted_at
        if completed_at is not None:
            job.completed_at = completed_at
        if generated_script_text is not None:
            job.generated_script_text = generated_script_text
        if generated_script_id is not None:
            job.generated_script_id = generated_script_id
        await session.commit()


async def _load_job_snapshot(db: Database, job_id: str) -> dict | None:
    async with await db.session() as session:
        job = await session.get(VideoScriptJob, job_id)
        if job is None:
            return None
        return {
            "id": job.id,
            "title": job.title,
            "video_urls_json": job.video_urls_json,
            "custom_script_prompt": job.custom_script_prompt,
            "output_tos_path": job.output_tos_path,
        }


async def run_video_script_job(db: Database, settings: Settings, job_id: str) -> None:
    """Top-level background task: submit → poll → fetch → ingest → finalize."""

    import json

    snapshot = await _load_job_snapshot(db, job_id)
    if snapshot is None:
        logger.warning("video job %s 不存在，跳过", job_id)
        return

    try:
        video_urls: list[str] = json.loads(snapshot["video_urls_json"])
    except Exception:
        await _set_status(
            db,
            job_id,
            status="failed",
            error_message="video_urls_json 解析失败",
            completed_at=datetime.now(timezone.utc),
        )
        return

    try:
        las = LASClient(settings)
        tos = TOSClient(settings)
    except RuntimeError as exc:
        await _set_status(
            db,
            job_id,
            status="failed",
            error_message=str(exc),
            completed_at=datetime.now(timezone.utc),
        )
        return

    try:
        submit = await las.submit(
            video_urls=video_urls,
            output_tos_path=snapshot["output_tos_path"],
            custom_script_prompt=snapshot["custom_script_prompt"],
        )
    except Exception as exc:  # noqa: BLE001
        await _set_status(
            db,
            job_id,
            status="failed",
            error_message=f"提交 LAS 失败: {exc}",
            completed_at=datetime.now(timezone.utc),
        )
        return

    await _set_status(
        db,
        job_id,
        status="running",
        progress_message="已提交至 LAS，等待生成",
        las_task_id=submit.task_id,
        submitted_at=datetime.now(timezone.utc),
    )

    interval = max(2, settings.las_poll_interval_seconds)
    deadline = asyncio.get_event_loop().time() + max(60, settings.las_poll_timeout_seconds)
    last_status: str | None = None

    while True:
        if asyncio.get_event_loop().time() > deadline:
            await _set_status(
                db,
                job_id,
                status="failed",
                error_message="LAS 任务等待超时",
                completed_at=datetime.now(timezone.utc),
            )
            return

        try:
            poll = await las.poll(submit.task_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("poll job %s 出错: %s", job_id, exc)
            await asyncio.sleep(interval)
            continue

        status_upper = poll.task_status.upper()
        if status_upper != last_status:
            last_status = status_upper
            await _set_status(
                db,
                job_id,
                progress_message=f"LAS task_status={status_upper}",
            )

        if status_upper in TERMINAL_STATUSES:
            if status_upper == "COMPLETED":
                break
            await _set_status(
                db,
                job_id,
                status="failed",
                error_message=poll.error_msg or f"LAS 返回 {status_upper}",
                completed_at=datetime.now(timezone.utc),
            )
            return

        await asyncio.sleep(interval)

    # COMPLETED → 拉取 output_tos_path 下的所有剧本文本，按 Key 排序后拼接
    try:
        bucket, key_prefix = parse_tos_uri(snapshot["output_tos_path"])
        if bucket != tos.bucket:
            raise RuntimeError(f"output bucket 与配置不一致: {bucket} vs {tos.bucket}")
        all_objects = tos.list_objects(prefix=key_prefix.rstrip("/") + "/")
        text_objects = filter_text_objects(all_objects)
        if not text_objects:
            raise RuntimeError(
                f"在 {snapshot['output_tos_path']} 下未找到 .md/.txt 剧本文件，all_objects={[o['Key'] for o in all_objects]}"
            )
        parts: list[str] = []
        for obj in text_objects:
            body = tos.download_object(obj["Key"])
            chunk = body.decode("utf-8", errors="replace")
            episode_name = obj["Key"].rsplit("/", 1)[-1]
            if len(text_objects) > 1:
                parts.append(f"# {episode_name}\n\n{chunk.strip()}\n")
            else:
                parts.append(chunk)
        script_text = "\n\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        await _set_status(
            db,
            job_id,
            status="failed",
            error_message=f"下载 LAS 产物失败: {exc}",
            completed_at=datetime.now(timezone.utc),
        )
        return

    # 入库为 Script
    try:
        async with await db.session() as session:
            ingested = await ingest_text_into_script(
                session,
                title=snapshot["title"],
                raw_text=script_text,
                source_type="video_restore",
                raw_file_path=None,
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        await _set_status(
            db,
            job_id,
            status="failed",
            error_message=f"剧本入库失败: {exc}",
            completed_at=datetime.now(timezone.utc),
            generated_script_text=script_text,
        )
        return

    await _set_status(
        db,
        job_id,
        status="completed",
        progress_message="剧本生成完成",
        generated_script_text=script_text,
        generated_script_id=ingested.script_id,
        completed_at=datetime.now(timezone.utc),
    )
