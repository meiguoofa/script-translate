from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from alibabacloud_ice20201109 import models as ice_models
from alibabacloud_ice20201109.client import Client as ICEClient
from alibabacloud_tea_openapi.models import Config as OpenApiConfig
from alibabacloud_tea_util.models import RuntimeOptions

from app.config import Settings
from app.services.rate_limiter import RateLimiter

logger = logging.getLogger("ims_client")


@dataclass
class IProductionSubmitResult:
    job_id: str


@dataclass
class IProductionFinalResult:
    status: str
    output_urls: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class VideoTranslationSubmitResult:
    job_id: str


@dataclass
class VideoTranslationFinalResult:
    state: str
    output_url: str | None
    raw: dict = field(default_factory=dict)


@dataclass
class SpeechTranslationLanguageResult:
    media_url: str | None = None
    media_id: str | None = None
    translated_audio_url: str | None = None
    translated_audio_media_id: str | None = None
    subtitle_url: str | None = None
    subtitle_signed_url: str | None = None
    fix_subtitle_url: str | None = None
    fix_subtitle_media_id: str | None = None
    bilingual_subtitle_url: str | None = None
    bilingual_subtitle_media_id: str | None = None
    speech_translation_job_id: str | None = None


@dataclass
class SpeechTranslationFinalResult:
    state: str
    detext_video_url: str | None
    detext_video_media_id: str | None
    translations: dict[str, SpeechTranslationLanguageResult]
    missing_languages: list[str]
    raw: dict = field(default_factory=dict)


def parse_speech_translation_result(
    raw: dict,
    target_languages: list[str],
    *,
    output_media_url_template: str | None = None,
) -> SpeechTranslationFinalResult:
    """将 GetSmartHandleJob 的 AiResult 统一成按目标语言索引的结果。"""

    job_result = raw.get("JobResult")
    ai_result_raw = job_result.get("AiResult") if isinstance(job_result, dict) else None
    if not ai_result_raw:
        raise RuntimeError(f"IMS 语音翻译结果缺少 JobResult.AiResult: {raw}")
    try:
        ai_result = (
            json.loads(ai_result_raw)
            if isinstance(ai_result_raw, str)
            else ai_result_raw
        )
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"IMS 语音翻译 AiResult 不是合法 JSON: {ai_result_raw}") from exc
    if not isinstance(ai_result, dict):
        raise RuntimeError(f"IMS 语音翻译 AiResult 不是对象: {ai_result}")

    result_map = ai_result.get("VideoTranslationAiResultMap")
    if not isinstance(result_map, dict):
        if len(target_languages) != 1:
            raise RuntimeError(
                "IMS 多语言语音翻译结果缺少 VideoTranslationAiResultMap"
            )
        result_map = {target_languages[0]: ai_result}

    translations: dict[str, SpeechTranslationLanguageResult] = {}
    missing_languages: list[str] = []
    for language in target_languages:
        value = result_map.get(language)
        if not isinstance(value, dict):
            value = {}
        media_url = value.get("MediaURL")
        if not media_url and value.get("MediaId") and output_media_url_template:
            media_url = output_media_url_template.replace("{language_id}", language)
        translations[language] = SpeechTranslationLanguageResult(
            media_url=media_url,
            media_id=value.get("MediaId"),
            translated_audio_url=value.get("TranslatedAudioMediaURL"),
            translated_audio_media_id=value.get("TranslatedAudioMediaId"),
            subtitle_url=value.get("SpeechTranslatedSubtitleURL"),
            subtitle_signed_url=value.get("SpeechTranslatedSubtitleURLSigned"),
            fix_subtitle_url=value.get("SpeechTranslatedSubtitleURLForFix"),
            fix_subtitle_media_id=value.get("SpeechTranslatedSubtitleMediaIdForFix"),
            bilingual_subtitle_url=value.get("SpeechBilingualSubtitleURL"),
            bilingual_subtitle_media_id=value.get("SpeechBilingualSubtitleMediaId"),
            speech_translation_job_id=value.get("SpeechTranslationJobId"),
        )
        if not media_url:
            missing_languages.append(language)

    return SpeechTranslationFinalResult(
        state=str(raw.get("State") or ""),
        detext_video_url=ai_result.get("DetextVideoURL"),
        detext_video_media_id=ai_result.get("DetextVideoMediaId"),
        translations=translations,
        missing_languages=missing_languages,
        raw=raw,
    )


class IMSClient:
    """阿里云智能媒体服务（IMS / ICE）客户端。

    封装四个接口：
      - SubmitIProductionJob(FunctionName=CaptionExtraction)  字幕提取
      - SubmitIProductionJob(FunctionName=VideoDetext)        字幕擦除（基础/高级 ModelId=algo-video-detext-new）
      - QueryIProductionJob                                    查询上面两类任务
      - SubmitVideoTranslationJob                             字幕级翻译 + 烧录
      - GetSmartHandleJob                                      查询翻译任务

    所有 Aliyun API 调用都过 RateLimiter，避免触发 throttling。
    """

    def __init__(
        self,
        settings: Settings,
        rate_limiter: RateLimiter | None = None,
        global_rate_limiter: RateLimiter | None = None,
    ):
        if not settings.aliyun_access_key_id or not settings.aliyun_access_key_secret:
            raise RuntimeError("ALIBABA_CLOUD_ACCESS_KEY_ID / SECRET 未配置")
        self._settings = settings
        config = OpenApiConfig(
            access_key_id=settings.aliyun_access_key_id,
            access_key_secret=settings.aliyun_access_key_secret,
        )
        # 区域从 endpoint 抽取：ice.cn-shanghai.aliyuncs.com → cn-shanghai
        endpoint = settings.aliyun_ice_endpoint
        config.endpoint = endpoint
        if "cn-" in endpoint or "ap-" in endpoint:
            # ice.cn-shanghai.aliyuncs.com → cn-shanghai
            parts = endpoint.split(".")
            if len(parts) >= 2:
                config.region_id = parts[1]
        self._client = ICEClient(config)
        self._rate_limiter = rate_limiter or RateLimiter(settings.ims_default_qps)
        self._global_rate_limiter = global_rate_limiter

    async def _acquire(self) -> None:
        if (
            self._global_rate_limiter is not None
            and self._global_rate_limiter is not self._rate_limiter
        ):
            await self._global_rate_limiter.acquire()
        await self._rate_limiter.acquire()

    def _oss_uri_to_https(self, oss_uri: str) -> str:
        """`oss://bucket/key1/key2` → `https://bucket.{endpoint}/key1/key2`。

        IMS SubmitVideoTranslationJob 要求 MediaURL 用 HTTPS 格式（不是 oss://）。
        """

        if not oss_uri.startswith("oss://"):
            return oss_uri
        rest = oss_uri[len("oss://"):]
        parts = rest.split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""
        endpoint = self._settings.aliyun_oss_endpoint
        return f"https://{bucket}.{endpoint}/{key}"

    # ===== 字幕提取：CaptionExtraction =====

    async def submit_caption_extraction(
        self,
        *,
        input_oss_uri: str,
        output_srt_oss_uri: str,
        name: str,
        fps: int = 5,
        lang: str = "ch_ml",
        track: str = "main",
        roi: list[list[float]] | None = None,
        sep: bool = False,
    ) -> IProductionSubmitResult:
        params: dict[str, Any] = {
            "fps": fps,
            "lang": lang,
            "track": track,
            "sep": sep,
        }
        if roi is not None:
            params["roi"] = roi
        job_params = json.dumps(params, ensure_ascii=False)
        return await self._submit_iproduction(
            function_name="CaptionExtraction",
            name=name,
            input_oss=input_oss_uri,
            output_oss=output_srt_oss_uri,
            job_params=job_params,
        )

    # ===== 字幕擦除：VideoDetext =====

    async def submit_video_detext(
        self,
        *,
        input_oss_uri: str,
        output_mp4_oss_uri: str,
        name: str,
        model_id: str | None = None,
        limit_region: list[list[float]] | None = None,
    ) -> IProductionSubmitResult:
        params: dict[str, Any] = {}
        if limit_region is not None:
            params["LimitRegion"] = limit_region
        job_params = json.dumps(params, ensure_ascii=False) if params else "{}"
        return await self._submit_iproduction(
            function_name="VideoDetext",
            name=name,
            input_oss=input_oss_uri,
            output_oss=output_mp4_oss_uri,
            job_params=job_params,
            model_id=model_id,
        )

    async def _submit_iproduction(
        self,
        *,
        function_name: str,
        name: str,
        input_oss: str,
        output_oss: str,
        job_params: str,
        model_id: str | None = None,
    ) -> IProductionSubmitResult:
        await self._acquire()

        request = ice_models.SubmitIProductionJobRequest(
            function_name=function_name,
            name=name,
            job_params=job_params,
            model_id=model_id,
            input=ice_models.SubmitIProductionJobRequestInput(
                type="OSS",
                media=input_oss,
            ),
            output=ice_models.SubmitIProductionJobRequestOutput(
                type="OSS",
                media=output_oss,
            ),
        )
        runtime = RuntimeOptions()
        runtime.connect_timeout = 60_000
        runtime.read_timeout = 120_000

        response = await asyncio.to_thread(
            self._client.submit_iproduction_job_with_options, request, runtime
        )
        body = response.body
        job_id = body.job_id if body else None
        if not job_id:
            raw = body.to_map() if body else {}
            raise RuntimeError(f"IMS SubmitIProductionJob({function_name}) 未返回 JobId: {raw}")
        logger.info("IMS submit %s job_id=%s", function_name, job_id)
        return IProductionSubmitResult(job_id=job_id)

    # ===== 查询 IProduction 任务 =====

    async def query_iproduction_job(self, job_id: str) -> dict:
        await self._acquire()
        request = ice_models.QueryIProductionJobRequest(job_id=job_id)
        runtime = RuntimeOptions()
        runtime.connect_timeout = 10_000
        runtime.read_timeout = 15_000
        response = await asyncio.to_thread(
            self._client.query_iproduction_job_with_options, request, runtime
        )
        return response.body.to_map() if response.body else {}

    async def wait_for_iproduction_job(
        self,
        job_id: str,
        *,
        poll_interval_seconds: int,
        timeout_seconds: int,
    ) -> IProductionFinalResult:
        """轮询到任务终态（Success / Failed）。"""

        deadline = time.monotonic() + max(60, timeout_seconds)
        last_raw: dict = {}
        last_status: str | None = None
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"IMS IProduction 任务 {job_id} 等待超时（>{timeout_seconds}s），last={last_raw}"
                )
            try:
                raw = await self.query_iproduction_job(job_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("query_iproduction_job %s 出错: %s, retrying", job_id, exc)
                await asyncio.sleep(max(1, poll_interval_seconds))
                continue
            last_raw = raw
            status = raw.get("Status")
            if status != last_status:
                logger.info("IMS IProduction job %s status=%s", job_id, status)
                last_status = status
            if status == "Success":
                output_urls = raw.get("OutputUrls") or []
                if not output_urls:
                    out = raw.get("Output") or {}
                    output_urls = out.get("OutputFiles") or []
                return IProductionFinalResult(
                    status=status, output_urls=output_urls, raw=raw
                )
            if status in ("Failed", "Cancelled"):
                err = raw.get("Result") or raw.get("ErrorMessage") or str(raw)
                raise RuntimeError(f"IMS IProduction 任务 {job_id} {status}: {err}")
            await asyncio.sleep(max(1, poll_interval_seconds))

    # ===== 视频翻译：SubmitVideoTranslationJob + GetSmartHandleJob =====

    async def register_media(
        self,
        *,
        input_url: str,
        media_type: str = "video",
        title: str,
        business_type: str = "subtitles",
    ) -> str:
        """注册媒体文件，返回 mediaId。SubmitVideoTranslationJob 需要 mediaId 而非 OSS URI。"""

        await self._acquire()
        request = ice_models.RegisterMediaInfoRequest(
            input_url=input_url,
            media_type=media_type,
            title=title,
            business_type=business_type,
            overwrite=True,
        )
        runtime = RuntimeOptions()
        runtime.connect_timeout = 30_000
        runtime.read_timeout = 60_000

        response = await asyncio.to_thread(
            self._client.register_media_info_with_options, request, runtime
        )
        body = response.body
        media_id = body.media_id if body else None
        if not media_id:
            raw = body.to_map() if body else {}
            raise RuntimeError(f"IMS RegisterMediaInfo({input_url}) 未返回 MediaId: {raw}")
        logger.info("IMS register_media input=%s → mediaId=%s", input_url[:80], media_id)
        return media_id

    async def submit_video_translation(
        self,
        *,
        title: str,
        video_media_id: str,
        subtitle_media_id: str | None = None,
        subtitle_oss_url: str | None = None,
        output_mp4_oss: str,
        source_lang: str,
        target_lang: str,
        burn_font_size: int = 72,
        burn_font_color: str = "#FFFFFF",
        burn_font_color_opacity: float = 1.0,
        burn_x: float = 0.5,
        burn_y: float = 0.82,
        burn_text_width: float = 0.9,
    ) -> VideoTranslationSubmitResult:
        await self._acquire()

        input_config: dict[str, Any] = {
            "Type": "Video",
            "Video": video_media_id,
        }
        if subtitle_media_id:
            input_config["Subtitle"] = subtitle_media_id
        elif subtitle_oss_url:
            # IMS SubmitVideoTranslationJob 要求 OSS URL 用 HTTPS 格式（不是 oss://）
            input_config["Subtitle"] = self._oss_uri_to_https(subtitle_oss_url)

        # OutputConfig.MediaURL 也必须是 HTTPS 格式
        output_https = self._oss_uri_to_https(output_mp4_oss)

        editing_config: dict[str, Any] = {
            "SourceLanguage": source_lang,
            "TargetLanguage": target_lang,
            "TextSource": "SubtitleFile" if (subtitle_media_id or subtitle_oss_url) else "ASR",
            "BilingualSubtitle": False,
            "NeedSpeechTranslate": False,
            "NeedFaceTranslate": False,
            "SubtitleTranslate": {
                "SubtitleConfig": {
                    "Type": "Text",
                    "FontSize": burn_font_size,
                    "FontColor": burn_font_color,
                    "FontColorOpacity": burn_font_color_opacity,
                    "X": burn_x,
                    "Y": burn_y,
                    "TextWidth": burn_text_width,
                    "Alignment": "Center",
                    "BorderStyle": 1,
                    "Outline": 2,
                }
            },
            "SupportEditing": True,
        }

        output_config: dict[str, Any] = {
            "OutputTarget": "OSS",
            "MediaURL": output_https,
        }

        request = ice_models.SubmitVideoTranslationJobRequest(
            title=title,
            input_config=json.dumps(input_config, ensure_ascii=False),
            editing_config=json.dumps(editing_config, ensure_ascii=False),
            output_config=json.dumps(output_config, ensure_ascii=False),
        )
        runtime = RuntimeOptions()
        runtime.connect_timeout = 60_000
        runtime.read_timeout = 120_000

        response = await asyncio.to_thread(
            self._client.submit_video_translation_job_with_options, request, runtime
        )
        body = response.body
        if not body or not body.success:
            raw = body.to_map() if body else {}
            raise RuntimeError(f"IMS SubmitVideoTranslationJob 失败: {raw}")
        data = body.data
        job_id = getattr(data, "job_id", None) if data else None
        if not job_id:
            raw = body.to_map() if body else {}
            raise RuntimeError(f"IMS SubmitVideoTranslationJob 未返回 JobId: {raw}")
        logger.info("IMS submit_video_translation job_id=%s", job_id)
        return VideoTranslationSubmitResult(job_id=job_id)

    async def submit_speech_translation(
        self,
        *,
        title: str,
        input_video_oss_uri: str,
        output_video_oss_uri: str,
        source_language: str,
        target_languages: list[str],
        text_source: str,
        detext_mode: str,
        detext_areas: list[list[float]] | None = None,
        ocr_area: list[float] | None = None,
        bilingual_subtitle: bool = False,
        subtitle_enabled: bool = True,
        fe_canvas: dict[str, int] | None = None,
        subtitle_config: dict[str, Any] | None = None,
        skip_song: bool = False,
    ) -> VideoTranslationSubmitResult:
        """提交 IMS 语音级视频翻译任务。一个任务可包含多个目标语言。"""

        if (
            len(target_languages) > 1
            and "{language_id}" not in output_video_oss_uri
        ):
            raise ValueError(
                "多目标语言 IMS 任务的输出地址必须包含 {language_id}"
            )
        await self._acquire()
        input_config = {
            "Type": "Video",
            "Video": self._oss_uri_to_https(input_video_oss_uri),
        }
        speech_config: dict[str, Any] = {
            "SubtitleTimeForce": False,
            "SkipSong": 1 if skip_song else 0,
        }
        rendered_subtitle_config = {
            "Type": "Text",
            **(subtitle_config or {}),
        }
        if not subtitle_enabled:
            rendered_subtitle_config["FontSize"] = 0
        speech_config["SubtitleConfig"] = rendered_subtitle_config
        if text_source in ("OCR", "OCR_ASR"):
            speech_config["OcrArea"] = ocr_area if ocr_area is not None else "Auto"

        editing_config: dict[str, Any] = {
            "SourceLanguage": source_language,
            "TargetLanguage": ",".join(target_languages),
            "TextSource": text_source,
            "SupportEditing": True,
            "BilingualSubtitle": bilingual_subtitle,
            "NeedSpeechTranslate": True,
            "NeedFaceTranslate": False,
            "SpeechTranslate": speech_config,
        }
        if fe_canvas is not None:
            editing_config["FECanvas"] = fe_canvas
        if detext_mode == "auto":
            editing_config["DetextArea"] = "Auto"
        elif detext_mode == "custom":
            if not detext_areas:
                raise ValueError("detext_mode=custom 时必须提供 detext_areas")
            editing_config["DetextArea"] = detext_areas
        elif detext_mode != "none":
            raise ValueError(f"不支持的 detext_mode: {detext_mode}")

        request = ice_models.SubmitVideoTranslationJobRequest(
            title=title,
            input_config=json.dumps(input_config, ensure_ascii=False),
            editing_config=json.dumps(editing_config, ensure_ascii=False),
            output_config=json.dumps(
                {
                    "OutputTarget": "OSS",
                    "MediaURL": self._oss_uri_to_https(output_video_oss_uri),
                },
                ensure_ascii=False,
            ),
        )
        runtime = RuntimeOptions()
        runtime.connect_timeout = 60_000
        runtime.read_timeout = 120_000
        response = await asyncio.to_thread(
            self._client.submit_video_translation_job_with_options,
            request,
            runtime,
        )
        body = response.body
        if not body or not body.success:
            raw = body.to_map() if body else {}
            raise RuntimeError(f"IMS SubmitVideoTranslationJob 语音翻译失败: {raw}")
        data = body.data
        job_id = getattr(data, "job_id", None) if data else None
        if not job_id:
            raw = body.to_map() if body else {}
            raise RuntimeError(f"IMS 语音翻译未返回 JobId: {raw}")
        logger.info(
            "IMS submit_speech_translation job_id=%s targets=%s",
            job_id,
            target_languages,
        )
        return VideoTranslationSubmitResult(job_id=job_id)

    async def get_smart_handle_job(self, job_id: str) -> dict:
        await self._acquire()
        request = ice_models.GetSmartHandleJobRequest(job_id=job_id)
        runtime = RuntimeOptions()
        runtime.connect_timeout = 10_000
        runtime.read_timeout = 15_000
        response = await asyncio.to_thread(
            self._client.get_smart_handle_job_with_options, request, runtime
        )
        return response.body.to_map() if response.body else {}

    async def wait_for_smart_handle_job(
        self,
        job_id: str,
        *,
        poll_interval_seconds: int,
        timeout_seconds: int,
    ) -> VideoTranslationFinalResult:
        """轮询到翻译任务终态。"""

        deadline = time.monotonic() + max(60, timeout_seconds)
        last_raw: dict = {}
        last_state: str | None = None
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"IMS SmartHandle 任务 {job_id} 等待超时（>{timeout_seconds}s），last={last_raw}"
                )
            try:
                raw = await self.get_smart_handle_job(job_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("get_smart_handle_job %s 出错: %s, retrying", job_id, exc)
                await asyncio.sleep(max(1, poll_interval_seconds))
                continue
            last_raw = raw
            state = raw.get("State")
            if state != last_state:
                logger.info("IMS SmartHandle job %s state=%s", job_id, state)
                last_state = state
            if state == "Finished":
                output_url = raw.get("Output") or None
                return VideoTranslationFinalResult(
                    state=state, output_url=output_url, raw=raw
                )
            if state in ("Failed", "Cancelled"):
                err = raw.get("ErrorMessage") or raw.get("ErrorCode") or str(raw)
                raise RuntimeError(f"IMS SmartHandle 任务 {job_id} {state}: {err}")
            await asyncio.sleep(max(1, poll_interval_seconds))

    async def wait_for_speech_translation(
        self,
        job_id: str,
        *,
        target_languages: list[str],
        output_video_oss_uri: str | None = None,
        poll_interval_seconds: int,
        timeout_seconds: int,
    ) -> SpeechTranslationFinalResult:
        deadline = time.monotonic() + max(60, timeout_seconds)
        last_raw: dict = {}
        last_state: str | None = None
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"IMS 语音翻译任务 {job_id} 等待超时"
                    f"（>{timeout_seconds}s），last={last_raw}"
                )
            try:
                raw = await self.get_smart_handle_job(job_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "get speech translation job %s 出错: %s, retrying",
                    job_id,
                    exc,
                )
                await asyncio.sleep(max(0, poll_interval_seconds))
                continue
            last_raw = raw
            state = raw.get("State")
            if state != last_state:
                logger.info("IMS speech translation job %s state=%s", job_id, state)
                last_state = state
            if state == "Finished":
                output_media_url_template = (
                    self._oss_uri_to_https(output_video_oss_uri)
                    if output_video_oss_uri
                    else None
                )
                return parse_speech_translation_result(
                    raw,
                    target_languages,
                    output_media_url_template=output_media_url_template,
                )
            if state in ("Failed", "Cancelled"):
                err = raw.get("ErrorMessage") or raw.get("ErrorCode") or str(raw)
                raise RuntimeError(f"IMS 语音翻译任务 {job_id} {state}: {err}")
            await asyncio.sleep(max(0, poll_interval_seconds))
