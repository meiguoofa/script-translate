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
async def test_create_baidu_vod_job_rejects_legacy_text_type_title(
    tmp_path, monkeypatch
):
    """百度 VOD 已将 textTypeList 的 'title' 改名为 'castName',
    后端 schema 必须把 'title' 自动映射为 'castName' 而不是直接透传,
    否则百度会返回 400 InvalidParameter(subtitleConfig.textTypeList)。
    """
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    async def fake_runner(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.routers.baidu_vod.run_baidu_vod_job", fake_runner)

    payload = job_payload("bos://test-bucket/ep.mp4", "ep.mp4")
    payload["job_id"] = "22222222-2222-4222-8222-222222222222"
    payload["text_type_list"] = ["dialog", "title"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/baidu-vod",
            json=payload,
            headers={"X-Access-Passphrase": "test-pass"},
        )
    await app.state.db.engine.dispose()

    assert response.status_code == 201, response.text
    body = response.json()
    # 后端应该把 'title' 自动映射为 'castName',而不是原样透传给百度
    assert body["subtitle_config"]["textTypeList"] == ["dialog", "castName"], \
        body["subtitle_config"]["textTypeList"]


@pytest.mark.asyncio
async def test_rerun_endpoint_normalizes_legacy_text_type_title(
    tmp_path, monkeypatch
):
    """rerun-all endpoint 也要把旧 'title' 映射为 'castName',
    保证历史任务用 rerun 时不会再次踩 400。
    """
    from app.schemas import BaiduVodRerunRequest

    # 直接在 schema 层验证,rerun-all endpoint 会用同一份 Pydantic 模型做 normalize
    req = BaiduVodRerunRequest(
        project_type="ShortSeries",
        source_language="zh-CN",
        target_langs=["pt-PT"],
        translation_type_list=["subtitle", "speech"],
        voice_mode="VOICE_CLONE",
        recognition_type="OCR",
        text_type_list=["dialog", "title"],  # 旧值
        target_subtitle_compose=True,
        desubtitle_enabled=True,
        desubtitle_model="v4",
        desubtitle_type="dialog",
        font_config={
            "family": "Hei", "alignment": "center", "size": 48, "bold": False,
            "color": "#FFFFFFFF", "outline_thickness": 2,
            "outline_color": "#000000FF", "padding": 8,
        },
    )
    assert req.text_type_list == ["dialog", "castName"], req.text_type_list


@pytest.mark.asyncio
async def test_create_baidu_vod_job_rejects_invalid_text_type(
    tmp_path, monkeypatch
):
    """非法 text_type 必须被 422 拒绝,避免错误透传到百度导致 400。"""
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    async def fake_runner(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.routers.baidu_vod.run_baidu_vod_job", fake_runner)

    payload = job_payload("bos://test-bucket/ep.mp4", "ep.mp4")
    payload["job_id"] = "44444444-4444-4444-8444-444444444444"
    payload["text_type_list"] = ["dialog", "foo"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/baidu-vod",
            json=payload,
            headers={"X-Access-Passphrase": "test-pass"},
        )
    await app.state.db.engine.dispose()

    assert response.status_code == 422, response.text


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
    await app.state.db.engine.dispose()

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
    await app.state.db.engine.dispose()

    assert response.status_code == 400
    assert "bos_uri" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_job_ignores_legacy_qps_and_records_global_limit(
    tmp_path, monkeypatch
):
    base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BAIDU_VOD_GLOBAL_QPS", "7")
    app = load_create_app()()

    async def fake_runner(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.routers.baidu_vod.run_baidu_vod_job", fake_runner)
    payload = job_payload("bos://test-bucket/ep.mp4", "ep.mp4")
    payload["qps"] = 99

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/baidu-vod",
            json=payload,
            headers={"X-Access-Passphrase": "test-pass"},
        )
    await app.state.db.engine.dispose()

    assert response.status_code == 201, response.text
    assert response.json()["qps"] == 7


@pytest.mark.asyncio
async def test_runtime_limits_endpoint_returns_effective_governor_settings(
    tmp_path, monkeypatch
):
    base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BAIDU_VOD_GLOBAL_QPS", "7")
    monkeypatch.setenv("MAX_CONCURRENT_BAIDU_VOD_JOBS", "2")
    monkeypatch.setenv("MAX_CONCURRENT_BAIDU_VOD_EPISODES", "4")
    app = load_create_app()()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        unauthorized = await client.get("/api/baidu-vod/runtime-limits")
        response = await client.get(
            "/api/baidu-vod/runtime-limits",
            headers={"X-Access-Passphrase": "test-pass"},
        )
    await app.state.db.engine.dispose()

    assert unauthorized.status_code in (401, 403)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "global_qps": 7,
        "max_concurrent_jobs": 2,
        "max_concurrent_episodes": 4,
    }
