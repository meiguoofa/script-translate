"""Resume the 墨色昭心 video super-resolution job from episode 14 (index 13).

Resets items[13..101] to pending, clears VIAPI fields, marks the job running,
then invokes run_video_super_resolution_job with only_indices=[13..101].

Run from /opt/script-translate/backend so it picks up the production .env + DB:

    cd /opt/script-translate/backend && \
    /root/project/script-translate-repo/.venv/bin/python \
    /root/project/script-translate-repo/backend/scripts/resume_mo_super_res.py

Designed to be invoked via nohup so it survives shell exit.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.db import Database
from app.models import VideoSuperResolutionJob
from app.services.video_super_resolution_runner import run_video_super_resolution_job

JOB_ID = "93a33b36-b147-4eec-9181-31193a11801b"
START_INDEX = 13  # 第14集.mp4
END_INDEX_EXCLUSIVE = 102  # 总共 102 集

RETRY_FIELDS = (
    "viapi_job_id",
    "viapi_status",
    "raw_output_url",
    "output_oss_uri",
    "output_public_url",
    "error",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("resume_mo_super_res")


async def main() -> None:
    settings = Settings()
    db = Database(settings.database_url)
    await db.init_models()

    async with await db.session() as session:
        job = await session.get(VideoSuperResolutionJob, JOB_ID)
        if job is None:
            logger.error("job %s 不存在", JOB_ID)
            return

        items: list[dict] = json.loads(job.items_json or "[]")
        total = len(items)
        logger.info(
            "job=%s title=%s total=%d current_status=%s",
            job.id, job.title, total, job.status,
        )

        end = min(END_INDEX_EXCLUSIVE, total)
        indices = list(range(START_INDEX, end))
        logger.info("将重置并重跑 indices=%s..%s (共 %d 个)", START_INDEX, end - 1, len(indices))

        reset_count = 0
        for idx in indices:
            it = items[idx]
            prev = it.get("status")
            if prev == "succeeded":
                logger.warning("index=%d 已 succeeded，跳过重置", idx)
                continue
            it["status"] = "pending"
            for f in RETRY_FIELDS:
                it[f] = None
            reset_count += 1

        job.items_json = json.dumps(items, ensure_ascii=False)
        job.status = "running"
        job.error_message = None
        job.completed_at = None
        job.submitted_at = datetime.now(timezone.utc)
        job.progress_message = f"后台脚本恢复：重跑 {len(indices)} 个（第{START_INDEX + 1}集起）"
        await session.commit()
        logger.info("已重置 %d 个 item，job.status=running", reset_count)

    logger.info("开始执行 run_video_super_resolution_job ...")
    await run_video_super_resolution_job(
        db, settings, JOB_ID, only_indices=indices
    )
    logger.info("run_video_super_resolution_job 退出")

    async with await db.session() as session:
        job = await session.get(VideoSuperResolutionJob, JOB_ID)
        if job is not None:
            items = json.loads(job.items_json or "[]")
            succeeded = sum(1 for it in items if it.get("status") == "succeeded")
            failed = sum(1 for it in items if it.get("status") == "failed")
            pending = sum(1 for it in items if it.get("status") == "pending")
            running = sum(1 for it in items if it.get("status") == "running")
            logger.info(
                "最终状态: job.status=%s succeeded=%d failed=%d running=%d pending=%d",
                job.status, succeeded, failed, running, pending,
            )


if __name__ == "__main__":
    asyncio.run(main())
