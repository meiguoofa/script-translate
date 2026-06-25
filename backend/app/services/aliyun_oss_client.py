from __future__ import annotations

import logging
import os
import tempfile
import time
from dataclasses import dataclass
from urllib.parse import quote

import httpx
import oss2
import oss2.defaults
from oss2.exceptions import RequestError

from app.config import Settings

# oss2.defaults.request_retries 只影响列举迭代器，不影响 upload_part。
# 我们自己在 _upload_part_with_retry 里做业务级重试。
oss2.defaults.request_retries = 10

logger = logging.getLogger("aliyun_oss_client")

PART_SIZE = 5 * 1024 * 1024  # 5MB
MAX_PART_RETRIES = 6
RETRY_BACKOFF_BASE = 2  # 指数退避：2, 4, 8, 16, 32, 64 秒


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
        self._bucket = self._fresh_bucket()

    def _fresh_bucket(self) -> oss2.Bucket:
        """每次重试前重建 Bucket 对象，避免复用被切断的 keep-alive 连接。"""

        return oss2.Bucket(
            self._auth,
            f"https://{self._settings.aliyun_oss_endpoint}",
            self._settings.aliyun_oss_bucket,
            connect_timeout=60,
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
        """Download `source_url` to a temp file, then upload to OSS with per-part retry.

        不用 oss2.resumable_upload —— 它的 __upload_part 零重试，单个 part SSL EOF
        就让整个 multipart upload 失败。我们自己管理 uploadId + 逐 part 重试 + 断点续传。
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

            self._multipart_upload_with_retry(key, tmp_path, content_type, total)
            logger.info(
                "uploaded → oss://%s/%s (%d bytes)", self.bucket_name, key, total
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _multipart_upload_with_retry(
        self, key: str, file_path: str, content_type: str, total_size: int
    ) -> None:
        """断点续传 + 每个 part 单独重试。"""

        # 复用未完成的 multipart upload（断点续传）
        upload_id, uploaded_parts = self._find_or_init_upload(key, content_type)
        logger.info(
            "multipart upload key=%s upload_id=%s, already uploaded %d parts",
            key,
            upload_id,
            len(uploaded_parts),
        )

        try:
            part_infos: list[oss2.models.PartInfo] = []
            part_number = 1
            offset = 0
            while offset < total_size:
                size = min(PART_SIZE, total_size - offset)
                if part_number in uploaded_parts:
                    # 断点续传：跳过已上传的 part
                    part_infos.append(
                        oss2.models.PartInfo(
                            part_number, uploaded_parts[part_number], size=size
                        )
                    )
                else:
                    etag = self._upload_part_with_retry(
                        key, upload_id, part_number, file_path, offset, size
                    )
                    part_infos.append(
                        oss2.models.PartInfo(part_number, etag, size=size)
                    )
                offset += size
                part_number += 1

            self._bucket.complete_multipart_upload(key, upload_id, part_infos)
            logger.info("multipart complete: %s, %d parts", key, len(part_infos))
        except Exception:
            # 整体失败时 abort，避免占用 OSS 存储
            try:
                self._fresh_bucket().abort_multipart_upload(key, upload_id)
                logger.warning("aborted multipart upload %s (upload_id=%s)", key, upload_id)
            except Exception:  # noqa: BLE001
                pass
            raise

    def _find_or_init_upload(
        self, key: str, content_type: str
    ) -> tuple[str, dict[int, str]]:
        """找同 key 未完成的 multipart upload（断点续传），否则新建。"""

        bucket = self._fresh_bucket()
        for u in oss2.MultipartUploadIterator(bucket, prefix=key):
            if u.key == key:
                upload_id = u.upload_id
                parts: dict[int, str] = {}
                for p in bucket.list_parts(key, upload_id).parts:
                    parts[p.part_number] = p.etag
                return upload_id, parts

        # 新建
        result = bucket.init_multipart_upload(
            key, headers={"Content-Type": content_type}
        )
        return result.upload_id, {}

    def _upload_part_with_retry(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        file_path: str,
        offset: int,
        size: int,
    ) -> str:
        """上传单个 part，遇到网络错误重试 MAX_PART_RETRIES 次，指数退避。"""

        last_exc: Exception | None = None
        for attempt in range(MAX_PART_RETRIES):
            try:
                bucket = self._fresh_bucket()
                with open(file_path, "rb") as f:
                    f.seek(offset)
                    result = bucket.upload_part(
                        key,
                        upload_id,
                        part_number,
                        oss2.SizedFileAdapter(f, size),
                    )
                return result.etag
            except (RequestError, oss2.exceptions.OssError) as exc:
                last_exc = exc
                wait = RETRY_BACKOFF_BASE ** attempt
                logger.warning(
                    "part %d upload failed (attempt %d/%d): %s, retry in %ds",
                    part_number,
                    attempt + 1,
                    MAX_PART_RETRIES,
                    str(exc)[:200],
                    wait,
                )
                time.sleep(wait)

        raise RuntimeError(
            f"part {part_number} upload failed after {MAX_PART_RETRIES} retries: {last_exc}"
        )
