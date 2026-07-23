"""One-shot script: configure CORS rules on the Aliyun OSS bucket used by the 视频超分辨 feature.

Run after first deploy or when adding a new origin:

    cd backend
    ../.venv/bin/python scripts/setup_oss_cors.py

Reads `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET` / `ALIYUN_OSS_*`
from the standard backend `.env`. Origin list is hard-coded below; edit and re-run if it changes.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure `app` package importable when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import oss2
from oss2.models import BucketCors, CorsRule

from app.config import Settings


ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:8900",
    "https://localhost:8900",
    # 生产域名（如不同请编辑此列表后再跑一次）
    "http://45.78.235.74:8900",
    "https://45.78.235.74:8900",
    "https://xz-script-translate.local",
    # 当前生产入口 IP（2026-07-23 修复 CORS 拦截）
    "http://45.78.235.1:8900",
    "https://45.78.235.1:8900",
]


def main() -> None:
    settings = Settings()
    if not settings.aliyun_access_key_id or not settings.aliyun_access_key_secret:
        raise SystemExit("ALIBABA_CLOUD_ACCESS_KEY_ID / SECRET 未配置")

    auth = oss2.Auth(settings.aliyun_access_key_id, settings.aliyun_access_key_secret)
    bucket = oss2.Bucket(
        auth,
        f"https://{settings.aliyun_oss_endpoint}",
        settings.aliyun_oss_bucket,
    )

    rule = CorsRule(
        allowed_origins=ALLOWED_ORIGINS,
        allowed_methods=["PUT", "GET", "HEAD", "POST"],
        allowed_headers=["*"],
        expose_headers=["ETag"],
        max_age_seconds=3600,
    )
    bucket.put_bucket_cors(BucketCors([rule]))
    print(
        f"✅ CORS rules applied to bucket {settings.aliyun_oss_bucket} @ "
        f"{settings.aliyun_oss_endpoint}; origins: {ALLOWED_ORIGINS}"
    )


if __name__ == "__main__":
    main()
