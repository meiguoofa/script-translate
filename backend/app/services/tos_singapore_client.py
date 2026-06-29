from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import boto3
import httpx
from botocore.client import Config

from app.config import Settings


@dataclass
class SGPresignedPutResult:
    key: str
    presigned_url: str  # 外网预签名 URL，给用户浏览器上传用
    public_url: str  # 外网公开访问 URL
    tos_uri: str
    internal_key: str  # 内网访问时的 key（同 key，但 client 不同）


class TOSSingaporeClient:
    """新加坡 TOS 桶客户端。

    服务器在新加坡，走内网 endpoint（ivolces.com）做 IO；
    用户浏览器上传走外网 endpoint（volces.com）的预签名 URL。
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        if not settings.tos_access_key_id or not settings.tos_secret_access_key:
            raise RuntimeError("TOS_ACCESS_KEY_ID / TOS_SECRET_ACCESS_KEY 未配置")
        # 内网 client（服务器 IO 用）
        self._internal = boto3.client(
            "s3",
            endpoint_url=settings.tos_sg_s3_internal_endpoint,
            aws_access_key_id=settings.tos_access_key_id,
            aws_secret_access_key=settings.tos_secret_access_key,
            region_name=settings.tos_sg_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )
        # 外网 client（生成预签名 URL 给用户上传用）
        self._public = boto3.client(
            "s3",
            endpoint_url=settings.tos_sg_s3_public_endpoint,
            aws_access_key_id=settings.tos_access_key_id,
            aws_secret_access_key=settings.tos_secret_access_key,
            region_name=settings.tos_sg_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )

    @property
    def bucket(self) -> str:
        return self._settings.tos_sg_bucket

    def public_url(self, key: str) -> str:
        encoded = "/".join(quote(part, safe="") for part in key.split("/"))
        return f"https://{self.bucket}.{self._settings.tos_sg_public_endpoint}/{encoded}"

    def tos_uri(self, key: str) -> str:
        return f"tos://{self.bucket}/{key}"

    def presign_put(
        self, key: str, content_type: str | None = None, expires_in: int = 3600
    ) -> SGPresignedPutResult:
        """生成外网预签名 PUT URL（给用户浏览器上传用）。"""
        params = {"Bucket": self.bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        url = self._public.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=expires_in, HttpMethod="PUT"
        )
        return SGPresignedPutResult(
            key=key,
            presigned_url=url,
            public_url=self.public_url(key),
            tos_uri=self.tos_uri(key),
            internal_key=key,
        )

    def download_object_to_file(self, key: str, file_path: str) -> None:
        """内网流式下载到本地文件。"""
        url = self._internal.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=6 * 3600,
            HttpMethod="GET",
        )
        with httpx.Client(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(file_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)

    def upload_file(
        self, key: str, file_path: str, content_type: str | None = None
    ) -> None:
        """内网上传本地文件到 TOS。"""
        extra_args = {"ContentType": content_type} if content_type else None
        self._internal.upload_file(
            file_path, self.bucket, key, ExtraArgs=extra_args
        )
