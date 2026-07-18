import sys
from importlib import import_module, reload

import pytest
from httpx import ASGITransport, AsyncClient


def load_create_app():
    module_name = "app.main"
    if module_name in sys.modules:
        module = reload(sys.modules[module_name])
    else:
        module = import_module(module_name)
    return module.create_app


def base_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/app.db")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("DEFAULT_PROVIDER", "doubao")
    monkeypatch.setenv("DOUBAO_API_KEY", "test-key")
    monkeypatch.setenv("DOUBAO_MODELS", "doubao-seed-1-6-flash-250715")
    monkeypatch.setenv("ACCESS_PASSPHRASE", "test-pass")
    monkeypatch.setenv("BAIDU_BOS_BUCKET", "test-bucket")


def job_payload(uri: str, key: str | None) -> dict:
    return {
        "job_id": "11111111-1111-4111-8111-111111111111",
        "title": "BOS URI regression",
        "project_type": "ShortSeries",
        "source_language": "zh-CN",
        "target_langs": ["en-US"],
        "items": [
            {
                "filename": "ep.mp4",
                "oss_uri": uri,
                "public_url": "https://test-bucket.bj.bcebos.com/ep.mp4",
                "key": key,
                "drama_index": 0,
                "episode_index": 0,
            }
        ],
    }


@pytest.mark.asyncio
async def test_create_baidu_vod_job_accepts_bos_uri_and_persists_bos_metadata(
    tmp_path, monkeypatch
):
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    async def fake_runner(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.routers.baidu_vod.run_baidu_vod_job", fake_runner)

    key = "baidu-vod-input/job/00-ep.mp4"
    uri = f"bos://test-bucket/{key}"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/baidu-vod",
            json=job_payload(uri, key),
            headers={"X-Access-Passphrase": "test-pass"},
        )

    assert response.status_code == 201, response.text
    item = response.json()["items"][0]
    assert item["input_bos_key"] == key
    assert item["input_bos_uri"] == uri


@pytest.mark.asyncio
async def test_create_baidu_vod_job_rejects_oss_uri(tmp_path, monkeypatch):
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    async def fake_runner(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.routers.baidu_vod.run_baidu_vod_job", fake_runner)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/baidu-vod",
            json=job_payload("oss://legacy-bucket/ep.mp4", "ep.mp4"),
            headers={"X-Access-Passphrase": "test-pass"},
        )

    assert response.status_code == 400
    assert "bos_uri" in response.json()["detail"]
