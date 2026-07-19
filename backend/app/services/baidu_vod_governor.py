"""Application-scoped coordination for Baidu VOD work."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.config import Settings
from app.services.rate_limiter import RateLimiter


class BaiduVodGovernor:
    """Own the process-wide request and concurrency limits for Baidu VOD."""

    def __init__(self, settings: Settings):
        self._request_limiter = RateLimiter(settings.baidu_vod_global_qps)
        self._job_semaphore = asyncio.Semaphore(
            settings.max_concurrent_baidu_vod_jobs
        )
        self._episode_semaphore = asyncio.Semaphore(
            settings.max_concurrent_baidu_vod_episodes
        )
        self.runtime_limits = {
            "global_qps": settings.baidu_vod_global_qps,
            "max_concurrent_jobs": settings.max_concurrent_baidu_vod_jobs,
            "max_concurrent_episodes": settings.max_concurrent_baidu_vod_episodes,
        }

    async def acquire_request(self) -> None:
        await self._request_limiter.acquire()

    @asynccontextmanager
    async def job_slot(self) -> AsyncIterator[None]:
        async with self._job_semaphore:
            yield

    @asynccontextmanager
    async def episode_slot(self) -> AsyncIterator[None]:
        async with self._episode_semaphore:
            yield
