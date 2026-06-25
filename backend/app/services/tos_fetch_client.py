from __future__ import annotations

import logging
import time
from urllib.parse import quote

import tos

from app.config import Settings

logger = logging.getLogger("tos_fetch_client")

FETCH_RETRIES = 4
RETRY_BACKOFF_BASE = 2


class TOSFetchClient:
    """用火山引擎 TOS 的 fetch_object 接口把外部 URL 直接抓到 TOS 桶。

    TOS 服务端在阿里云 ↔ 火山引擎之间内网拉取，本服务器零带宽消耗。
    157MB 视频实测 ~4 秒完成。
    """

    def __init__(self, settings: Settings):
        if not settings.tos_access_key_id or not settings.tos_secret_access_key:
            raise RuntimeError("TOS_ACCESS_KEY_ID / TOS_SECRET_ACCESS_KEY 未配置")
        self._settings = settings
        endpoint = f"tos-{settings.tos_region}.volces.com"
        self._client = tos.TosClientV2(
            settings.tos_access_key_id,
            settings.tos_secret_access_key,
            endpoint,
            settings.tos_region,
            request_timeout=300,
            socket_timeout=300,
        )

    @property
    def bucket_name(self) -> str:
        return self._settings.tos_bucket

    @property
    def region(self) -> str:
        return self._settings.tos_region

    def public_url(self, key: str) -> str:
        encoded = "/".join(quote(p, safe="") for p in key.split("/"))
        return f"https://{self.bucket_name}.tos-{self.region}.volces.com/{encoded}"

    def tos_uri(self, key: str) -> str:
        return f"tos://{self.bucket_name}/{key}"

    def fetch_from_url(self, key: str, source_url: str) -> tuple[str, str, int]:
        """让 TOS 服务端从 source_url 拉取到 key。返回 (tos_uri, public_url, size_bytes)。"""

        last_exc: Exception | None = None
        for attempt in range(FETCH_RETRIES):
            try:
                start = time.time()
                out = self._client.fetch_object(
                    self.bucket_name, key, source_url, ignore_same_key=True
                )
                # fetch_object 同步返回；head 取大小确认
                head = self._client.head_object(self.bucket_name, key)
                size = head.content_length
                logger.info(
                    "fetch_object ok: %s → tos://%s/%s (%d bytes, %.1fs)",
                    source_url[:100],
                    self.bucket_name,
                    key,
                    size,
                    time.time() - start,
                )
                return self.tos_uri(key), self.public_url(key), size
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                wait = RETRY_BACKOFF_BASE ** attempt
                logger.warning(
                    "fetch_object failed (attempt %d/%d): %s, retry in %ds",
                    attempt + 1,
                    FETCH_RETRIES,
                    str(exc)[:200],
                    wait,
                )
                time.sleep(wait)

        raise RuntimeError(
            f"fetch_object from {source_url[:100]} failed after {FETCH_RETRIES} retries: {last_exc}"
        )
