"""Verify LAS drama-script API end-to-end with a known-good video.

Usage:
    cd backend && python scripts/verify_las_api.py

Submits one real LAS task using a historical successful video, polls until
terminal state, and prints the full raw submit/poll responses so we can
see whether LAS still writes TOS products and what business_code/error_msg
look like in the terminal state.

This script does NOT modify business code or DB data. It only reads .env
config, calls LAS submit/poll, lists TOS objects, and optionally downloads
the first .md product to print its head.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, ".")

from app.config import Settings
from app.services.las_client import LASClient
from app.services.tos_client import TOSClient, filter_text_objects, parse_tos_uri

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("verify_las")

# Historical successful video: uploads/034c1b04-.../00-1_srt.mp4
# corresponds to output/034c1b04-.../scripts/ep_001.md (2951 bytes).
KNOWN_GOOD_VIDEO_URI = "tos://test-short-drama/uploads/034c1b04-11f7-4f18-ad46-718c3553cd8d/00-1_srt.mp4"

POLL_INTERVAL = 10
POLL_TIMEOUT = 30 * 60  # 30 min cap

TERMINAL = {"COMPLETED", "FAILED", "TIMEOUT", "SUCCESS"}


def _truncate(obj, limit: int = 3000) -> str:
    s = json.dumps(obj, ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[:limit] + f"...<truncated, total {len(s)} chars>"


def load_default_prompt(db_path: str) -> str:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT content FROM prompt_templates WHERE id = 'default-las'"
    ).fetchone()
    conn.close()
    if row is None:
        raise RuntimeError("default-las prompt not found in DB")
    return row["content"]


async def main() -> int:
    settings = Settings()
    logger.info("LAS_BASE_URL=%s LAS_OPERATOR_ID=%s", settings.las_base_url, settings.las_operator_id)
    logger.info("TOS_BUCKET=%s", settings.tos_bucket)

    prompt = load_default_prompt("data/app.db")
    logger.info("default-las prompt loaded (%d chars)", len(prompt))

    job_id = str(uuid.uuid4())
    output_tos_path = (
        f"tos://{settings.tos_bucket}/"
        f"{settings.tos_output_prefix.strip('/') or 'output'}/{job_id}"
    )
    logger.info("new job_id=%s", job_id)
    logger.info("output_tos_path=%s", output_tos_path)
    logger.info("video_url=%s", KNOWN_GOOD_VIDEO_URI)

    las = LASClient(settings)
    tos = TOSClient(settings)

    logger.info("=== submit ===")
    submit = await las.submit(
        video_urls=[KNOWN_GOOD_VIDEO_URI],
        output_tos_path=output_tos_path,
        custom_script_prompt=prompt,
    )
    logger.info("submit.task_id=%s", submit.task_id)
    logger.info("submit.raw=%s", _truncate(submit.raw))

    logger.info("=== poll (interval=%ds, timeout=%ds) ===", POLL_INTERVAL, POLL_TIMEOUT)
    deadline = asyncio.get_event_loop().time() + POLL_TIMEOUT
    last_status = None
    poll = None
    while True:
        if asyncio.get_event_loop().time() > deadline:
            logger.error("poll timeout reached, last poll=%s", _truncate(poll.raw if poll else None))
            return 2

        try:
            poll = await las.poll(submit.task_id)
        except Exception as exc:
            logger.warning("poll error: %s, retry in %ds", exc, POLL_INTERVAL)
            await asyncio.sleep(POLL_INTERVAL)
            continue

        status_upper = poll.task_status.upper()
        if status_upper != last_status:
            last_status = status_upper
            logger.info(
                "poll status=%s business_code=%s error_msg=%s",
                status_upper, poll.business_code, poll.error_msg,
            )

        if status_upper in TERMINAL:
            break

        await asyncio.sleep(POLL_INTERVAL)

    logger.info("=== terminal poll.raw ===")
    logger.info("poll.raw=%s", _truncate(poll.raw, limit=8000))
    logger.info("poll.task_status=%s business_code=%s error_msg=%s",
                poll.task_status, poll.business_code, poll.error_msg)

    status_upper = poll.task_status.upper()
    if status_upper not in {"COMPLETED", "SUCCESS"}:
        logger.error("LAS task did not succeed: status=%s bizCode=%s msg=%s",
                     status_upper, poll.business_code, poll.error_msg)
        return 3

    # Success path: check TOS products
    logger.info("=== TOS products under %s ===", output_tos_path)
    bucket, key_prefix = parse_tos_uri(output_tos_path)
    if bucket != tos.bucket:
        logger.error("bucket mismatch: %s vs %s", bucket, tos.bucket)
        return 4

    all_objects = tos.list_objects(prefix=key_prefix.rstrip("/") + "/")
    logger.info("all_objects count=%d", len(all_objects))
    for o in all_objects[:30]:
        logger.info("  %12d  %s", o.get("Size", 0), o["Key"])

    text_objects = filter_text_objects(all_objects)
    logger.info("text_objects count=%d", len(text_objects))
    if not text_objects:
        logger.error("NO .md/.txt products found under %s", output_tos_path)
        return 5

    first = text_objects[0]
    body = tos.download_object(first["Key"])
    text = body.decode("utf-8", errors="replace")
    logger.info("=== first product %s (size=%d) head 500 chars ===", first["Key"], len(text))
    print(text[:500])

    logger.info("=== verify done, output_tos_path=%s ===", output_tos_path)
    return 0


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
