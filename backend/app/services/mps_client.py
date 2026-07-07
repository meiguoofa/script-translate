from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from alibabacloud_mts20140618 import models as mts_models
from alibabacloud_mts20140618.client import Client as MTSClient
from alibabacloud_tea_openapi.models import Config as OpenApiConfig
from alibabacloud_tea_util.models import RuntimeOptions

from app.config import Settings
from app.services.aliyun_oss_client import AliyunOSSClient
from app.services.rate_limiter import RateLimiter

logger = logging.getLogger("mps_client")


@dataclass
class MPSSubmitResult:
    job_id: str


@dataclass
class MPSFinalResult:
    state: str
    output_oss_uri: str | None
    raw: dict = field(default_factory=dict)


class MPSClient:
    """阿里云媒体处理（MPS / MTS）客户端。

    封装 SubmitJobs + QueryJobList：
      - SubmitJobs 把外部 ASS 字幕硬压到 clean.mp4，输出 output.mp4 落 OSS
      - QueryJobList 轮询任务状态到终态

    输入：clean.mp4 与 ASS 字幕文件都已在 OSS；输出：烧录好的 mp4 落 OSS。
    所有 Aliyun API 调用都过 RateLimiter，避免触发 throttling。
    """

    def __init__(self, settings: Settings, rate_limiter: RateLimiter | None = None):
        if not settings.aliyun_access_key_id or not settings.aliyun_access_key_secret:
            raise RuntimeError("ALIBABA_CLOUD_ACCESS_KEY_ID / SECRET 未配置")
        if not settings.aliyun_mps_pipeline_id:
            raise RuntimeError("ALIYUN_MPS_PIPELINE_ID 未配置")
        self._settings = settings
        config = OpenApiConfig(
            access_key_id=settings.aliyun_access_key_id,
            access_key_secret=settings.aliyun_access_key_secret,
        )
        endpoint = settings.aliyun_mps_endpoint
        config.endpoint = endpoint
        if "cn-" in endpoint or "ap-" in endpoint:
            parts = endpoint.split(".")
            if len(parts) >= 2:
                config.region_id = parts[1]
        self._client = MTSClient(config)
        self._rate_limiter = rate_limiter or RateLimiter(settings.ims_default_qps)

    async def _acquire(self) -> None:
        await self._rate_limiter.acquire()

    def _oss_uri_to_mps_input(self, oss_uri: str) -> dict[str, str]:
        """oss://bucket/key1/key2 → {"Bucket": bucket, "Location": "oss-cn-xxx", "Object": "key1/key2"}"""
        bucket, key = AliyunOSSClient.parse_oss_uri(oss_uri)
        location = f"oss-{self._settings.aliyun_oss_region}"
        return {"Bucket": bucket, "Location": location, "Object": key}

    async def submit_subtitle_burn(
        self,
        *,
        input_oss_uri: str,
        subtitle_oss_uri: str,
        output_oss_uri: str,
        title: str,
    ) -> MPSSubmitResult:
        """提交 SubmitJobs：把 subtitle.ass 硬压到 input.mp4，输出到 output_oss_uri。"""
        await self._acquire()

        video_input = self._oss_uri_to_mps_input(input_oss_uri)
        subtitle_input = self._oss_uri_to_mps_input(subtitle_oss_uri)
        out_bucket, out_object = AliyunOSSClient.parse_oss_uri(output_oss_uri)
        out_location = f"oss-{self._settings.aliyun_oss_region}"

        outputs = [
            {
                "OutputObject": out_object,
                "TemplateId": self._settings.aliyun_mps_template_id,
                "SubtitleConfig": {
                    "ExtSubtitleList": [
                        {
                            "Input": subtitle_input,
                            "CharEnc": "UTF-8",
                        }
                    ]
                },
                "UserData": title,
            }
        ]

        request = mts_models.SubmitJobsRequest(
            input=json.dumps(video_input, ensure_ascii=False),
            output_bucket=out_bucket,
            output_location=out_location,
            outputs=json.dumps(outputs, ensure_ascii=False),
            pipeline_id=self._settings.aliyun_mps_pipeline_id,
        )
        runtime = RuntimeOptions()
        runtime.connect_timeout = 60_000
        runtime.read_timeout = 120_000

        response = await asyncio.to_thread(
            self._client.submit_jobs_with_options, request, runtime
        )
        body = response.body
        if not body or not body.job_result_list or not body.job_result_list.job_result:
            raw = body.to_map() if body else {}
            raise RuntimeError(f"MPS SubmitJobs 未返回 JobResult: {raw}")
        job_result = body.job_result_list.job_result[0]
        if not job_result.success:
            raw = job_result.to_map()
            raise RuntimeError(
                f"MPS SubmitJobs 失败: code={job_result.code} message={job_result.message} raw={raw}"
            )
        job = job_result.job
        if not job or not job.job_id:
            raw = body.to_map()
            raise RuntimeError(f"MPS SubmitJobs 未返回 JobId: {raw}")
        logger.info("MPS submit_subtitle_burn job_id=%s", job.job_id)
        return MPSSubmitResult(job_id=job.job_id)

    async def _query_job(self, job_id: str) -> dict[str, Any]:
        await self._acquire()
        request = mts_models.QueryJobListRequest(job_ids=job_id)
        runtime = RuntimeOptions()
        runtime.connect_timeout = 10_000
        runtime.read_timeout = 15_000
        response = await asyncio.to_thread(
            self._client.query_job_list_with_options, request, runtime
        )
        body = response.body
        return body.to_map() if body else {}

    async def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval_seconds: int,
        timeout_seconds: int,
    ) -> MPSFinalResult:
        """轮询到任务终态（Success / Failed / Cancelled）。"""

        deadline = time.monotonic() + max(60, timeout_seconds)
        last_raw: dict = {}
        last_state: str | None = None
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"MPS 任务 {job_id} 等待超时（>{timeout_seconds}s），last={last_raw}"
                )
            try:
                raw = await self._query_job(job_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("query_job_list %s 出错: %s, retrying", job_id, exc)
                await asyncio.sleep(max(1, poll_interval_seconds))
                continue
            last_raw = raw
            job_list = (raw.get("JobList") or {}).get("Job") or []
            if not job_list:
                logger.warning("MPS QueryJobList %s 未返回任务详情", job_id)
                await asyncio.sleep(max(1, poll_interval_seconds))
                continue
            job = job_list[0]
            state = job.get("State")
            if state != last_state:
                logger.info("MPS job %s state=%s", job_id, state)
                last_state = state
            if state in ("Success", "TranscodeSuccess"):
                output_file = (job.get("Output") or {}).get("OutputFile") or {}
                out_bucket = output_file.get("Bucket")
                out_object = output_file.get("Object")
                output_oss_uri = (
                    f"oss://{out_bucket}/{out_object}"
                    if out_bucket and out_object
                    else None
                )
                return MPSFinalResult(
                    state=state, output_oss_uri=output_oss_uri, raw=raw
                )
            if state in ("Failed", "Cancelled", "TranscodeFailed"):
                err = job.get("Message") or job.get("Code") or str(raw)
                raise RuntimeError(f"MPS 任务 {job_id} {state}: {err}")
            await asyncio.sleep(max(1, poll_interval_seconds))
