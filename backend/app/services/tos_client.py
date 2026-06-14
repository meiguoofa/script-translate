from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote

import boto3
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
