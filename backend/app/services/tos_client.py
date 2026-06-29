from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote

import boto3
import httpx
from botocore.client import Config

from app.config import Settings


@dataclass
class PresignedPutResult:
    key: str
    presigned_url: str
    public_url: str
    tos_uri: str


class TOSClient:
    """Wrapper over boto3 S3-compatible client targeting Volcengine TOS."""

    def __init__(self, settings: Settings):
        self._settings = settings
        if not settings.tos_access_key_id or not settings.tos_secret_access_key:
            raise RuntimeError("TOS_ACCESS_KEY_ID / TOS_SECRET_ACCESS_KEY 未配置")
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.tos_s3_endpoint,
            aws_access_key_id=settings.tos_access_key_id,
            aws_secret_access_key=settings.tos_secret_access_key,
            region_name=settings.tos_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )

    @property
    def bucket(self) -> str:
        return self._settings.tos_bucket

    def public_url(self, key: str) -> str:
        encoded = "/".join(quote(part, safe="") for part in key.split("/"))
        return f"https://{self.bucket}.{self._settings.tos_public_endpoint}/{encoded}"

    def tos_uri(self, key: str) -> str:
        return f"tos://{self.bucket}/{key}"

    def presign_put(
        self, key: str, content_type: str | None = None, expires_in: int = 3600
    ) -> PresignedPutResult:
        params = {"Bucket": self.bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        url = self._client.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=expires_in, HttpMethod="PUT"
        )
        return PresignedPutResult(
            key=key,
            presigned_url=url,
            public_url=self.public_url(key),
            tos_uri=self.tos_uri(key),
        )

    def list_objects(self, prefix: str) -> list[dict]:
        paginator = self._client.get_paginator("list_objects_v2")
        result: list[dict] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for item in page.get("Contents", []) or []:
                result.append({"Key": item["Key"], "Size": item.get("Size", 0)})
        return result

    def download_object(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"].read()
        return body

    def download_object_to_file(self, key: str, file_path: str) -> None:
        """流式下载到本地文件。

        boto3 download_file 在跨地域（新加坡→北京，RTT 250ms）下极慢（0.18MB/s），
        因为它先 HeadObject 再单连接 GET，TCP 窗口涨不起来。
        改用预签名 URL + httpx 流式，实测 1.94MB/s（11 倍提升）。
        """
        url = self.presign_get(key, 6 * 3600)
        with httpx.Client(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(file_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)

    def presign_get(self, key: str, expires_in: int = 6 * 3600) -> str:
        """生成 GET 预签名 URL，供阿里云 VIAPI 临时读取私有视频。"""
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
            HttpMethod="GET",
        )

    def upload_file(
        self, key: str, file_path: str, content_type: str | None = None
    ) -> None:
        """上传本地文件到 TOS，大文件自动分片。"""
        extra_args = {"ContentType": content_type} if content_type else None
        self._client.upload_file(
            file_path, self.bucket, key, ExtraArgs=extra_args
        )


def parse_tos_uri(uri: str) -> tuple[str, str]:
    """Parse `tos://bucket/key` into (bucket, key). Trailing slash is stripped from key."""

    if not uri.startswith("tos://"):
        raise ValueError(f"不是合法的 tos uri: {uri}")
    rest = uri[len("tos://") :]
    bucket, _, key = rest.partition("/")
    return bucket, key.rstrip("/")


def filter_text_objects(items: Iterable[dict]) -> list[dict]:
    """Pick text-script-like products: .md / .txt / .markdown, sorted by Key ascending.

    LAS 短剧算子在多视频场景下会按 ep_001.md / ep_002.md 命名，按 Key 升序即可保证集顺序。
    """

    text = [
        i
        for i in items
        if i["Key"].lower().endswith((".md", ".txt", ".markdown"))
    ]
    text.sort(key=lambda x: x["Key"])
    return text
