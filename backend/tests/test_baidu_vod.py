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
        target_langs=["en-US"],  # VOICE_CLONE 支持的语言
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


@pytest.mark.asyncio
async def test_create_baidu_vod_job_default_desubtitle_type_is_global(
    tmp_path, monkeypatch
):
    """默认 desubtitleType 应为 "global"。

    dialog 模式只擦 OCR 检测框,会出现"黑矩形 + 残字"问题;
    global 模式擦整片字幕区,擦除干净。
    """
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    async def fake_runner(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.routers.baidu_vod.run_baidu_vod_job", fake_runner)

    payload = job_payload("bos://test-bucket/ep.mp4", "ep.mp4")
    payload["job_id"] = "55555555-5555-5555-8555-555555555555"
    # 不传 desubtitle_type,验证默认值

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
    subtitle_config = response.json()["subtitle_config"]
    assert subtitle_config["desubtitleConfig"]["desubtitleType"] == "global", \
        subtitle_config["desubtitleConfig"]


@pytest.mark.asyncio
async def test_create_baidu_vod_job_fontconfig_nested_camelcase(
    tmp_path, monkeypatch
):
    """fontConfig 必须嵌套在 text type 下,且键为 camelCase。

    百度 API 接受的结构:
      {"dialog": {"padding": 8, "color": "#00000000",
                  "font": {"family":..., "outlineThickness":..., "outlineColor":...}}}
    扁平 snake_case 会被百度忽略,译文烧录位置/样式退回默认,
    出现"译文压在原字幕擦除区黑矩形上"的问题。
    """
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    async def fake_runner(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.routers.baidu_vod.run_baidu_vod_job", fake_runner)

    payload = job_payload("bos://test-bucket/ep.mp4", "ep.mp4")
    payload["job_id"] = "66666666-6666-6666-8666-666666666666"
    payload["font_config"] = {
        "family": "Hei", "alignment": "center", "size": 48, "bold": False,
        "color": "#FFFFFFFF", "outline_thickness": 2,
        "outline_color": "#000000FF", "padding": 8,
    }

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
    font_config = response.json()["subtitle_config"]["fontConfig"]
    assert "dialog" in font_config, font_config
    dialog = font_config["dialog"]
    assert dialog["padding"] == 8
    assert dialog["color"] == "#00000000"  # 透明背景
    font = dialog["font"]
    # camelCase 键
    assert "outlineThickness" in font, font
    assert "outlineColor" in font, font
    assert "outline_thickness" not in font, font  # 不应有 snake_case
    assert "outline_color" not in font, font
    assert font["outlineThickness"] == 2
    assert font["outlineColor"] == "#000000FF"
    assert font["family"] == "Hei"
    assert font["color"] == "#FFFFFFFF"


@pytest.mark.asyncio
async def test_create_baidu_vod_job_desubtitle_disabled_omits_desubtitle_config(
    tmp_path, monkeypatch
):
    """desubtitle_enabled=False 时不发 desubtitleConfig 字段。

    之前 router 忽略这个开关,总是发 desubtitleConfig,导致用户无法关闭擦除。
    """
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    async def fake_runner(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.routers.baidu_vod.run_baidu_vod_job", fake_runner)

    payload = job_payload("bos://test-bucket/ep.mp4", "ep.mp4")
    payload["job_id"] = "77777777-7777-7777-8777-777777777777"
    payload["desubtitle_enabled"] = False

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
    subtitle_config = response.json()["subtitle_config"]
    assert "desubtitleConfig" not in subtitle_config, subtitle_config
    # 其他字段仍然存在
    assert "fontConfig" in subtitle_config
    assert "recognitionType" in subtitle_config


@pytest.mark.asyncio
async def test_create_baidu_vod_job_accepts_voice_clone_with_pt_pt(
    tmp_path, monkeypatch
):
    """VOICE_CLONE + pt-PT 必须能提交。

    百度官方文档仅列出部分支持语言,但实际 API 接受 pt-PT + VOICE_CLONE
    并产出带葡语配音的视频(数据库有历史成功任务证据)。
    backend 不做语言白名单硬拒绝,语言支持由百度决定。
    """
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    async def fake_runner(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.routers.baidu_vod.run_baidu_vod_job", fake_runner)

    payload = job_payload("bos://test-bucket/ep.mp4", "ep.mp4")
    payload["job_id"] = "88888888-8888-4888-8888-888888888888"
    payload["translation_type_list"] = ["subtitle", "speech"]
    payload["voice_mode"] = "VOICE_CLONE"
    payload["target_langs"] = ["pt-PT"]

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
    assert body["translation_config"]["voiceMode"] == "VOICE_CLONE"


@pytest.mark.asyncio
async def test_create_baidu_vod_job_rejects_ai_dub_without_voice_list(
    tmp_path, monkeypatch
):
    """AI_DUB 必须传 voice_list(音色 ID),否则 422 拒绝。

    百度 AI_DUB 要求 voiceList 必填且只支持 1 个音色。
    缺失会被百度返回 400 InvalidParameter,在后端提前拦截更友好。
    """
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    async def fake_runner(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.routers.baidu_vod.run_baidu_vod_job", fake_runner)

    payload = job_payload("bos://test-bucket/ep.mp4", "ep.mp4")
    payload["job_id"] = "99999999-9999-4999-9999-999999999999"
    payload["translation_type_list"] = ["subtitle", "speech"]
    payload["voice_mode"] = "AI_DUB"
    payload["target_langs"] = ["pt-PT"]  # AI_DUB 支持 pt-PT
    # 不传 voice_list

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
async def test_create_baidu_vod_job_ai_dub_voicelist_persisted_as_object_array(
    tmp_path, monkeypatch
):
    """AI_DUB voice_list 在 DB 里以字符串数组保存,runner 提交百度时
    要转成 [{"voiceId": "..."}] 对象数组(百度官方文档明确要求)。
    """
    from app.services.baidu_vod_runner import _build_translation_config

    snapshot = {
        "source_language": "en-US",
        "translation_config": {
            "translationTypeList": ["subtitle", "speech"],
            "voiceMode": "AI_DUB",
            "voiceList": ["1101"],  # 字符串数组(用户输入)
        },
    }
    out = _build_translation_config(snapshot, "pt-PT")
    tts_config = out["ttsConfig"]
    assert tts_config["type"] == "AI_DUB"
    voice_list = tts_config["voiceList"]
    # 必须是对象数组,不是字符串数组
    assert isinstance(voice_list, list)
    assert len(voice_list) == 1
    assert isinstance(voice_list[0], dict), voice_list
    assert voice_list[0] == {"voiceId": "1101"}, voice_list


@pytest.mark.asyncio
async def test_create_baidu_vod_job_voice_clone_supported_lang_accepted(
    tmp_path, monkeypatch
):
    """VOICE_CLONE + 支持语言(en-US)能正常提交,不被白名单拒绝。"""
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    async def fake_runner(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.routers.baidu_vod.run_baidu_vod_job", fake_runner)

    payload = job_payload("bos://test-bucket/ep.mp4", "ep.mp4")
    payload["job_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    payload["translation_type_list"] = ["subtitle", "speech"]
    payload["voice_mode"] = "VOICE_CLONE"
    payload["target_langs"] = ["en-US"]  # VOICE_CLONE 支持

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
    assert body["translation_config"]["voiceMode"] == "VOICE_CLONE"


@pytest.mark.asyncio
async def test_create_baidu_vod_job_speech_without_voice_mode_rejected(
    tmp_path, monkeypatch
):
    """translation_type_list 含 speech 但没 voice_mode 时必须 422 拒绝。

    否则百度会移除原对白音轨但不生成配音,对白段静音。
    """
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    async def fake_runner(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.routers.baidu_vod.run_baidu_vod_job", fake_runner)

    payload = job_payload("bos://test-bucket/ep.mp4", "ep.mp4")
    payload["job_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    payload["translation_type_list"] = ["subtitle", "speech"]
    # 不传 voice_mode

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


