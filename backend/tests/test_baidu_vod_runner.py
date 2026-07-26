import asyncio

import pytest

from app.config import Settings
from app.services import baidu_vod_runner
from app.services.baidu_vod_governor import BaiduVodGovernor


def test_build_translation_config_voice_clone_uses_tts_config_not_voice_mode():
    """VOICE_CLONE 必须以 ttsConfig.type 形式发出,且强制包含 speech。

    旧实现把 voiceMode 放在顶层,百度服务端会忽略该字段,导致 speech 流程
    移除原对白音轨却不生成配音,成片对白处静音。
    """
    snapshot = {
        "source_language": "zh-CN",
        "translation_config": {
            "translationTypeList": ["subtitle"],
            "voiceMode": "VOICE_CLONE",
        },
    }
    cfg = baidu_vod_runner._build_translation_config(snapshot, "pt-PT")

    assert cfg["sourceLanguage"] == "zh-CN"
    assert cfg["targetLanguage"] == "pt-PT"
    assert "speech" in cfg["translationTypeList"]
    assert "subtitle" in cfg["translationTypeList"]
    assert cfg["ttsConfig"] == {"type": "VOICE_CLONE"}
    assert "voiceMode" not in cfg  # 顶层 voiceMode 字段不应再被发出


def test_build_translation_config_subtitle_only_has_no_tts_config():
    """无 voice_mode 时不应该带 ttsConfig,避免误触 TTS 流程。"""
    snapshot = {
        "source_language": "zh-CN",
        "translation_config": {
            "translationTypeList": ["subtitle"],
            "voiceMode": None,
        },
    }
    cfg = baidu_vod_runner._build_translation_config(snapshot, "en-US")

    assert cfg["translationTypeList"] == ["subtitle"]
    assert "ttsConfig" not in cfg
    assert "voiceMode" not in cfg


def test_build_translation_config_ai_dub_includes_voice_list_when_provided():
    """AI_DUB 模式下若提供 voiceList 则原样透传。"""
    snapshot = {
        "source_language": "zh-CN",
        "translation_config": {
            "translationTypeList": ["subtitle", "speech"],
            "voiceMode": "AI_DUB",
            # schemas 里 voice_list 是 list[str],router 原样存到 translation_config.voiceList
            # runner 把字符串包装成 {"voiceId": ...} 以匹配百度 API 格式
            "voiceList": ["v-001"],
        },
    }
    cfg = baidu_vod_runner._build_translation_config(snapshot, "pt-PT")

    assert cfg["ttsConfig"] == {
        "type": "AI_DUB",
        "voiceList": [{"voiceId": "v-001"}],
    }


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


@pytest.mark.asyncio
async def test_fetch_media_uses_presigned_get_url_when_bos_key_available(monkeypatch):
    """当 item 有 input_bos_key 时,runner 应该生成 presigned GET URL 给 fetch_media。

    presigned URL 是认证请求(AK+签名),比 unsigned public_url 更稳健。
    """
    settings = Settings(_env_file=None, max_concurrent_baidu_vod_episodes=1)
    items = [{
        "input_oss_uri": "bos://b/a.mp4",
        "input_public_url": "https://b.bcebos.com/a.mp4",  # unsigned
        "input_bos_key": "baidu-vod-input/job/00-a.mp4",  # 有 key -> 应该 presign
        "translations": {},
        "drama_index": 0,
        "episode_index": 0,
    }]

    captured_urls: list[str] = []

    async def fake_fetch_media(*, source_url, **kwargs):
        captured_urls.append(source_url)
        class _R:
            task_id = "tsk-ok"
        return _R()

    async def fake_wait_for_fetch_media(task_id, **kwargs):
        return "mda-ok"

    async def fake_probe(*_args, **_kwargs):
        return 0.0

    async def fake_persist(*_args, **_kwargs):
        return None

    class FakeVod:
        fetch_media = staticmethod(fake_fetch_media)
        wait_for_fetch_media = staticmethod(fake_wait_for_fetch_media)

    async def fake_submit(*_args, **_kwargs):
        class _T:
            task_id = "t1"
        return [_T()]
    async def fake_wait(*_args, **_kwargs):
        class _S:
            status = "SUCCESS"
            url = "u"
            desubtitle_url = None
            cover_url = None
            source_srt_url = None
            target_srt_url = None
        return _S()
    FakeVod.submit_translation_tasks = staticmethod(fake_submit)
    FakeVod.wait_for_task = staticmethod(fake_wait)

    # Mock BaiduBOSClient.presign_get to return a fake presigned URL
    presign_called = {"n": 0}

    class FakeBosClient:
        def __init__(self, settings):
            pass

        def presign_get(self, key, expires_in=86400):
            presign_called["n"] += 1
            return f"https://b.bcebos.com/{key}?authorization=bce-auth-v1%2Ffake"

    monkeypatch.setattr(baidu_vod_runner, "BaiduBOSClient", FakeBosClient)
    monkeypatch.setattr(baidu_vod_runner, "_probe_video_duration_seconds", fake_probe)
    monkeypatch.setattr(baidu_vod_runner, "_persist_items", fake_persist)

    snapshot = {
        "baidu_project_id": "pjt-x",
        "source_language": "zh-CN",
        "target_langs": ["en-US"],
        "translation_config": {"translationTypeList": ["subtitle"]},
        "subtitle_config": {},
    }
    await baidu_vod_runner._run_episode_impl(
        None, "job-1", FakeVod(), settings, snapshot, items, 0
    )

    # 应该调用了 presign_get
    assert presign_called["n"] >= 1, presign_called
    # fetch_media 应该收到 presigned URL(含 authorization 参数),不是 unsigned public_url
    assert len(captured_urls) == 1, captured_urls
    assert "authorization=" in captured_urls[0], captured_urls[0]
    assert captured_urls[0] != "https://b.bcebos.com/a.mp4", captured_urls[0]
