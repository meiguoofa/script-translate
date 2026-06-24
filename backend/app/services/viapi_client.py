from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

from alibabacloud_tea_openapi.models import Config as OpenApiConfig
from alibabacloud_tea_util.models import RuntimeOptions
from alibabacloud_videoenhan20200320 import models as ve_models
from alibabacloud_videoenhan20200320.client import Client as VideoenhanClient

from app.config import Settings

logger = logging.getLogger("viapi_client")


@dataclass
class SuperResolveSubmitResult:
    job_id: str  # = RequestId returned by submit; used as jobId for GetAsyncJobResult


@dataclass
class SuperResolveFinalResult:
    output_video_url: str
    status: str
    raw: dict


class VIAPIClient:
    """Wrapper over alibabacloud-videoenhan20200320 SDK.

    `super_resolve_video_with_options` 在阿里云 VIAPI 中是**异步**调用：
      - 提交立即返回 `RequestId`，需以 `RequestId` 作为 `jobId` 调用
        `get_async_job_result_with_options` 轮询任务最终状态。
      - 轮询 Body 结构：`{Data: {JobId, Status, Result}}`，
        其中 `Status` 取 `PROCESSING / PROCESS_SUCCESS / PROCESS_FAILED`，
        `Result` 是 JSON 字符串，成功时包含 `{"VideoUrl": "..."}`。
    """

    def __init__(self, settings: Settings):
        if not settings.aliyun_access_key_id or not settings.aliyun_access_key_secret:
            raise RuntimeError("ALIBABA_CLOUD_ACCESS_KEY_ID / SECRET 未配置")
        self._settings = settings
        config = OpenApiConfig(
            access_key_id=settings.aliyun_access_key_id,
            access_key_secret=settings.aliyun_access_key_secret,
        )
        config.endpoint = settings.aliyun_viapi_endpoint
        self._client = VideoenhanClient(config)

    def submit_super_resolve_video(
        self, video_url: str, bit_rate: int
    ) -> SuperResolveSubmitResult:
        request = ve_models.SuperResolveVideoRequest(
            video_url=video_url,
            bit_rate=bit_rate,
        )
        runtime = RuntimeOptions()
        runtime.connect_timeout = 60_000
        runtime.read_timeout = 120_000

        response = self._client.super_resolve_video_with_options(request, runtime)
        request_id = response.body.request_id if response.body else None
        if not request_id:
            raw = response.body.to_map() if response.body else {}
            raise RuntimeError(f"VIAPI SuperResolveVideo submit 未返回 RequestId: {raw}")
        logger.info("SuperResolveVideo submitted, jobId=%s", request_id)
        return SuperResolveSubmitResult(job_id=request_id)

    def poll_job(self, job_id: str) -> dict:
        request = ve_models.GetAsyncJobResultRequest(job_id=job_id)
        runtime = RuntimeOptions()
        runtime.connect_timeout = 10_000
        runtime.read_timeout = 15_000
        response = self._client.get_async_job_result_with_options(request, runtime)
        return response.body.to_map() if response.body else {}

    def wait_for_super_resolve_video(
        self, job_id: str, *, poll_interval_seconds: int, timeout_seconds: int
    ) -> SuperResolveFinalResult:
        """Block until the async job reaches PROCESS_SUCCESS / PROCESS_FAILED or timeout."""

        deadline = time.monotonic() + max(60, timeout_seconds)
        last_raw: dict = {}
        last_status: str | None = None
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"VIAPI 任务 {job_id} 等待超时（>{timeout_seconds}s），last={last_raw}"
                )
            try:
                raw = self.poll_job(job_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("poll job %s 出错: %s, retrying", job_id, exc)
                time.sleep(max(1, poll_interval_seconds))
                continue
            last_raw = raw
            data = raw.get("Data", {}) or {}
            status = data.get("Status")
            if status != last_status:
                logger.info("VIAPI job %s status=%s", job_id, status)
                last_status = status
            if status == "PROCESS_SUCCESS":
                result_str = data.get("Result") or "{}"
                try:
                    parsed = json.loads(result_str)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"VIAPI 任务 {job_id} 结果不是合法 JSON: {result_str!r}"
                    ) from exc
                output_url = parsed.get("VideoUrl") or parsed.get("VideoURL")
                if not output_url:
                    raise RuntimeError(
                        f"VIAPI 任务 {job_id} Result 中缺少 VideoUrl 字段: {parsed}"
                    )
                logger.info("VIAPI job %s SUCCESS url=%s", job_id, output_url)
                return SuperResolveFinalResult(
                    output_video_url=output_url, status=status, raw=raw
                )
            if status == "PROCESS_FAILED":
                err = data.get("Result") or data.get("ErrorMessage") or str(raw)
                raise RuntimeError(f"VIAPI 任务 {job_id} 处理失败: {err}")
            # 仍在 PROCESSING / QUEUED 等中间态：继续等。
            time.sleep(max(1, poll_interval_seconds))
