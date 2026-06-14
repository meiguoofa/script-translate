from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings


@dataclass
class LASSubmitResult:
    task_id: str
    raw: dict


@dataclass
class LASPollResult:
    task_status: str
    business_code: str | None
    error_msg: str | None
    data: dict | None
    raw: dict


class LASClient:
    def __init__(self, settings: Settings):
        if not settings.las_api_key:
            raise RuntimeError("LAS_API_KEY 未配置")
        self._settings = settings
        self._headers = {
            "Authorization": f"Bearer {settings.las_api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, extra: dict[str, Any]) -> dict[str, Any]:
        return {
            "operator_id": self._settings.las_operator_id,
            "operator_version": self._settings.las_operator_version,
            **extra,
        }

    async def submit(
        self,
        video_urls: list[str],
        output_tos_path: str,
        custom_script_prompt: str,
        timeout: float = 60.0,
    ) -> LASSubmitResult:
        payload = self._payload(
            {
                "data": {
                    "video_urls": video_urls,
                    "output_tos_path": output_tos_path,
                    "custom_script_prompt": custom_script_prompt,
                }
            }
        )
        url = f"{self._settings.las_base_url.rstrip('/')}/api/v1/submit"
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=self._headers)
            response.raise_for_status()
            data = response.json()
        task_id = (
            data.get("task_id")
            or (data.get("metadata") or {}).get("task_id")
            or (data.get("data") or {}).get("task_id")
        )
        if not task_id:
            raise RuntimeError(f"LAS submit 没有返回 task_id: {data}")
        return LASSubmitResult(task_id=task_id, raw=data)

    async def poll(self, task_id: str, timeout: float = 30.0) -> LASPollResult:
        payload = self._payload({"task_id": task_id})
        url = f"{self._settings.las_base_url.rstrip('/')}/api/v1/poll"
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=self._headers)
            response.raise_for_status()
            data = response.json()
        task_status = (
            data.get("task_status")
            or (data.get("metadata") or {}).get("task_status")
            or "UNKNOWN"
        )
        business_code = data.get("business_code") or (data.get("metadata") or {}).get(
            "business_code"
        )
        error_msg = data.get("error_msg") or (data.get("metadata") or {}).get("error_msg")
        return LASPollResult(
            task_status=str(task_status),
            business_code=str(business_code) if business_code is not None else None,
            error_msg=str(error_msg) if error_msg else None,
            data=data.get("data"),
            raw=data,
        )
