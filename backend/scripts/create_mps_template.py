"""创建 MPS 自定义 H264 转码模板（保留原视频分辨率/帧率/码率）。

成功后把 TemplateId 写进 backend/.env：
    ALIYUN_MPS_TEMPLATE_ID=xxx

模板配置：
  - Container: mp4
  - Video: H.264, profile=high, 不指定 Width/Height/Fps（保留原视频参数）
  - Audio: AAC, 不指定 Bitrate/SampleRate/Channels（保留原音频参数）
  - TransConfig: onepass
"""

from __future__ import annotations

import asyncio
import json
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
logger = logging.getLogger("create_mps_template")

TEMPLATE_NAME = "subtitle-burn-h264-keep-reso"


def make_client(settings: Settings) -> MTSClient:
    config = OpenApiConfig(
        access_key_id=settings.aliyun_access_key_id,
        access_key_secret=settings.aliyun_access_key_secret,
    )
    config.endpoint = settings.aliyun_mps_endpoint
    parts = settings.aliyun_mps_endpoint.split(".")
    if len(parts) >= 2:
        config.region_id = parts[1]
    return MTSClient(config)


async def search_existing(client: MTSClient, name: str) -> str | None:
    """如果同名模板已存在，返回其 ID（避免重复创建）。"""
    request = mts_models.SearchTemplateRequest(name_prefix=name, page_size=100, page_number=1)
    runtime = RuntimeOptions()
    runtime.connect_timeout = 10_000
    runtime.read_timeout = 15_000
    response = await asyncio.to_thread(client.search_template_with_options, request, runtime)
    body = response.body
    raw = body.to_map() if body else {}
    templates = (raw.get("TemplateList") or {}).get("Template") or []
    for t in templates:
        if (t.get("Name") or t.get("name")) == name:
            return t.get("Id") or t.get("id")
    return None


async def create_template(client: MTSClient, name: str) -> str:
    container = json.dumps({"Format": "mp4"}, ensure_ascii=False)
    video = json.dumps({"Codec": "H.264", "Profile": "high", "Remove": "false"}, ensure_ascii=False)
    audio = json.dumps({"Codec": "AAC", "Remove": "false"}, ensure_ascii=False)
    trans_config = json.dumps(
        {"TransMode": "onepass", "IsCheckVideoBitrate": "false", "IsCheckAudioBitrate": "false"},
        ensure_ascii=False,
    )

    request = mts_models.AddTemplateRequest(
        name=name,
        container=container,
        video=video,
        audio=audio,
        trans_config=trans_config,
    )
    runtime = RuntimeOptions()
    runtime.connect_timeout = 10_000
    runtime.read_timeout = 15_000
    response = await asyncio.to_thread(client.add_template_with_options, request, runtime)
    body = response.body
    raw = body.to_map() if body else {}
    template = raw.get("Template") or {}
    tid = template.get("Id") or template.get("id")
    if not tid:
        raise RuntimeError(f"AddTemplate 未返回 Id: {raw}")
    return tid


async def main() -> None:
    settings = Settings()
    client = make_client(settings)

    existing = await search_existing(client, TEMPLATE_NAME)
    if existing:
        print(f"✅ 模板已存在（不重复创建）")
        print(f"   Name: {TEMPLATE_NAME}")
        print(f"   TemplateId: {existing}")
        print(f"\n把它填进 backend/.env：")
        print(f"  ALIYUN_MPS_TEMPLATE_ID={existing}")
        return

    print(f"正在创建模板 name={TEMPLATE_NAME} ...")
    tid = await create_template(client, TEMPLATE_NAME)
    print(f"✅ 创建成功！")
    print(f"   Name: {TEMPLATE_NAME}")
    print(f"   TemplateId: {tid}")
    print(f"\n把它填进 backend/.env：")
    print(f"  ALIYUN_MPS_TEMPLATE_ID={tid}")


if __name__ == "__main__":
    asyncio.run(main())
