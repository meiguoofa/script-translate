from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from urllib.parse import quote

import httpx
import oss2

from app.config import Settings

logger = logging.getLogger("aliyun_oss_client")


@dataclass
class PresignedPutResult:
    key: str
    presigned_url: str
    public_url: str
    oss_uri: str


class AliyunOSSClient:
    """Wrapper around `oss2.Bucket` targeting the 视频超分辨 bucket."""

    def __init__(self, settings: Settings):
        if not settings.aliyun_access_key_id or not settings.aliyun_access_key_secret:
            raise RuntimeError("ALIBABA_CLOUD_ACCESS_KEY_ID / SECRET 未配置")
        self._settings = settings
        self._auth = oss2.Auth(
            settings.aliyun_access_key_id, settings.aliyun_access_key_secret
        )
        self._bucket = oss2.Bucket(
            self._auth,
            f"https://{settings.aliyun_oss_endpoint}",
            settings.aliyun_oss_bucket,
        )

    @property
    def bucket_name(self) -> str:
        return self._settings.aliyun_oss_bucket

    @property
    def endpoint(self) -> str:
        return self._settings.aliyun_oss_endpoint

    def public_url(self, key: str) -> str:
        encoded = "/".join(quote(p, safe="") for p in key.split("/"))
        return f"https://{self.bucket_name}.{self.endpoint}/{encoded}"

    def oss_uri(self, key: str) -> str:
        return f"oss://{self.bucket_name}/{key}"

    def presign_put(
        self, key: str, content_type: str | None = None, expires_in: int = 3600
    ) -> PresignedPutResult:
        headers = {"Content-Type": content_type} if content_type else None
        url = self._bucket.sign_url(
            "PUT",
            key,
            expires_in,
            slash_safe=True,
            headers=headers,
        )
        return PresignedPutResult(
            key=key,
            presigned_url=url,
            public_url=self.public_url(key),
            oss_uri=self.oss_uri(key),
        )

    def put_object_from_url(
        self, key: str, source_url: str, content_type: str = "video/mp4"
    ) -> None:
        """Stream-download `source_url` to a temp file, then resumable-upload to OSS.

        VIAPI 输出视频通常几十 ~ 几百 MB；用 oss2.resumable_upload 做分片上传更稳健，
        避免单次 PUT 因网络抖动超时。
        """

        tmp = tempfile.NamedTemporaryFile(prefix="vsr-", suffix=".mp4", delete=False)
        tmp_path = tmp.name
        tmp.close()
        try:
            total = 0
            with httpx.stream(
                "GET",
                source_url,
                timeout=httpx.Timeout(60.0, read=300.0),
                follow_redirects=True,
            ) as r:
                r.raise_for_status()
                with open(tmp_path, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)
                        total += len(chunk)
            logger.info("downloaded %d bytes from VIAPI → %s", total, tmp_path)

            headers = {"Content-Type": content_type}
            oss2.resumable_upload(
                self._bucket,
                key,
                tmp_path,
                headers=headers,
                multipart_threshold=10 * 1024 * 1024,
                part_size=5 * 1024 * 1024,
                num_threads=4,
            )
            logger.info(
                "uploaded → oss://%s/%s (%d bytes)", self.bucket_name, key, total
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
