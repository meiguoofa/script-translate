import asyncio
import importlib.util

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.baidu_vod_governor import BaiduVodGovernor


def test_baidu_vod_governor_module_exists():
    assert importlib.util.find_spec("app.services.baidu_vod_governor") is not None


@pytest.mark.asyncio
async def test_governor_delegates_every_request_to_one_shared_limiter(monkeypatch):
    governor = BaiduVodGovernor(Settings(_env_file=None))
    acquisitions = 0

    async def fake_acquire():
        nonlocal acquisitions
        acquisitions += 1

    monkeypatch.setattr(governor._request_limiter, "acquire", fake_acquire)

    await governor.acquire_request()
    await governor.acquire_request()

    assert acquisitions == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("slot_name", "limit"),
    [("job_slot", 2), ("episode_slot", 3)],
)
async def test_governor_caps_concurrency(slot_name, limit):
    settings = Settings(
        _env_file=None,
        max_concurrent_baidu_vod_jobs=2,
        max_concurrent_baidu_vod_episodes=3,
    )
    governor = BaiduVodGovernor(settings)
    active = 0
    peak = 0

    async def worker():
        nonlocal active, peak
        async with getattr(governor, slot_name)():
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(*(worker() for _ in range(limit + 2)))

    assert peak == limit


@pytest.mark.asyncio
async def test_governor_releases_episode_slot_after_error():
    settings = Settings(_env_file=None, max_concurrent_baidu_vod_episodes=1)
    governor = BaiduVodGovernor(settings)

    with pytest.raises(RuntimeError, match="boom"):
        async with governor.episode_slot():
            raise RuntimeError("boom")

    async with governor.episode_slot():
        acquired_again = True

    assert acquired_again is True


def test_governor_exposes_runtime_limits():
    settings = Settings(
        _env_file=None,
        baidu_vod_global_qps=7,
        max_concurrent_baidu_vod_jobs=2,
        max_concurrent_baidu_vod_episodes=4,
    )

    assert BaiduVodGovernor(settings).runtime_limits == {
        "global_qps": 7,
        "max_concurrent_jobs": 2,
        "max_concurrent_episodes": 4,
    }


def test_fastapi_app_owns_one_baidu_vod_governor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/app.db")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("DEFAULT_PROVIDER", "doubao")
    monkeypatch.setenv("DOUBAO_API_KEY", "test-key")
    monkeypatch.setenv("DOUBAO_MODELS", "test-model")

    from app.main import create_app, get_application_state

    app = create_app()

    assert isinstance(app.state.baidu_vod_governor, BaiduVodGovernor)
    assert get_application_state().baidu_vod_governor is app.state.baidu_vod_governor


def test_baidu_vod_governor_settings_have_safe_defaults():
    settings = Settings(_env_file=None)

    assert settings.baidu_vod_global_qps == 10
    assert settings.max_concurrent_baidu_vod_jobs == 3
    assert settings.max_concurrent_baidu_vod_episodes == 3


@pytest.mark.parametrize(
    "field_name",
    [
        "baidu_vod_global_qps",
        "max_concurrent_baidu_vod_jobs",
        "max_concurrent_baidu_vod_episodes",
    ],
)
def test_baidu_vod_governor_settings_reject_non_positive_values(field_name):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field_name: 0})
