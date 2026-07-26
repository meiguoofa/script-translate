import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.ims_client import IMSClient, parse_speech_translation_result


class NoopLimiter:
    async def acquire(self) -> None:
        return None


class CountingLimiter:
    def __init__(self) -> None:
        self.calls = 0

    async def acquire(self) -> None:
        self.calls += 1


def client_settings() -> Settings:
    return Settings(
        _env_file=None,
        ALIBABA_CLOUD_ACCESS_KEY_ID="test-ak",
        ALIBABA_CLOUD_ACCESS_KEY_SECRET="test-sk",
        ALIYUN_OSS_BUCKET="test-bucket",
        ALIYUN_OSS_ENDPOINT="oss-cn-shanghai.aliyuncs.com",
        ALIYUN_ICE_ENDPOINT="ice.cn-shanghai.aliyuncs.com",
    )


@pytest.mark.asyncio
async def test_submit_speech_translation_builds_multi_language_asr_request() -> None:
    client = IMSClient(client_settings(), rate_limiter=NoopLimiter())
    captured = {}

    def submit(request, _runtime):
        captured["request"] = request
        data = SimpleNamespace(job_id="ims-job-1")
        body = SimpleNamespace(success=True, data=data)
        return SimpleNamespace(body=body)

    client._client = SimpleNamespace(
        submit_video_translation_job_with_options=submit,
    )

    result = await client.submit_speech_translation(
        title="episode-01",
        input_video_oss_uri="oss://test-bucket/input/01.mp4",
        output_video_oss_uri="oss://test-bucket/output/01-{language_id}.mp4",
        source_language="zh",
        target_languages=["en", "es"],
        text_source="ASR",
        detext_mode="none",
        bilingual_subtitle=False,
        subtitle_enabled=True,
        fe_canvas={"Width": 1080, "Height": 1920},
        subtitle_config={
            "FontSize": 77,
            "FontColor": "#FFFFFF",
            "FontColorOpacity": 1,
            "X": 0.5,
            "Y": 0.76,
            "TextWidth": 0.9,
            "AdaptMode": "AutoWrap",
        },
        skip_song=False,
    )

    assert result.job_id == "ims-job-1"
    request = captured["request"]
    input_config = json.loads(request.input_config)
    editing_config = json.loads(request.editing_config)
    output_config = json.loads(request.output_config)
    assert input_config == {
        "Type": "Video",
        "Video": "https://test-bucket.oss-cn-shanghai.aliyuncs.com/input/01.mp4",
    }
    assert output_config["MediaURL"].endswith("/output/01-{language_id}.mp4")
    assert editing_config["SourceLanguage"] == "zh"
    assert editing_config["TargetLanguage"] == "en,es"
    assert editing_config["TextSource"] == "ASR"
    assert "DetextArea" not in editing_config
    assert editing_config["NeedSpeechTranslate"] is True
    assert editing_config["NeedFaceTranslate"] is False
    assert editing_config["FECanvas"] == {"Width": 1080, "Height": 1920}
    assert "SubtitleTranslate" not in editing_config
    assert editing_config["SpeechTranslate"]["SkipSong"] == 0
    assert editing_config["SpeechTranslate"]["SubtitleConfig"]["FontSize"] == 77
    assert (
        editing_config["SpeechTranslate"]["SubtitleConfig"]["AdaptMode"]
        == "AutoWrap"
    )


@pytest.mark.asyncio
async def test_submit_speech_translation_rejects_fixed_multi_language_output() -> None:
    client = IMSClient(client_settings(), rate_limiter=NoopLimiter())
    client._client = SimpleNamespace(
        submit_video_translation_job_with_options=lambda *_args: SimpleNamespace(
            body=SimpleNamespace(
                success=True,
                data=SimpleNamespace(job_id="must-not-submit"),
            )
        )
    )

    with pytest.raises(ValueError, match=r"\{language_id\}"):
        await client.submit_speech_translation(
            title="episode-01",
            input_video_oss_uri="oss://test-bucket/input/01.mp4",
            output_video_oss_uri="oss://test-bucket/output/01.mp4",
            source_language="zh",
            target_languages=["en", "es"],
            text_source="ASR",
            detext_mode="none",
        )


@pytest.mark.asyncio
async def test_ims_client_applies_job_and_account_rate_limits() -> None:
    job_limiter = CountingLimiter()
    account_limiter = CountingLimiter()
    client = IMSClient(
        client_settings(),
        rate_limiter=job_limiter,
        global_rate_limiter=account_limiter,
    )

    await client._acquire()

    assert job_limiter.calls == 1
    assert account_limiter.calls == 1


@pytest.mark.asyncio
async def test_submit_speech_translation_builds_ocr_custom_regions_and_hides_subtitles() -> None:
    client = IMSClient(client_settings(), rate_limiter=NoopLimiter())
    captured = {}

    def submit(request, _runtime):
        captured["request"] = request
        return SimpleNamespace(
            body=SimpleNamespace(
                success=True,
                data=SimpleNamespace(job_id="ims-job-2"),
            )
        )

    client._client = SimpleNamespace(
        submit_video_translation_job_with_options=submit,
    )

    await client.submit_speech_translation(
        title="episode-02",
        input_video_oss_uri="oss://test-bucket/input/02.mp4",
        output_video_oss_uri="oss://test-bucket/output/02.mp4",
        source_language="en",
        target_languages=["ja"],
        text_source="OCR_ASR",
        detext_mode="custom",
        detext_areas=[[0.1, 0.7, 0.8, 0.2]],
        ocr_area=[0.1, 0.7, 0.8, 0.2],
        bilingual_subtitle=True,
        subtitle_enabled=False,
        subtitle_config={"FontSize": 80, "FontColor": "#FFFFFF"},
        skip_song=True,
    )

    editing_config = json.loads(captured["request"].editing_config)
    assert editing_config["DetextArea"] == [[0.1, 0.7, 0.8, 0.2]]
    assert editing_config["BilingualSubtitle"] is True
    assert editing_config["SpeechTranslate"]["OcrArea"] == [0.1, 0.7, 0.8, 0.2]
    assert editing_config["SpeechTranslate"]["SkipSong"] == 1
    assert editing_config["SpeechTranslate"]["SubtitleConfig"]["FontSize"] == 0


def test_parse_multi_language_speech_translation_result() -> None:
    ai_result = {
        "DetextVideoURL": "https://oss/clean.mp4",
        "DetextVideoMediaId": "clean-media",
        "VideoTranslationAiResultMap": {
            "en": {
                "MediaURL": "https://oss/en.mp4",
                "MediaId": "en-media",
                "TranslatedAudioMediaURL": "https://oss/en.wav",
                "TranslatedAudioMediaId": "en-audio",
                "SpeechTranslatedSubtitleURL": "https://oss/en.srt",
                "SpeechTranslatedSubtitleURLForFix": "https://oss/en-fix.srt",
                "SpeechBilingualSubtitleURL": "https://oss/en-bi.srt",
                "SpeechTranslationJobId": "speech-en",
            },
            "es": {
                "MediaURL": "https://oss/es.mp4",
                "MediaId": "es-media",
            },
        },
    }
    raw = {
        "State": "Finished",
        "JobResult": {"AiResult": json.dumps(ai_result)},
    }

    result = parse_speech_translation_result(raw, ["en", "es"])

    assert result.detext_video_url == "https://oss/clean.mp4"
    assert result.detext_video_media_id == "clean-media"
    assert result.translations["en"].media_url == "https://oss/en.mp4"
    assert result.translations["en"].translated_audio_url == "https://oss/en.wav"
    assert result.translations["en"].fix_subtitle_url == "https://oss/en-fix.srt"
    assert result.translations["en"].speech_translation_job_id == "speech-en"
    assert result.translations["es"].media_id == "es-media"
    assert result.missing_languages == []


def test_parse_multi_language_result_uses_submitted_urls_when_ims_omits_media_url() -> None:
    ai_result = {
        "VideoTranslationAiResultMap": {
            "en": {"MediaId": "en-media"},
            "es": {"MediaId": "es-media"},
        },
    }
    raw = {
        "State": "Finished",
        "JobResult": {"AiResult": json.dumps(ai_result)},
    }

    result = parse_speech_translation_result(
        raw,
        ["en", "es"],
        output_media_url_template="https://oss/output-{language_id}.mp4",
    )

    assert result.translations["en"].media_url == "https://oss/output-en.mp4"
    assert result.translations["es"].media_url == "https://oss/output-es.mp4"
    assert result.missing_languages == []


def test_parse_single_language_result_and_reports_missing_media() -> None:
    raw = {
        "State": "Finished",
        "JobResult": {
            "AiResult": json.dumps(
                {
                    "MediaId": "en-media",
                    "SpeechTranslatedSubtitleURL": "https://oss/en.srt",
                }
            )
        },
    }

    result = parse_speech_translation_result(raw, ["en"])

    assert result.translations["en"].media_id == "en-media"
    assert result.missing_languages == ["en"]


def test_parse_speech_translation_result_rejects_invalid_ai_result() -> None:
    with pytest.raises(RuntimeError, match="AiResult"):
        parse_speech_translation_result(
            {"State": "Finished", "JobResult": {"AiResult": "not-json"}},
            ["en"],
        )


@pytest.mark.asyncio
async def test_wait_for_speech_translation_returns_parsed_finished_result() -> None:
    client = IMSClient(client_settings(), rate_limiter=NoopLimiter())
    responses = [
        {"State": "Executing"},
        {
            "State": "Finished",
            "JobResult": {
                "AiResult": json.dumps(
                    {"MediaURL": "https://oss/en.mp4", "MediaId": "en-media"}
                )
            },
        },
    ]

    async def get_job(_job_id):
        return responses.pop(0)

    client.get_smart_handle_job = get_job

    result = await client.wait_for_speech_translation(
        "job-1",
        target_languages=["en"],
        poll_interval_seconds=0,
        timeout_seconds=60,
    )

    assert result.translations["en"].media_url == "https://oss/en.mp4"
