import asyncio
import json
import sys
from importlib import import_module, reload

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect

from app.models import VideoImsSpeechJob


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
    monkeypatch.setenv("DOUBAO_MODELS", "test-model")
    monkeypatch.setenv("ACCESS_PASSPHRASE", "test-pass")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "test-ak")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "test-sk")
    monkeypatch.setenv("ALIYUN_OSS_BUCKET", "test-bucket")


def job_payload() -> dict:
    return {
        "job_id": "11111111-1111-4111-8111-111111111111",
        "title": "IMS speech translation",
        "source_language": "zh",
        "target_languages": ["en", "es"],
        "text_source": "ASR",
        "detext_mode": "auto",
        "detext_areas": None,
        "ocr_area": None,
        "bilingual_subtitle": False,
        "subtitle_enabled": True,
        "skip_song": False,
        "font_color": "#FFFFFF",
        "font_color_opacity": 1,
        "subtitle_y": 0.76,
        "items": [
            {
                "filename": "01.mp4",
                "oss_uri": "oss://test-bucket/input/01.mp4",
                "public_url": "https://test-bucket.oss-cn-shanghai.aliyuncs.com/input/01.mp4",
                "key": "input/01.mp4",
                "drama_index": 0,
                "episode_index": 0,
            }
        ],
        "original_filenames": ["01.mp4"],
    }


@pytest.mark.asyncio
async def test_create_ims_speech_job_persists_independent_task(tmp_path, monkeypatch) -> None:
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    async def fake_runner(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.routers.ims_speech.run_ims_speech_job",
        fake_runner,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/ims-speech-translation",
            json=job_payload(),
            headers={"X-Access-Passphrase": "test-pass"},
        )
        listing = await client.get("/api/ims-speech-translation")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == job_payload()["job_id"]
    assert body["target_languages"] == ["en", "es"]
    assert body["text_source"] == "ASR"
    assert body["items"][0]["ims_job_id"] is None
    assert body["items"][0]["translations"]["en"]["status"] == "pending"
    assert body["items"][0]["translations"]["es"]["status"] == "pending"
    assert body["config"]["style_mode"] == "adaptive_v1"
    assert body["config"]["fe_canvas"] == {"Width": 1080, "Height": 1920}
    assert body["config"]["subtitle_config"]["FontSize"] == 77
    assert body["config"]["subtitle_config"]["Y"] == 0.76
    assert "font_size" not in body["config"]
    assert "subtitle_x" not in body["config"]
    assert "text_width" not in body["config"]
    assert listing.status_code == 200
    assert listing.json()[0]["title"] == "IMS speech translation"

    async with app.state.db.engine.begin() as connection:
        tables = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_table_names()
        )
    await app.state.db.engine.dispose()
    assert "video_ims_speech_jobs" in tables


@pytest.mark.asyncio
async def test_create_ignores_deprecated_manual_style_fields(
    tmp_path,
    monkeypatch,
) -> None:
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()

    async def fake_runner(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.routers.ims_speech.run_ims_speech_job", fake_runner)
    payload = job_payload()
    payload.update(
        {
            "job_id": "44444444-4444-4444-8444-444444444444",
            "font_size": 200,
            "subtitle_x": 0.2,
            "text_width": 0.4,
        }
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/ims-speech-translation",
            json=payload,
            headers={"X-Access-Passphrase": "test-pass"},
        )
        await asyncio.sleep(0)

    assert response.status_code == 201, response.text
    config = response.json()["config"]
    assert config["subtitle_config"]["FontSize"] == 77
    assert config["subtitle_config"]["X"] == 0.5
    assert config["subtitle_config"]["TextWidth"] == 0.9
    assert "font_size" not in config
    assert "subtitle_x" not in config
    assert "text_width" not in config
    await app.state.db.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text_source", "source_language"),
    [
        ("OCR", "fr"),
        ("OCR_ASR", "tr"),
        ("ASR", "ja"),
    ],
)
async def test_create_rejects_source_language_not_supported_by_recognizer(
    tmp_path,
    monkeypatch,
    text_source,
    source_language,
) -> None:
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()
    payload = job_payload()
    payload["job_id"] = "22222222-2222-4222-8222-222222222222"
    payload["text_source"] = text_source
    payload["source_language"] = source_language

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/ims-speech-translation",
            json=payload,
            headers={"X-Access-Passphrase": "test-pass"},
        )
    await app.state.db.engine.dispose()

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_requires_regions_for_custom_detext(tmp_path, monkeypatch) -> None:
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()
    payload = job_payload()
    payload["job_id"] = "33333333-3333-4333-8333-333333333333"
    payload["detext_mode"] = "custom"
    payload["detext_areas"] = None

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/ims-speech-translation",
            json=payload,
            headers={"X-Access-Passphrase": "test-pass"},
        )
    await app.state.db.engine.dispose()

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_retry_keeps_successful_language_and_resets_failed_language(
    tmp_path,
    monkeypatch,
) -> None:
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()
    runner_calls = []

    async def fake_runner(
        _db,
        _settings,
        _job_id,
        *,
        only_indices=None,
        global_rate_limiter=None,
    ):
        runner_calls.append(only_indices)

    monkeypatch.setattr("app.routers.ims_speech.run_ims_speech_job", fake_runner)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        created = await client.post(
            "/api/ims-speech-translation",
            json=job_payload(),
            headers={"X-Access-Passphrase": "test-pass"},
        )
        assert created.status_code == 201
        await asyncio.sleep(0)
        async with await app.state.db.session() as session:
            job = await session.get(VideoImsSpeechJob, job_payload()["job_id"])
            items = json.loads(job.items_json)
            items[0]["status"] = "partial_failed"
            items[0]["ims_job_id"] = "old-job"
            items[0]["translations"]["en"] = {
                "status": "succeeded",
                "error": None,
                "media_url": "https://oss/en.mp4",
            }
            items[0]["translations"]["es"] = {
                "status": "failed",
                "error": "missing",
                "media_url": None,
            }
            job.items_json = json.dumps(items)
            job.status = "completed"
            await session.commit()

        response = await client.post(
            f"/api/ims-speech-translation/{job_payload()['job_id']}/retry",
            headers={"X-Access-Passphrase": "test-pass"},
        )
        await asyncio.sleep(0)

    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["ims_job_id"] is None
    assert item["translations"]["en"]["status"] == "succeeded"
    assert item["translations"]["en"]["media_url"] == "https://oss/en.mp4"
    assert item["translations"]["es"]["status"] == "pending"
    assert runner_calls[-1] == [0]
    await app.state.db.engine.dispose()


@pytest.mark.asyncio
async def test_stop_cancels_local_tracking_and_warns_about_cloud_job(
    tmp_path,
    monkeypatch,
) -> None:
    base_env(monkeypatch, tmp_path)
    app = load_create_app()()
    started = asyncio.Event()

    async def blocking_runner(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("app.routers.ims_speech.run_ims_speech_job", blocking_runner)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        created = await client.post(
            "/api/ims-speech-translation",
            json=job_payload(),
            headers={"X-Access-Passphrase": "test-pass"},
        )
        assert created.status_code == 201
        await asyncio.wait_for(started.wait(), timeout=1)

        stopped = await client.post(
            f"/api/ims-speech-translation/{job_payload()['job_id']}/stop",
            headers={"X-Access-Passphrase": "test-pass"},
        )

    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] == "failed"
    assert "阿里云任务可能仍在执行并产生费用" in stopped.json()["error_message"]
    assert job_payload()["job_id"] not in app.state.ims_speech_tasks
    await app.state.db.engine.dispose()


@pytest.mark.asyncio
async def test_upload_url_uses_dedicated_ims_speech_prefix(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    base_env(monkeypatch, tmp_path)
    app = load_create_app()()
    captured = []

    class FakeOss:
        def __init__(self, _settings):
            pass

        def presign_put(self, key, *, content_type, expires_in):
            captured.append((key, content_type, expires_in))
            return SimpleNamespace(
                presigned_url="https://upload",
                public_url=f"https://public/{key}",
                oss_uri=f"oss://test-bucket/{key}",
                key=key,
            )

    monkeypatch.setattr("app.routers.ims_speech.AliyunOSSClient", FakeOss)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/ims-speech-translation/upload-url",
            json={
                "job_id": "upload-job",
                "files": [{"filename": "01.mp4", "content_type": "video/mp4"}],
            },
            headers={"X-Access-Passphrase": "test-pass"},
        )
    await app.state.db.engine.dispose()

    assert response.status_code == 200, response.text
    assert captured[0][0] == "ims-speech-input/upload-job/00-01.mp4"
