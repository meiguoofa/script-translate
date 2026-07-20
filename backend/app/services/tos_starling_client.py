"""Starling 专用 TOS 北京桶客户端。

桶 xzdl-starling 在北京 region，与火山 Starling API 同地域。
- 服务器在中国境内，走外网 endpoint（volces.com）即可
- 桶公开读（前缀路径公开可访问），便于 Starling 直接拉取视频
- 上传用 boto3 S3 v4 签名 + 内部走 https://tos-s3-cn-beijing.volces.com

参考 tos_singapore_client.py 的实现模式，但所有 endpoint 用北京。
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import boto3
import httpx
from botocore.client import Config

from app.config import Settings


@dataclass
class StarlingTosPresignResult:
    key: str
    presigned_url: str  # 外网预签名 PUT URL（给用户浏览器上传用）
    public_url: str  # 外网公开访问 URL（传给 Starling 让它拉取）
    tos_uri: str


class TOSStarlingClient:
    """Starling 专用 TOS 北京桶客户端。

    与 TOSSingaporeClient 区别：
    - region=cn-beijing，桶=xzdl-starling
    - 用 root 账号 AK/SK（同 starling_access_key_id/secret_access_key）
    - 只用一个外网 client（服务器在中国境内，无需内外网分离）
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        if not settings.starling_access_key_id or not settings.starling_secret_access_key:
            raise RuntimeError(
                "STARLING_ACCESS_KEY_ID / STARLING_SECRET_ACCESS_KEY 未配置（root 账号 AK/SK）"
            )
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.tos_starling_s3_public_endpoint,
            aws_access_key_id=settings.starling_access_key_id,
            aws_secret_access_key=settings.starling_secret_access_key,
            region_name=settings.tos_starling_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )

    @property
    def bucket(self) -> str:
        return self._settings.tos_starling_bucket

    def public_url(self, key: str) -> str:
        encoded = "/".join(quote(part, safe="") for part in key.split("/"))
        return f"https://{self.bucket}.{self._settings.tos_starling_public_endpoint}/{encoded}"

    def tos_uri(self, key: str) -> str:
        return f"tos://{self.bucket}/{key}"

    def presign_put(
        self, key: str, content_type: str | None = None, expires_in: int = 3600
    ) -> StarlingTosPresignResult:
        """生成外网预签名 PUT URL（给用户浏览器上传用）。"""
        params = {"Bucket": self.bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        url = self._client.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=expires_in, HttpMethod="PUT"
        )
        return StarlingTosPresignResult(
            key=key,
            presigned_url=url,
            public_url=self.public_url(key),
            tos_uri=self.tos_uri(key),
        )

    def presign_multipart_put(
        self,
        key: str,
        content_type: str | None,
        file_size: int,
        part_size: int = 8 * 1024 * 1024,
        expires_in: int = 3600,
    ) -> StarlingTosPresignResult:
        """分片上传：init + 为每个 part 签 PUT URL。

        part_size 默认 8MB，与 TOS 新加坡客户端对齐。
        """
        # 1. init multipart
        params = {"Bucket": self.bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        init_resp = self._client.create_multipart_upload(**params)
        upload_id = init_resp["UploadId"]

        # 2. 为每个 part 签 URL
        parts: list[dict] = []
        offset = 0
        part_number = 1
        while offset < file_size:
            size = min(part_size, file_size - offset)
            url = self._client.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "UploadId": upload_id,
                    "PartNumber": part_number,
                },
                ExpiresIn=expires_in,
                HttpMethod="PUT",
            )
            parts.append(
                {"part_number": part_number, "offset": offset, "size": size, "presigned_url": url}
            )
            offset += size
            part_number += 1

        return StarlingTosPresignResult(
            key=key,
            presigned_url="",  # 分片模式不用单 URL
            public_url=self.public_url(key),
            tos_uri=self.tos_uri(key),
        ), {"upload_id": upload_id, "parts": parts, "part_size": part_size}

    def upload_file(
        self, key: str, file_path: str, content_type: str | None = None
    ) -> None:
        """服务器端直接上传本地文件到 TOS（用于归档 Starling 产物）。"""
        extra_args = {"ContentType": content_type} if content_type else None
        self._client.upload_file(file_path, self.bucket, key, ExtraArgs=extra_args)

    def download_url_to_file(self, source_url: str, file_path: str) -> None:
        """从 URL 下载到本地文件（用于拉取 Starling 产物）。"""
        with httpx.Client(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
            with client.stream("GET", source_url) as resp:
                resp.raise_for_status()
                with open(file_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)

    def abort_multipart(self, key: str, upload_id: str) -> None:
        self._client.abort_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload_id)

    def complete_multipart(self, key: str, upload_id: str, parts: list[tuple[int, str]]) -> dict:
        """parts: [(part_number, etag), ...]"""
        parts_data = [{"PartNumber": pn, "ETag": etag} for pn, etag in parts]
        resp = self._client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts_data},
        )
        return {"location": resp.get("Location", ""), "key": key}
