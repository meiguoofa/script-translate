"""MPS Pipeline 查/建脚本。

用法：

    cd backend
    .venv/bin/python scripts/probe_mps_pipeline.py            # 列出所有 MPS 管道
    .venv/bin/python scripts/probe_mps_pipeline.py --create   # 一个都没有就建一个

脚本流程：
  1. SearchPipeline 列账号下所有 MPS 管道
  2. 有 → 打印 ID/Name/Speed/State，挑一个填进 .env
  3. 没有 + 带 --create → AddPipeline 建一个名为 subtitle-burn-pipeline 的 Standard 管道
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alibabacloud_mts20140618 import models as mts_models
from alibabacloud_mts20140618.client import Client as MTSClient
from alibabacloud_tea_openapi.models import Config as OpenApiConfig
from alibabacloud_tea_util.models import RuntimeOptions

from app.config import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("probe_mps_pipeline")


def make_client(settings: Settings) -> MTSClient:
    if not settings.aliyun_access_key_id or not settings.aliyun_access_key_secret:
        raise RuntimeError("ALIBABA_CLOUD_ACCESS_KEY_ID / SECRET 未配置")
    config = OpenApiConfig(
        access_key_id=settings.aliyun_access_key_id,
        access_key_secret=settings.aliyun_access_key_secret,
    )
    config.endpoint = settings.aliyun_mps_endpoint
    if "cn-" in settings.aliyun_mps_endpoint or "ap-" in settings.aliyun_mps_endpoint:
        parts = settings.aliyun_mps_endpoint.split(".")
        if len(parts) >= 2:
            config.region_id = parts[1]
    return MTSClient(config)


async def list_pipelines(client: MTSClient) -> list[dict]:
    """SearchPipeline 列出所有管道（不带分页参数，返回首屏）。"""
    request = mts_models.SearchPipelineRequest(page_size=100, page_number=1)
    runtime = RuntimeOptions()
    runtime.connect_timeout = 10_000
    runtime.read_timeout = 15_000
    response = await asyncio.to_thread(client.search_pipeline_with_options, request, runtime)
    body = response.body
    raw = body.to_map() if body else {}
    pipelines = (raw.get("PipelineList") or {}).get("Pipeline") or []
    return pipelines


async def create_pipeline(client: MTSClient, name: str, speed: str = "Standard") -> dict:
    """AddPipeline 创建管道。speed: Standard / Boost / NarrowBandHDV2"""
    request = mts_models.AddPipelineRequest(name=name, speed=speed)
    runtime = RuntimeOptions()
    runtime.connect_timeout = 10_000
    runtime.read_timeout = 15_000
    response = await asyncio.to_thread(client.add_pipeline_with_options, request, runtime)
    body = response.body
    raw = body.to_map() if body else {}
    return raw.get("Pipeline") or {}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--create", action="store_true", help="列不到时创建一个新管道")
    parser.add_argument("--name", default="subtitle-burn-pipeline", help="新建管道的名称")
    parser.add_argument("--speed", default="Standard", choices=["Standard", "Boost", "NarrowBandHDV2"])
    args = parser.parse_args()

    settings = Settings()
    client = make_client(settings)

    pipelines = await list_pipelines(client)
    if pipelines:
        print(f"找到 {len(pipelines)} 个 MPS 管道：")
        print(f"{'PipelineId':<40} {'Name':<30} {'Speed':<20} {'State':<10}")
        print("-" * 100)
        for p in pipelines:
            pid = p.get("Id") or p.get("id") or ""
            name = p.get("Name") or p.get("name") or ""
            speed = p.get("Speed") or p.get("speed") or ""
            state = p.get("State") or p.get("state") or ""
            print(f"{pid:<40} {name:<30} {speed:<20} {state:<10}")
        print()
        print("挑一个 State=Active 的，把 PipelineId 填进 .env 的 ALIYUN_MPS_PIPELINE_ID")
        return

    print("账号下没有任何 MPS 管道。")
    if not args.create:
        print("加 --create 参数创建一个名为 subtitle-burn-pipeline 的 Standard 管道：")
        print(f"  .venv/bin/python scripts/probe_mps_pipeline.py --create")
        sys.exit(1)

    print(f"正在创建管道 name={args.name} speed={args.speed} ...")
    pipeline = await create_pipeline(client, args.name, args.speed)
    pid = pipeline.get("Id") or pipeline.get("id")
    if not pid:
        print(f"ERROR: AddPipeline 未返回 Id，raw={pipeline}")
        sys.exit(2)
    print()
    print(f"✅ 创建成功！PipelineId = {pid}")
    print()
    print("把它填进 backend/.env：")
    print(f"  ALIYUN_MPS_PIPELINE_ID={pid}")


if __name__ == "__main__":
    asyncio.run(main())
