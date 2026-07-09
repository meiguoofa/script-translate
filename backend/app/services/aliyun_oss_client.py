from __future__ import annotations

import logging
import os
import tempfile
import time
from dataclasses import dataclass
from urllib.parse import quote, urlparse

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
COPY_RETRIES = 4
MULTIPART_PART_SIZE = 8 * 1024 * 1024  # 8MB/片（前端分片上传）


@dataclass
class PresignedPutResult:
    key: str
    presigned_url: str
    public_url: str
    oss_uri: str


@dataclass
class PresignedMultipartPart:
    part_number: int
    offset: int
    size: int
    presigned_url: str


@dataclass
class PresignedMultipartResult:
    key: str
    upload_id: str
    public_url: str
    oss_uri: str
    parts: list[PresignedMultipartPart]


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

    @staticmethod
    def parse_oss_uri(oss_uri: str) -> tuple[str, str]:
        """`oss://bucket/key1/key2` → (bucket, "key1/key2")。"""

        if not oss_uri.startswith("oss://"):
            raise ValueError(f"非法 OSS URI: {oss_uri}")
        rest = oss_uri[len("oss://"):]
        parts = rest.split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""
        return bucket, key

    def get_object_text(self, key: str, *, encoding: str = "utf-8") -> str:
        """读取 OSS 对象为文本（用于 SRT 文件）。"""

        bucket = self._fresh_bucket()
        stream = bucket.get_object(key)
        try:
            return stream.read().decode(encoding)
        finally:
            stream.close()

    def put_object_text(self, key: str, text: str, *, content_type: str = "application/x-subrip") -> None:
        """把文本写入 OSS 对象（用于 cleaned/translated SRT）。"""

        bucket = self._fresh_bucket()
        bucket.put_object(key, text.encode("utf-8"), headers={"Content-Type": content_type})

    def download_object_to_file(self, key: str, file_path: str) -> None:
        """流式下载 OSS 对象到本地文件（用于下载 clean.mp4 做 ffmpeg 烧录）。

        用 oss2.resumable_download 做分片断点续传：
        - 默认 5MB/片，每片独立失败可重试
        - 已下载的片不重下，连接断了不用从头来
        - 跨地域（上海 OSS → 新加坡服务器）拉 200MB 大文件必须用这个
        """

        bucket = self._fresh_bucket()
        oss2.resumable_download(
            bucket,
            key,
            file_path,
            multiget_threshold=10 * 1024 * 1024,  # <10MB 直接 PUT，否则分片
            part_size=5 * 1024 * 1024,  # 5MB/片
            num_threads=4,
        )

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

    def presign_multipart_put(
        self,
        key: str,
        content_type: str,
        file_size: int,
        part_size: int = MULTIPART_PART_SIZE,
        expires_in: int = 3600,
    ) -> PresignedMultipartResult:
        """初始化 multipart upload 并为每个 part 签 PUT URL。

        前端按返回的 parts 切片并发 PUT 到 OSS，全部成功后调 complete_multipart。
        签 URL 失败时 abort 已创建的 upload，避免 OSS 残留分片计费。
        """
        bucket = self._fresh_bucket()
        ct = content_type or "video/mp4"
        init = bucket.init_multipart_upload(key, headers={"Content-Type": ct})
        upload_id = init.upload_id
        try:
            parts: list[PresignedMultipartPart] = []
            offset = 0
            part_number = 1
            while offset < file_size:
                size = min(part_size, file_size - offset)
                url = bucket.sign_url(
                    "PUT",
                    key,
                    expires_in,
                    slash_safe=True,
                    params={"uploadId": upload_id, "partNumber": str(part_number)},
                    headers={"Content-Type": ct},
                )
                parts.append(
                    PresignedMultipartPart(part_number, offset, size, url)
                )
                offset += size
                part_number += 1
            return PresignedMultipartResult(
                key=key,
                upload_id=upload_id,
                public_url=self.public_url(key),
                oss_uri=self.oss_uri(key),
                parts=parts,
            )
        except Exception:
            try:
                self._fresh_bucket().abort_multipart_upload(key, upload_id)
            except Exception:  # noqa: BLE001
                pass
            raise

    def complete_multipart(
        self, key: str, upload_id: str, parts: list[dict]
    ) -> tuple[str, str]:
        """完成分片上传。parts: [{part_number, etag}](etag 保留双引号原样回传)。

        返回 (public_url, oss_uri)。
        """
        bucket = self._fresh_bucket()
        infos = [
            oss2.models.PartInfo(p["part_number"], p["etag"]) for p in parts
        ]
        bucket.complete_multipart_upload(key, upload_id, infos)
        return self.public_url(key), self.oss_uri(key)

    def abort_multipart(self, key: str, upload_id: str) -> None:
        """幂等 abort。upload_id 不存在不算错。"""
        try:
            self._fresh_bucket().abort_multipart_upload(key, upload_id)
        except Exception:  # noqa: BLE001
            pass

    def put_object_from_url(
        self, key: str, source_url: str, content_type: str = "video/mp4"
    ) -> None:
        """把 `source_url` 的内容存到 OSS `key`。

        用阿里云 OSS 的「异步URL拉取」（AsyncFetchTask）：OSS 服务端直接从
        source_url 拉取到目标 bucket，**字节流不经过本服务器**。提交后轮询
        任务状态，直到成功/失败。

        VIAPI 输出 URL 带签名参数、所在 vigen-invi 桶是阿里云内部桶，我们
        AK 无跨桶读权限，所以不能用 copy_object。AsyncFetch 是唯一零中转方案：
        OSS 服务端用 HTTP GET 拉 source_url（带签名参数原样发出），落到目标桶。
        """

        bucket = self._fresh_bucket()
        config = oss2.models.AsyncFetchTaskConfiguration(
            url=source_url,
            object_name=key,
            ignore_same_key=False,
        )
        result = bucket.put_async_fetch_task(config)
        task_id = result.task_id
        logger.info(
            "async fetch task submitted: url=%s → oss://%s/%s, task_id=%s",
            source_url[:100],
            self.bucket_name,
            key,
            task_id,
        )

        # 轮询任务状态：OSS 异步拉取通常 10-60 秒完成（取决于源文件大小）
        deadline = time.monotonic() + 600  # 10 分钟上限
        while time.monotonic() < deadline:
            time.sleep(5)
            try:
                status_resp = self._fresh_bucket().get_async_fetch_task(task_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("get_async_fetch_task %s 出错: %s", task_id, exc)
                continue

            state = getattr(status_resp, "task_state", None) or ""
            error_msg = getattr(status_resp, "error_msg", None) or ""
            logger.info(
                "async fetch %s state=%s error=%s",
                task_id,
                state,
                error_msg[:100],
            )

            if state == "Success":
                # 验证对象确实存在
                try:
                    meta = self._fresh_bucket().head_object(key)
                    logger.info(
                        "async fetch done: oss://%s/%s (%d bytes)",
                        self.bucket_name,
                        key,
                        meta.content_length,
                    )
                    return
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(
                        f"async fetch reported Success but head_object failed: {exc}"
                    )
            if state in ("Failed", "Cancelled"):
                raise RuntimeError(
                    f"async fetch {task_id} {state}: {error_msg}"
                )

        raise RuntimeError(
            f"async fetch {task_id} 超时（>10 分钟），最后状态查询失败"
        )

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
