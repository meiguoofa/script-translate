from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import quote

# bce-python-sdk 在 Python 3.12 下 http_headers 常量是 bytes,导致 str.startswith(bytes) 报错。
# 在 import baidubce 之前 monkey-patch:把 http_headers 模块所有 bytes 常量转 str。
import baidubce.http.http_headers as _bce_headers  # type: ignore  # noqa: E402

for _attr in dir(_bce_headers):
    if _attr.startswith("_"):
        continue
    _val = getattr(_bce_headers, _attr)
    if isinstance(_val, (bytes, bytearray)):
        setattr(_bce_headers, _attr, _val.decode("ascii"))

from baidubce import bce_client_configuration  # noqa: E402
from baidubce.auth.bce_credentials import BceCredentials  # noqa: E402
from baidubce.http import http_methods  # noqa: E402
from baidubce.services.bos.bos_client import BosClient  # noqa: E402

from app.config import Settings  # noqa: E402

logger = logging.getLogger("baidu_bos_client")

MULTIPART_PART_SIZE = 8 * 1024 * 1024  # 8MB/片(与 subtitle-erase 对齐)


@dataclass
class PresignedPutResult:
    key: str
    presigned_url: str
    public_url: str
    bos_uri: str


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
    bos_uri: str
    parts: list[PresignedMultipartPart] = field(default_factory=list)


class BaiduBOSClient:
    """百度云 BOS 客户端。封装 presign PUT / 分片上传 / complete / abort。

    前端直传 BOS,后端只做签名和 complete/abort(用 AK/SK)。
    接口与 AliyunOSSClient 对齐,前端可复用上传逻辑。
    """

    def __init__(self, settings: Settings):
        if not settings.baidu_access_key_id or not settings.baidu_access_key_secret:
            raise RuntimeError("BAIDU_ACCESS_KEY_ID / SECRET 未配置")
        if not settings.baidu_bos_bucket:
            raise RuntimeError("BAIDU_BOS_BUCKET 未配置")
        self._settings = settings
        cred = BceCredentials(settings.baidu_access_key_id, settings.baidu_access_key_secret)
        self._config = bce_client_configuration.BceClientConfiguration(
            credentials=cred,
            endpoint=settings.baidu_bos_endpoint,
        )
        self._client = BosClient(self._config)

    @property
    def bucket_name(self) -> str:
        return self._settings.baidu_bos_bucket

    @property
    def endpoint(self) -> str:
        return self._settings.baidu_bos_endpoint

    def public_url(self, key: str) -> str:
        """BOS 公网 URL: https://{bucket}.{endpoint}/{key}"""
        encoded = "/".join(quote(p, safe="") for p in key.split("/"))
        return f"https://{self.bucket_name}.{self.endpoint}/{encoded}"

    def bos_uri(self, key: str) -> str:
        return f"bos://{self.bucket_name}/{key}"

    @staticmethod
    def parse_bos_uri(bos_uri: str) -> tuple[str, str]:
        """bos://bucket/key -> (bucket, key)"""
        if not bos_uri.startswith("bos://"):
            raise ValueError(f"非法 BOS URI: {bos_uri}")
        rest = bos_uri[len("bos://"):]
        parts = rest.split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""
        return bucket, key

    def presign_put(
        self, key: str, content_type: str | None = None, expires_in: int = 3600
    ) -> PresignedPutResult:
        """签名单文件 PUT URL。前端 axios.put(url, file, headers={Content-Type})。"""
        headers = {"Content-Type": content_type} if content_type else None
        url = self._client.generate_pre_signed_url(
            bucket_name=self.bucket_name,
            key=key,
            expiration_in_seconds=expires_in,
            headers=headers,
            httpmethod=http_methods.PUT,
        )
        if isinstance(url, bytes):
            url = url.decode("ascii")
        # SDK 默认返回 http,强制 https
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        return PresignedPutResult(
            key=key,
            presigned_url=url,
            public_url=self.public_url(key),
            bos_uri=self.bos_uri(key),
        )

    def presign_multipart_put(
        self,
        key: str,
        content_type: str,
        file_size: int,
        part_size: int = MULTIPART_PART_SIZE,
        expires_in: int = 3600,
    ) -> PresignedMultipartResult:
        """初始化分片上传 + 为每个 part 签 PUT URL。

        前端按返回的 parts 切片并发 PUT 到 BOS,全部成功后调 complete_multipart。
        """
        ct = content_type or "video/mp4"
        # init multipart
        init_response = self._client.initiate_multipart_upload(
            bucket_name=self.bucket_name,
            key=key,
            content_type=ct,
        )
        upload_id = init_response.upload_id
        try:
            parts: list[PresignedMultipartPart] = []
            offset = 0
            part_number = 1
            while offset < file_size:
                size = min(part_size, file_size - offset)
                url = self._client.generate_pre_signed_url(
                    bucket_name=self.bucket_name,
                    key=key,
                    expiration_in_seconds=expires_in,
                    headers={"Content-Type": ct},
                    params={"uploadId": upload_id, "partNumber": str(part_number)},
                    httpmethod=http_methods.PUT,
                )
                if isinstance(url, bytes):
                    url = url.decode("ascii")
                if url.startswith("http://"):
                    url = "https://" + url[len("http://"):]
                parts.append(PresignedMultipartPart(part_number, offset, size, url))
                offset += size
                part_number += 1
            return PresignedMultipartResult(
                key=key,
                upload_id=upload_id,
                public_url=self.public_url(key),
                bos_uri=self.bos_uri(key),
                parts=parts,
            )
        except Exception:
            try:
                self._client.abort_multipart_upload(
                    bucket_name=self.bucket_name,
                    key=key,
                    upload_id=upload_id,
                )
            except Exception:  # noqa: BLE001
                pass
            raise

    def complete_multipart(self, key: str, upload_id: str, parts: list[dict]) -> tuple[str, str]:
        """完成分片上传。eTag 必须不带双引号(BOS 返回带引号,complete 时要去掉)。
        parts: [{part_number, etag}]
        返回 (public_url, bos_uri)。
        """
        part_list = [
            {"partNumber": p["part_number"], "eTag": (p.get("etag") or "").strip('"')}
            for p in parts
        ]
        self._client.complete_multipart_upload(
            bucket_name=self.bucket_name,
            key=key,
            upload_id=upload_id,
            part_list=part_list,
        )
        return self.public_url(key), self.bos_uri(key)

    def abort_multipart(self, key: str, upload_id: str) -> None:
        """幂等 abort。手写 host 签名。"""
        import hashlib
        import hmac
        import time as _time
        from datetime import datetime, timezone

        path = f"/{key}"
        ts = int(_time.time())
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sign_key_info = f"bce-auth-v1/{self._settings.baidu_access_key_id}/{date_str}/1800"
        sign_key = hmac.new(
            self._settings.baidu_access_key_secret.encode(),
            sign_key_info.encode(), hashlib.sha256,
        ).hexdigest()
        canonical_query = f"uploadId={upload_id}"
        canonical_headers = f"host:{self.bucket_name}.{self.endpoint}"
        sign_string = f"DELETE\n{path}\n{canonical_query}\n{canonical_headers}"
        sig = hmac.new(sign_key.encode(), sign_string.encode(), hashlib.sha256).hexdigest()
        auth = f"{sign_key_info}/host/{sig}"
        from urllib.parse import quote
        url = f"https://{self.bucket_name}.{self.endpoint}/{quote(key, safe='/')}?uploadId={upload_id}"
        import httpx
        try:
            httpx.delete(url, headers={
                "Host": f"{self.bucket_name}.{self.endpoint}",
                "Authorization": auth,
                "x-bce-date": date_str,
            }, timeout=30.0)
        except Exception:  # noqa: BLE001
            pass

    def delete_object(self, key: str) -> None:
        """删除 BOS 对象(清理测试产物用)"""
        try:
            self._client.delete_object(bucket_name=self.bucket_name, key=key)
        except Exception:  # noqa: BLE001
            logger.warning("delete_object %s failed", key, exc_info=True)
