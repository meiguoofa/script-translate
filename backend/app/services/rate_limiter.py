from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Token-bucket 风格的 async QPS 限流器。

    - `qps` = 每秒允许的调用数
    - `acquire()` 保证两次调用之间至少 `1/qps` 秒间隔
    - 限流是 per-instance 的；runner 为每个 job 实例化一份，job 间不互相饿死
    """

    def __init__(self, qps: int):
        if qps < 1:
            qps = 1
        self.qps = qps
        self._min_interval = 1.0 / qps
        self._last_call = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._last_call + self._min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()
