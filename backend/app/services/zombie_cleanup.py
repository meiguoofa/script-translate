from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.db import Database
from app.models import (
    VideoScriptJob,
    VideoSubtitleEraseJob,
    VideoSubtitleJob,
    VideoSuperResolutionJob,
)

logger = logging.getLogger("zombie_cleanup")

# 任务超过这个时间没更新且仍处于 running，视为僵尸任务
# 必须 > ims_poll_timeout_seconds/60 (=180)，否则正常 IMS 轮询期间会被误判
ZOMBIE_TIMEOUT_MINUTES = 200

ZOMBIE_ERROR_MSG = "任务执行过程中服务重启，后台任务丢失（已自动标记为失败，请重新提交）"

ABORT_ERROR_MSG = "用户手动停止任务（可调用 /retry 重试失败项）"


async def cleanup_zombie_jobs(db: Database) -> int:
    """启动时扫描所有 status=running 且超过 ZOMBIE_TIMEOUT_MINUTES 未更新的 job，
    标记为 failed，避免 zombie job 永远卡在 running。

    返回清理的 job 总数。
    """

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ZOMBIE_TIMEOUT_MINUTES)
    total = 0

    # 4 个 job 表，每张表独立更新
    job_models = [
        VideoScriptJob,
        VideoSuperResolutionJob,
        VideoSubtitleJob,
        VideoSubtitleEraseJob,
    ]

    async with await db.session() as session:
        for model in job_models:
            result = await session.execute(
                select(model).where(
                    model.status == "running",
                    (model.updated_at < cutoff) | (model.updated_at.is_(None)),
                )
            )
            rows = result.scalars().all()
            for row in rows:
                logger.warning(
                    "清理 zombie job: %s/%s（updated_at=%s）",
                    model.__tablename__,
                    row.id,
                    row.updated_at,
                )
                row.status = "failed"
                row.error_message = ZOMBIE_ERROR_MSG
                if row.completed_at is None:
                    row.completed_at = datetime.now(timezone.utc)
                total += 1
            if rows:
                await session.commit()

    if total > 0:
        logger.info("共清理 %d 个 zombie job", total)
    return total


async def abort_running_job(db: Database, job_id: str, model) -> bool:
    """把指定 job 强制标记为 failed，允许后续 retry。返回是否命中。

    用于用户主动停止 running 任务：job 仍在 running 但用户想终止时调用。
    """
    async with await db.session() as session:
        row = await session.get(model, job_id)
        if row is None:
            return False
        if row.status != "running":
            return False
        row.status = "failed"
        row.error_message = ABORT_ERROR_MSG
        if row.completed_at is None:
            row.completed_at = datetime.now(timezone.utc)
        await session.commit()
        return True
