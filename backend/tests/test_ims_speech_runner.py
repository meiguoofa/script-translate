import json

import pytest

from app.config import Settings
from app.db import Database
from app.models import VideoImsSpeechJob
from app.services import ims_speech_runner
from app.services.ims_client import (
    SpeechTranslationFinalResult,
    SpeechTranslationLanguageResult,
    VideoTranslationSubmitResult,
)


LEGACY_CONFIG = {
    "detext_mode": "auto",
    "detext_areas": None,
    "ocr_area": None,
    "bilingual_subtitle": False,
    "subtitle_enabled": True,
    "skip_song": False,
    "font_size": 72,
    "font_color": "#FFFFFF",
    "font_color_opacity": 1,
    "subtitle_x": 0.5,
    "subtitle_y": 0.82,
    "text_width": 0.9,
}


async def create_job(
    db: Database,
    items: list[dict],
    *,
    config: dict | None = None,
) -> None:
    await db.init_models()
    async with await db.session() as session:
        session.add(
            VideoImsSpeechJob(
                id="job-1",
                title="runner test",
                drama_count=1,
                video_count=len(items),
                source_language="zh",
                target_langs_json=json.dumps(["en", "es"]),
                text_source="ASR",
                config_json=json.dumps(config or LEGACY_CONFIG),
                items_json=json.dumps(items),
                output_oss_prefix="oss://test-bucket/ims-speech-output/job-1/",
                status="pending",
            )
        )
        await session.commit()


def pending_item() -> dict:
    return {
        "index": 0,
        "drama_index": 0,
        "episode_index": 0,
        "filename": "01.mp4",
        "input_oss_uri": "oss://test-bucket/input/01.mp4",
        "input_public_url": "https://oss/input/01.mp4",
        "ims_job_id": None,
        "ims_status": None,
        "detext_video_url": None,
        "detext_video_media_id": None,
        "translations": {
            "en": {"status": "pending", "error": None},
            "es": {"status": "pending", "error": None},
        },
        "stage": "pending",
        "status": "pending",
        "error": None,
    }


@pytest.mark.asyncio
async def test_runner_submits_one_multi_language_job_and_preserves_partial_results(
    tmp_path,
    monkeypatch,
) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/app.db")
    await create_job(db, [pending_item()])
    calls = []

    class FakeClient:
        def __init__(self, _settings):
            pass

        async def submit_speech_translation(self, **kwargs):
            calls.append(kwargs)
            return VideoTranslationSubmitResult(job_id="ims-job-1")

        async def wait_for_speech_translation(self, *_args, **_kwargs):
            return SpeechTranslationFinalResult(
                state="Finished",
                detext_video_url="https://oss/clean.mp4",
                detext_video_media_id="clean-media",
                translations={
                    "en": SpeechTranslationLanguageResult(
                        media_url="https://oss/en.mp4",
                        media_id="en-media",
                        translated_audio_url="https://oss/en.wav",
                    ),
                    "es": SpeechTranslationLanguageResult(),
                },
                missing_languages=["es"],
            )

    monkeypatch.setattr(ims_speech_runner, "IMSClient", FakeClient)
    settings = Settings(
        _env_file=None,
        ALIBABA_CLOUD_ACCESS_KEY_ID="test-ak",
        ALIBABA_CLOUD_ACCESS_KEY_SECRET="test-sk",
        ALIYUN_OSS_BUCKET="test-bucket",
    )

    await ims_speech_runner.run_ims_speech_job(db, settings, "job-1")

    assert len(calls) == 1
    assert calls[0]["target_languages"] == ["en", "es"]
    assert calls[0]["output_video_oss_uri"].endswith(
        "/d01-e001-01-{language_id}.mp4"
    )
    assert calls[0].get("fe_canvas") is None
    assert calls[0]["subtitle_config"]["FontSize"] == 72
    assert calls[0]["subtitle_config"]["Y"] == 0.82
    async with await db.session() as session:
        job = await session.get(VideoImsSpeechJob, "job-1")
        items = json.loads(job.items_json)
        assert job.status == "completed"
        assert items[0]["status"] == "partial_failed"
        assert items[0]["translations"]["en"]["status"] == "succeeded"
        assert items[0]["translations"]["en"]["media_url"] == "https://oss/en.mp4"
        assert items[0]["translations"]["es"]["status"] == "failed"
        assert items[0]["detext_video_url"] == "https://oss/clean.mp4"
    await db.engine.dispose()


@pytest.mark.asyncio
async def test_runner_builds_bilingual_adaptive_v1_style(tmp_path, monkeypatch) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/app.db")
    await create_job(
        db,
        [pending_item()],
        config={
            "style_mode": "adaptive_v1",
            "detext_mode": "auto",
            "detext_areas": None,
            "ocr_area": None,
            "bilingual_subtitle": True,
            "subtitle_enabled": True,
            "skip_song": False,
            "font_color": "#FFFFFF",
            "font_color_opacity": 1,
            "subtitle_y": 0.76,
        },
    )
    calls = []

    class FakeClient:
        def __init__(self, _settings):
            pass

        async def submit_speech_translation(self, **kwargs):
            calls.append(kwargs)
            return VideoTranslationSubmitResult(job_id="ims-job-adaptive")

        async def wait_for_speech_translation(self, *_args, **_kwargs):
            return SpeechTranslationFinalResult(
                state="Finished",
                detext_video_url=None,
                detext_video_media_id=None,
                translations={
                    "en": SpeechTranslationLanguageResult(
                        media_url="https://oss/en.mp4",
                    ),
                    "es": SpeechTranslationLanguageResult(
                        media_url="https://oss/es.mp4",
                    ),
                },
                missing_languages=[],
            )

    monkeypatch.setattr(ims_speech_runner, "IMSClient", FakeClient)
    settings = Settings(
        _env_file=None,
        ALIBABA_CLOUD_ACCESS_KEY_ID="test-ak",
        ALIBABA_CLOUD_ACCESS_KEY_SECRET="test-sk",
        ALIYUN_OSS_BUCKET="test-bucket",
    )

    await ims_speech_runner.run_ims_speech_job(db, settings, "job-1")

    assert calls[0]["fe_canvas"] == {"Width": 1080, "Height": 1920}
    assert calls[0]["subtitle_config"]["FontSize"] == 67
    assert calls[0]["subtitle_config"]["X"] == 0.5
    assert calls[0]["subtitle_config"]["Y"] == 0.76
    assert calls[0]["subtitle_config"]["TextWidth"] == 0.9
    assert calls[0]["subtitle_config"]["AdaptMode"] == "AutoWrap"
    await db.engine.dispose()


@pytest.mark.asyncio
async def test_runner_retry_submits_only_languages_without_success(
    tmp_path,
    monkeypatch,
) -> None:
    item = pending_item()
    item["status"] = "partial_failed"
    item["translations"]["en"] = {
        "status": "succeeded",
        "error": None,
        "media_url": "https://oss/en.mp4",
    }
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/app.db")
    await create_job(db, [item])
    calls = []

    class FakeClient:
        def __init__(self, _settings):
            pass

        async def submit_speech_translation(self, **kwargs):
            calls.append(kwargs)
            return VideoTranslationSubmitResult(job_id="ims-job-es")

        async def wait_for_speech_translation(self, *_args, **_kwargs):
            return SpeechTranslationFinalResult(
                state="Finished",
                detext_video_url=None,
                detext_video_media_id=None,
                translations={
                    "es": SpeechTranslationLanguageResult(
                        media_url="https://oss/es.mp4",
                    )
                },
                missing_languages=[],
            )

    monkeypatch.setattr(ims_speech_runner, "IMSClient", FakeClient)
    settings = Settings(
        _env_file=None,
        ALIBABA_CLOUD_ACCESS_KEY_ID="test-ak",
        ALIBABA_CLOUD_ACCESS_KEY_SECRET="test-sk",
        ALIYUN_OSS_BUCKET="test-bucket",
    )

    await ims_speech_runner.run_ims_speech_job(
        db,
        settings,
        "job-1",
        only_indices=[0],
    )

    assert calls[0]["target_languages"] == ["es"]
    assert calls[0]["output_video_oss_uri"].endswith("/d01-e001-01-es.mp4")
    async with await db.session() as session:
        job = await session.get(VideoImsSpeechJob, "job-1")
        items = json.loads(job.items_json)
        assert items[0]["status"] == "succeeded"
        assert items[0]["translations"]["en"]["media_url"] == "https://oss/en.mp4"
        assert items[0]["translations"]["es"]["media_url"] == "https://oss/es.mp4"
    await db.engine.dispose()
