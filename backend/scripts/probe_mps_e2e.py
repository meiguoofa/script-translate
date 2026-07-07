"""MPS 端到端冒烟测：clean.mp4 + zh.srt → ASS → MPS SubmitJobs → output.mp4

用 OSS 上现成的 28MB clean.mp4 + 570 字节 zh.srt 跑完整流程，计时并验证 output。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.services.aliyun_oss_client import AliyunOSSClient
from app.services.ffmpeg_burn import probe_video_size
from app.services.mps_client import MPSClient
from app.services.srt_utils import parse_srt, srt_to_ass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mps_e2e")

# OSS 上现成的冒烟素材
INPUT_OSS = "oss://xzdl-shortdrama/subtitle-erase-output/0728050a-4583-44df-91a6-480adac26ef1/drama-00/ep00-Adobe_Express_-_1335269607-1-192__1_.clean.mp4"
SRT_OSS = "oss://xzdl-shortdrama/subtitle-erase-output/0728050a-4583-44df-91a6-480adac26ef1/drama-00/ep00-Adobe_Express_-_1335269607-1-192__1_.zh.srt"
OUTPUT_OSS = "oss://xzdl-shortdrama/mps-e2e-test/output.mp4"
ASS_OSS = "oss://xzdl-shortdrama/mps-e2e-test/burn.ass"


async def main() -> None:
    settings = Settings()
    if not settings.aliyun_mps_pipeline_id:
        print("ERROR: ALIYUN_MPS_PIPELINE_ID 未配置", file=sys.stderr)
        sys.exit(2)

    oss = AliyunOSSClient(settings)
    mps = MPSClient(settings)
    print(f"使用 TemplateId: {settings.aliyun_mps_template_id}")
    print(f"使用 PipelineId: {settings.aliyun_mps_pipeline_id}")

    t_start = time.monotonic()

    # 1. 下载 zh.srt
    print(f"\n[1/6] 下载 SRT: {SRT_OSS}")
    t0 = time.monotonic()
    _, srt_key = AliyunOSSClient.parse_oss_uri(SRT_OSS)
    srt_text = await asyncio.to_thread(oss.get_object_text, srt_key)
    print(f"  ✅ {len(srt_text)} 字节, 耗时 {time.monotonic()-t0:.2f}s")

    # 2. 探测视频宽高（ffprobe URL）
    print(f"\n[2/6] ffprobe 探测视频宽高")
    t0 = time.monotonic()
    _, video_key = AliyunOSSClient.parse_oss_uri(INPUT_OSS)
    video_url = oss.public_url(video_key)
    video_w, video_h = await asyncio.to_thread(probe_video_size, video_url)
    print(f"  ✅ {video_w}x{video_h}, 耗时 {time.monotonic()-t0:.2f}s")

    # 3. SRT → ASS
    print(f"\n[3/6] SRT → ASS 转换 + 上传 OSS")
    t0 = time.monotonic()
    entries = parse_srt(srt_text)
    print(f"  SRT 解析出 {len(entries)} 条字幕")
    ass_text = srt_to_ass(
        entries,
        video_w=video_w,
        video_h=video_h,
        placement_mode="simple_bottom",
        font_size=72,
        font_color="#FFFFFF",
        font_color_opacity=1.0,
        pos_x_ratio=0.5,
        pos_y_ratio=0.82,
        text_width_ratio=0.9,
    )
    _, ass_key = AliyunOSSClient.parse_oss_uri(ASS_OSS)
    await asyncio.to_thread(oss.put_object_text, ass_key, ass_text, **{"content_type": "text/plain"})
    print(f"  ✅ ASS 上传 {len(ass_text)} 字节, 耗时 {time.monotonic()-t0:.2f}s")
    print(f"     ASS URI: {ASS_OSS}")

    # 4. 提交 MPS SubmitJobs
    print(f"\n[4/6] 提交 MPS SubmitJobs")
    t0 = time.monotonic()
    submit = await mps.submit_subtitle_burn(
        input_oss_uri=INPUT_OSS,
        subtitle_oss_uri=ASS_OSS,
        output_oss_uri=OUTPUT_OSS,
        title="mps-e2e-test",
    )
    print(f"  ✅ JobId={submit.job_id}, 提交耗时 {time.monotonic()-t0:.2f}s")

    # 5. 轮询
    print(f"\n[5/6] 轮询任务状态（默认 10s 间隔）")
    t0 = time.monotonic()
    final = await mps.wait_for_job(
        submit.job_id,
        poll_interval_seconds=settings.ims_poll_interval_seconds,
        timeout_seconds=settings.ims_poll_timeout_seconds,
    )
    poll_duration = time.monotonic() - t0
    print(f"  ✅ State={final.state}, 轮询耗时 {poll_duration:.2f}s")
    print(f"     Output: {final.output_oss_uri}")

    # 6. 验证 output.mp4
    print(f"\n[6/6] 验证 output.mp4 在 OSS 上存在")
    t0 = time.monotonic()
    _, out_key = AliyunOSSClient.parse_oss_uri(OUTPUT_OSS)
    bucket = oss._fresh_bucket()
    import oss2
    try:
        meta = bucket.head_object(out_key)
        size_mb = meta.content_length / 1024 / 1024
        print(f"  ✅ output.mp4 存在, 大小 {size_mb:.2f} MB, 验证耗时 {time.monotonic()-t0:.2f}s")
        print(f"     公网 URL: {oss.public_url(out_key)}")
    except oss2.exceptions.NoSuchKey:
        print(f"  ❌ output.mp4 不存在！raw={final.raw}")
        sys.exit(1)

    total = time.monotonic() - t_start
    print(f"\n=== 总耗时 ===")
    print(f"  提交 + 轮询 + 验证: {total:.2f}s")
    print(f"  其中轮询等待: {poll_duration:.2f}s (MPS 实际转码耗时)")
    print(f"\n=== 成本估算 ===")
    # 视频时长未知，假设 1-2 分钟
    print(f"  按 1080p 0.065 元/min 计费，本次烧录成本约 0.07~0.13 元")


if __name__ == "__main__":
    asyncio.run(main())
