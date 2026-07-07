"""MPS 烧录端到端冒烟测。

用法（先在阿里云控制台创建 MPS Pipeline，把 ID 填进 backend/.env）：

    ALIYUN_MPS_PIPELINE_ID=xxx

然后：

    cd backend
    .venv/bin/python scripts/probe_mps.py \\
        --input oss://xzdl-shortdrama/subtitle-erase-output/drama-00/ep01-clean.mp4 \\
        --subtitle oss://xzdl-shortdrama/subtitle-erase-output/drama-00/ep01-burn.ass \\
        --output oss://xzdl-shortdrama/subtitle-erase-output/drama-00/ep01-mps-test.mp4

脚本会：1) 提交 SubmitJobs；2) 轮询到终态；3) 打印 output_oss_uri。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.services.mps_client import MPSClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="输入视频 oss:// URI (clean.mp4)")
    parser.add_argument("--subtitle", required=True, help="ASS 字幕 oss:// URI")
    parser.add_argument("--output", required=True, help="输出视频 oss:// URI")
    parser.add_argument("--title", default="probe-mps-burn")
    args = parser.parse_args()

    settings = Settings()
    if not settings.aliyun_mps_pipeline_id:
        print("ERROR: ALIYUN_MPS_PIPELINE_ID 未配置，请先在阿里云控制台创建 MPS Pipeline 并填进 .env", file=sys.stderr)
        sys.exit(2)

    mps = MPSClient(settings)
    submit = await mps.submit_subtitle_burn(
        input_oss_uri=args.input,
        subtitle_oss_uri=args.subtitle,
        output_oss_uri=args.output,
        title=args.title,
    )
    print(f"submit OK, job_id={submit.job_id}")

    final = await mps.wait_for_job(
        submit.job_id,
        poll_interval_seconds=settings.ims_poll_interval_seconds,
        timeout_seconds=settings.ims_poll_timeout_seconds,
    )
    print(f"final state={final.state} output_oss_uri={final.output_oss_uri}")


if __name__ == "__main__":
    asyncio.run(main())
