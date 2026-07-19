import asyncio

import pytest

from app.config import Settings
from app.services import baidu_vod_runner
from app.services.baidu_vod_governor import BaiduVodGovernor


@pytest.mark.asyncio
async def test_episode_pipeline_concurrency_is_capped_by_governor(monkeypatch):
    settings = Settings(_env_file=None, max_concurrent_baidu_vod_episodes=2)
    governor = BaiduVodGovernor(settings)
    items = [{"translations": {}} for _ in range(5)]
    active = 0
    peak = 0

    async def fake_impl(*_args, **_kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1

    async def fake_persist(*_args, **_kwargs):
        return None

    monkeypatch.setattr(baidu_vod_runner, "_run_episode_impl", fake_impl)
    monkeypatch.setattr(baidu_vod_runner, "_persist_items", fake_persist)

    await asyncio.gather(
        *(
            baidu_vod_runner._run_episode(
                None,
                "job-1",
                None,
                settings,
                {},
                items,
                index,
                governor=governor,
            )
            for index in range(len(items))
        )
    )

    assert peak == 2
