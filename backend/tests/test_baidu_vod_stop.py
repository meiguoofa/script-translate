"""测试 stop endpoint 能真正取消正在运行的 runner asyncio task。

旧实现只改 DB status,后台 runner 不知道,继续轮询 VOD API。
新实现通过 app.state.baidu_vod_tasks 保存 Task 引用,stop 调 task.cancel()。
"""
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient


def load_create_app():
    from importlib import import_module, reload
    import sys

    module_name = "app.main"
    if module_name in sys.modules:
        return reload(sys.modules[module_name]).create_app
    return import_module(module_name).create_app


def base_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/app.db")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("DEFAULT_PROVIDER", "doubao")
    monkeypatch.setenv("DOUBAO_API_KEY", "test-key")
    monkeypatch.setenv("DOUBAO_MODELS", "doubao-seed-1-6-flash-250715")
    monkeypatch.setenv("ACCESS_PASSPHRASE", "test-pass")
    monkeypatch.setenv("BAIDU_BOS_BUCKET", "test-bucket")


def job_payload(uri: str = "bos://test-bucket/ep.mp4") -> dict:
    return {
        "job_id": "stop-test-0001",
        "title": "Stop test",
        "project_type": "ShortSeries",
        "source_language": "zh-CN",
        "target_langs": ["en-US"],
        "items": [
            {
                "filename": "ep.mp4",
                "oss_uri": uri,
                "public_url": "https://test-bucket.bj.bcebos.com/ep.mp4",
                "key": "baidu-vod-input/job/00-ep.mp4",
                "drama_index": 0,
                "episode_index": 0,
            }
        ],
    }


@pytest.mark.asyncio
async def test_stop_cancels_running_task(tmp_path, monkeypatch):
    """stop endpoint 必须把 baidu_vod_tasks 中的 asyncio.Task cancel 掉。"""
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    started = asyncio.Event()
    cancelled = {"n": 0}

    async def fake_run_baidu_vod_job(*_args, **_kwargs):
        started.set()
        try:
            await asyncio.sleep(3600)  # 模拟长轮询
        except asyncio.CancelledError:
            cancelled["n"] += 1
            raise

    monkeypatch.setattr("app.routers.baidu_vod.run_baidu_vod_job", fake_run_baidu_vod_job)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        await client.post(
            "/api/baidu-vod",
            json=job_payload(),
            headers={"X-Access-Passphrase": "test-pass"},
        )
        # 等 runner 启动
        await asyncio.wait_for(started.wait(), timeout=2.0)
        assert "stop-test-0001" in app.state.baidu_vod_tasks
        task = app.state.baidu_vod_tasks["stop-test-0001"]
        assert not task.done()

        # 模拟真实 runner 已开始执行把 status 改为 running
        # (fake runner 只 sleep 不写 DB,需要测试手动设置)
        from app.models import VideoBaiduVodJob
        async with await app.state.db.session() as session:
            job = await session.get(VideoBaiduVodJob, "stop-test-0001")
            job.status = "running"
            await session.commit()

        # 调 stop
        resp = await client.post(
            "/api/baidu-vod/stop-test-0001/stop",
            headers={"X-Access-Passphrase": "test-pass"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "failed"

    # task 应被 cancel,fake_run_baidu_vod_job 应收到 CancelledError
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError:
        pass
    except asyncio.TimeoutError:
        pass
    assert cancelled["n"] == 1, cancelled
    # task 引用应从 app.state.baidu_vod_tasks 中清理
    assert "stop-test-0001" not in app.state.baidu_vod_tasks
    await app.state.db.engine.dispose()


@pytest.mark.asyncio
async def test_stop_returns_404_for_unknown_job(tmp_path, monkeypatch):
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/api/baidu-vod/nonexistent/stop",
            headers={"X-Access-Passphrase": "test-pass"},
        )
    await app.state.db.engine.dispose()
    assert resp.status_code == 404
