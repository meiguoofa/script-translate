from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings
from app.services.baidu_vod_governor import BaiduVodGovernor

logger = logging.getLogger("baidu_vod_client")

_MAX_REQUEST_ATTEMPTS = 4
_MAX_RETRY_DELAY_SECONDS = 30.0


class BaiduVodApiError(RuntimeError):
    """Structured VOD request failure used by orchestration retry decisions."""

    def __init__(
        self,
        *,
        method: str,
        path: str,
        status_code: int | None,
        detail: str,
        retryable: bool,
    ):
        status = str(status_code) if status_code is not None else "network"
        super().__init__(f"VOD API {method} {path} failed: {status} {detail}")
        self.method = method
        self.path = path
        self.status_code = status_code
        self.retryable = retryable


def _retry_delay_seconds(attempt: int, retry_after: str | None = None) -> float:
    if retry_after:
        try:
            return min(_MAX_RETRY_DELAY_SECONDS, max(0.0, float(retry_after)))
        except ValueError:
            pass
    return min(
        _MAX_RETRY_DELAY_SECONDS,
        float(2 ** (attempt - 1)) + random.uniform(0.0, 0.25),
    )


@dataclass
class BaiduProject:
    project_id: str


@dataclass
class BaiduMediaFetchResult:
    """fetch_media 返回:上传任务 ID(不是 mediaId,需轮询拿 mediaId)"""
    task_id: str


@dataclass
class BaiduTranslationTaskResult:
    """submit_translation_tasks 单个 mediaId 的结果"""
    task_id: str
    media_id: str
    error: str | None = None


@dataclass
class BaiduTranslationTaskStatus:
    """query_tasks 单个任务状态"""
    task_id: str
    media_id: str | None
    status: str  # READY/RUNNING/SUCCESS/FAILED
    url: str | None = None  # 最终视频
    desubtitle_url: str | None = None  # 擦除后视频
    cover_url: str | None = None
    source_srt_url: str | None = None
    target_srt_url: str | None = None
    err_msg: str | None = None
    raw: dict = field(default_factory=dict)


class BaiduVodClient:
    """百度云 VOD 视频翻译客户端。

    VOD API 是 REST 形式(/v2/translation/...),bce-python-sdk 未封装,
    用 httpx + 手写 BCE V1 签名直接调。

    签名格式(新版,带 payload hash):
      signing_key = HMAC-SHA256(secret, "bce-auth-v1/{AK}/{timestamp}/{expiration}")
      canonical_request = method\npath\nquery\nheaders\nsigned_headers\npayload_hash
      signature = HMAC-SHA256(signing_key, canonical_request)
      authorization = "bce-auth-v1/{AK}/{timestamp}/{expiration}/{signed_headers}/{signature}"
    """

    def __init__(self, settings: Settings, governor: BaiduVodGovernor):
        if not settings.baidu_access_key_id or not settings.baidu_access_key_secret:
            raise RuntimeError("BAIDU_ACCESS_KEY_ID / SECRET 未配置")
        self._settings = settings
        self._ak = settings.baidu_access_key_id
        self._sk = settings.baidu_access_key_secret
        self._endpoint = settings.baidu_vod_endpoint  # vod.bj.baidubce.com
        self._base_url = f"https://{self._endpoint}"
        self._governor = governor

    def _sign(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        params: dict[str, str] | None,
        timestamp: int | None = None,
        expiration_in_seconds: int = 1800,
    ) -> str:
        """生成 BCE V1 签名(与百度 VOD 官方示例一致)。

        签名串 = method\npath\nquery\ncanonical_headers
        canonical_headers 只含 host(其他 header 不参与签名)
        signing_key = HMAC-SHA256(SK, "bce-auth-v1/{AK}/{date}/{exp}")
        signature = HMAC-SHA256(signing_key, sign_string)
        authorization = "bce-auth-v1/{AK}/{date}/{exp}/host/{signature}"
        """
        import hashlib
        import hmac

        ts = timestamp or int(time.time())
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # sign key info(HMAC,不是 SHA256 digest)
        sign_key_info = f"bce-auth-v1/{self._ak}/{date_str}/{expiration_in_seconds}"
        sign_key = hmac.new(
            self._sk.encode("ascii"),
            sign_key_info.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

        # canonical query string:按 key 字典序,url-encode 值
        if params:
            sorted_items = sorted(params.items())
            canonical_query = "&".join(
                f"{quote(k, safe='')}={quote(str(v), safe='')}" for k, v in sorted_items
            )
        else:
            canonical_query = ""

        # canonical headers:只签 host(与官方示例一致)
        canonical_headers = f"host:{self._endpoint}"

        # 签名串:4 段(method/path/query/canonical_headers)
        sign_string = "\n".join([
            method.upper(),
            path,
            canonical_query,
            canonical_headers,
        ])

        signature = hmac.new(
            sign_key.encode("ascii"),
            sign_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # signed_headers = "host"
        authorization = f"{sign_key_info}/host/{signature}"
        return authorization

    async def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        params: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> dict:
        """发 HTTP 请求,带 BCE V1 签名。返回 JSON dict。"""
        url = self._base_url + path
        if params:
            qs = "&".join(f"{quote(k, safe='')}={quote(str(v), safe='')}" for k, v in sorted(params.items()))
            url = f"{url}?{qs}"

        body_bytes = b""
        if body is not None:
            body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")

        base_headers = {
            "Host": self._endpoint,
            "Content-Type": "application/json",
        }
        if body_bytes:
            base_headers["Content-Length"] = str(len(body_bytes))

        method = method.upper()
        for attempt in range(1, _MAX_REQUEST_ATTEMPTS + 1):
            headers = dict(base_headers)
            ts = int(time.time())
            headers["x-bce-date"] = datetime.fromtimestamp(
                ts, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            headers["Authorization"] = self._sign(
                method, path, headers, params or {}, timestamp=ts
            )

            await self._governor.acquire_request()
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.request(
                        method, url, headers=headers, content=body_bytes
                    )
            except httpx.TransportError as exc:
                retryable = method == "GET"
                error = BaiduVodApiError(
                    method=method,
                    path=path,
                    status_code=None,
                    detail=str(exc)[:500],
                    retryable=retryable,
                )
                if retryable and attempt < _MAX_REQUEST_ATTEMPTS:
                    delay = _retry_delay_seconds(attempt)
                    logger.warning(
                        "VOD API %s %s network error, attempt=%d/%d retry_in=%.2fs",
                        method,
                        path,
                        attempt,
                        _MAX_REQUEST_ATTEMPTS,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(
                    "VOD API %s %s network error after attempt=%d/%d",
                    method,
                    path,
                    attempt,
                    _MAX_REQUEST_ATTEMPTS,
                )
                raise error from exc

            if resp.status_code < 400:
                if not resp.text:
                    return {}
                try:
                    return resp.json()
                except Exception:
                    return {"raw_text": resp.text}

            retryable = resp.status_code == 429 or (
                method == "GET" and 500 <= resp.status_code < 600
            )
            error = BaiduVodApiError(
                method=method,
                path=path,
                status_code=resp.status_code,
                detail=resp.text[:500],
                retryable=retryable,
            )
            if retryable and attempt < _MAX_REQUEST_ATTEMPTS:
                delay = _retry_delay_seconds(
                    attempt,
                    resp.headers.get("Retry-After"),
                )
                logger.warning(
                    "VOD API %s %s status=%d attempt=%d/%d retry_in=%.2fs",
                    method,
                    path,
                    resp.status_code,
                    attempt,
                    _MAX_REQUEST_ATTEMPTS,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            logger.error(
                "VOD API %s %s failed: status=%d attempt=%d/%d",
                method,
                path,
                resp.status_code,
                attempt,
                _MAX_REQUEST_ATTEMPTS,
            )
            raise error

        raise AssertionError("unreachable")

    # ===== API 方法 =====

    async def create_project(
        self, name: str, description: str = "", project_type: str = "ShortSeries"
    ) -> BaiduProject:
        """创建翻译项目(一部短剧一个)。"""
        body = {"name": name, "description": description, "type": project_type}
        result = await self._request("POST", "/v2/translation/project", body=body)
        project_id = result.get("projectId")
        if not project_id:
            raise RuntimeError(f"create_project 未返回 projectId: {result}")
        logger.info("VOD create_project name=%s -> projectId=%s", name, project_id)
        return BaiduProject(project_id=project_id)

    async def fetch_media(
        self, source_url: str, name: str, delete_after_seconds: int | None = None
    ) -> BaiduMediaFetchResult:
        """拉取上传:从公网 URL 拉取视频到 VOD 媒资库。返回上传任务 ID。

        拉取完成后需轮询 query_fetch_task 拿 mediaId。
        """
        body: dict[str, Any] = {"url": source_url, "name": name}
        if delete_after_seconds is not None:
            body["deleteAfterSeconds"] = delete_after_seconds
        result = await self._request("POST", "/v2/medias/fetch", body=body)
        task_id = result.get("taskId")
        if not task_id:
            raise RuntimeError(f"fetch_media 未返回 taskId: {result}")
        logger.info("VOD fetch_media url=%s -> taskId=%s", source_url[:80], task_id)
        return BaiduMediaFetchResult(task_id=task_id)

    async def query_fetch_task(self, task_id: str) -> dict:
        """查询拉取上传任务状态,成功后含 mediaId。路径:GET /v2/tasks/{taskId}"""
        result = await self._request(
            "GET", f"/v2/tasks/{task_id}", params={}
        )
        return result

    async def wait_for_fetch_media(
        self, task_id: str, *, poll_interval: int = 10, timeout: int = 600
    ) -> str:
        """轮询拉取上传任务,返回 mediaId。"""
        deadline = time.monotonic() + timeout
        last_status = None
        while time.monotonic() < deadline:
            try:
                result = await self.query_fetch_task(task_id)
                status = result.get("status") or ""
                if status != last_status:
                    logger.info("VOD fetch task %s status=%s", task_id, status)
                    last_status = status
                # SUCCESS 时 mediaId 在 mediaFetchTaskInfo.mediaBasicInfo.mediaId
                if status in ("SUCCESS", "FINISHED", "FINISH", "FINISHED"):
                    media_info = result.get("mediaFetchTaskInfo") or {}
                    basic_info = media_info.get("mediaBasicInfo") or {}
                    media_id = (
                        basic_info.get("mediaId")
                        or media_info.get("mediaId")
                        or result.get("mediaId")
                    )
                    if media_id:
                        return media_id
                    raise RuntimeError(f"fetch task SUCCESS 但无 mediaId: {result}")
                if status in ("FAILED", "FAIL", "ERROR"):
                    err = result.get("errMsg") or result.get("error") or str(result)
                    raise RuntimeError(f"fetch task {task_id} FAILED: {err}")
            except BaiduVodApiError as exc:
                if not exc.retryable:
                    raise
                logger.warning(
                    "query_fetch_task %s 临时失败: %s, retrying",
                    task_id,
                    exc,
                )
            except RuntimeError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("query_fetch_task %s 出错: %s", task_id, exc)
            await asyncio.sleep(poll_interval)
        raise RuntimeError(f"fetch task {task_id} 等待 mediaId 超时(>{timeout}s)")

    async def submit_translation_tasks(
        self,
        project_id: str,
        media_id_list: list[str],
        translation_config: dict,
        subtitle_config: dict,
    ) -> list[BaiduTranslationTaskResult]:
        """批量提交翻译任务。每个 mediaId 返回独立 taskId。"""
        body = {
            "projectId": project_id,
            "mediaIdList": media_id_list,
            "translationConfig": translation_config,
            "subtitleConfig": subtitle_config,
        }
        result = await self._request("POST", "/v2/translation/tasks", body=body)
        task_list = result.get("translationTaskCreateResultList") or []
        if not task_list:
            raise RuntimeError(f"submit_translation_tasks 未返回任务列表: {result}")
        out: list[BaiduTranslationTaskResult] = []
        for t in task_list:
            out.append(
                BaiduTranslationTaskResult(
                    task_id=t.get("taskId", ""),
                    media_id=t.get("mediaId", ""),
                    error=t.get("errMsg") or t.get("error"),
                )
            )
        logger.info(
            "VOD submit_translation_tasks project=%s media=%d -> %d tasks",
            project_id, len(media_id_list), len(out),
        )
        return out

    async def query_tasks(
        self,
        project_id: str,
        task_id: str | None = None,
        media_id: str | None = None,
    ) -> list[BaiduTranslationTaskStatus]:
        """查询项目下的翻译任务。可按 taskId 或 mediaId 过滤。"""
        params = {}
        if task_id:
            params["taskId"] = task_id
        if media_id:
            params["mediaId"] = media_id
        result = await self._request(
            "GET", f"/v2/translation/project/{project_id}/tasks", params=params
        )
        # 百度实际返回字段是 "data"(文档写的是 translationTaskList,实际不一致)
        tasks_raw = (
            result.get("data")
            or result.get("translationTaskList")
            or result.get("taskList")
            or []
        )
        out: list[BaiduTranslationTaskStatus] = []
        for t in tasks_raw:
            # mediaId 嵌套在 mediaInfo 里
            media_info = t.get("mediaInfo") or {}
            out.append(
                BaiduTranslationTaskStatus(
                    task_id=t.get("taskId", ""),
                    media_id=media_info.get("mediaId") or t.get("mediaId"),
                    status=t.get("status", ""),
                    url=t.get("url"),
                    desubtitle_url=t.get("desubtitleUrl"),
                    cover_url=t.get("coverUrl"),
                    source_srt_url=t.get("sourceSrtUrl"),
                    target_srt_url=t.get("targetSrtUrl"),
                    err_msg=t.get("errMsg"),
                    raw=t,
                )
            )
        return out

    async def wait_for_task(
        self,
        project_id: str,
        task_id: str,
        *,
        poll_interval: int = 30,
        timeout: int = 10800,
    ) -> BaiduTranslationTaskStatus:
        """轮询单个翻译任务到终态(SUCCESS/FAILED)。"""
        deadline = time.monotonic() + max(60, timeout)
        last_status = None
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"VOD task {task_id} 等待超时(>{timeout}s),last_status={last_status}"
                )
            try:
                tasks = await self.query_tasks(project_id, task_id=task_id)
            except BaiduVodApiError as exc:
                if not exc.retryable:
                    raise
                logger.warning("query_tasks %s 临时失败: %s, retrying", task_id, exc)
                await asyncio.sleep(max(5, poll_interval))
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("query_tasks %s 出错: %s, retrying", task_id, exc)
                await asyncio.sleep(max(5, poll_interval))
                continue
            if not tasks:
                logger.warning("query_tasks %s 未返回任务详情", task_id)
                await asyncio.sleep(max(5, poll_interval))
                continue
            t = tasks[0]
            if t.status != last_status:
                logger.info("VOD task %s status=%s", task_id, t.status)
                last_status = t.status
            if t.status == "SUCCESS":
                return t
            if t.status in ("FAILED", "FAIL", "ERROR"):
                err = t.err_msg or str(t.raw)
                raise RuntimeError(f"VOD task {task_id} {t.status}: {err}")
            await asyncio.sleep(max(5, poll_interval))
