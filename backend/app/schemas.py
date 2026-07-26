from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import BaseModel, Field, PlainSerializer, field_validator, model_validator


def _to_utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UTCDatetime = Annotated[datetime, PlainSerializer(_to_utc_iso, return_type=str | None)]


class ModelOption(BaseModel):
    provider: str
    name: str
    label: str
    target_langs: list[str]
    default: bool = False


class ScriptLineOut(BaseModel):
    id: str
    line_no: int
    raw_line: str
    speaker: str | None
    parenthetical: str | None
    dialogue: str | None
    is_dialogue: bool


class ScriptCreateResponse(BaseModel):
    script_id: str
    title: str
    line_count: int
    source_lang: str | None


class ScriptSummary(BaseModel):
    id: str
    title: str
    source_lang: str | None
    source_type: str
    created_at: UTCDatetime
    version_count: int


class ScriptDetail(BaseModel):
    id: str
    title: str
    source_lang: str | None
    source_type: str
    created_at: UTCDatetime
    lines: list[ScriptLineOut]


class TranslateRequest(BaseModel):
    target_lang: str
    provider: str
    model: str


class TranslationVersionResponse(BaseModel):
    version_id: str
    status: str


class TranslationVersionSummary(BaseModel):
    id: str
    target_lang: str
    model_provider: str
    model_name: str
    status: str
    created_at: UTCDatetime
    error_message: str | None


class TranslationDetail(BaseModel):
    id: str
    script_id: str
    target_lang: str
    model_provider: str
    model_name: str
    status: str
    prompt_version: str
    total_tokens: int | None
    cost: float | None
    duration_ms: int | None
    error_message: str | None
    created_at: UTCDatetime
    rendered_lines: list[str]


class CleanedScriptCreateResponse(BaseModel):
    id: str
    title: str
    source_filename: str | None
    output_filename: str
    line_count: int
    stripped_count: int
    created_at: UTCDatetime


class CleanedScriptSummary(BaseModel):
    id: str
    title: str
    source_filename: str | None
    output_filename: str
    line_count: int
    stripped_count: int
    created_at: UTCDatetime


class CleanedScriptDetail(CleanedScriptSummary):
    cleaned_preview: list[str]


class PromptTemplateOut(BaseModel):
    id: str
    name: str
    content: str
    is_default: bool
    created_at: UTCDatetime
    updated_at: UTCDatetime


class PromptTemplateCreateRequest(BaseModel):
    name: str
    content: str


class PromptTemplateUpdateRequest(BaseModel):
    name: str | None = None
    content: str | None = None


class VideoUploadFileSpec(BaseModel):
    filename: str
    content_type: str | None = None


class VideoUploadUrlRequest(BaseModel):
    files: list[VideoUploadFileSpec]


class VideoUploadEntry(BaseModel):
    filename: str
    presigned_url: str
    public_url: str
    tos_uri: str
    key: str


class VideoUploadUrlResponse(BaseModel):
    job_id: str
    expires_in: int
    entries: list[VideoUploadEntry]


class VideoJobCreateRequest(BaseModel):
    job_id: str
    title: str
    video_urls: list[str]
    original_filenames: list[str] | None = None
    prompt_template_id: str


class VideoJobOut(BaseModel):
    id: str
    title: str
    video_count: int
    video_urls: list[str]
    original_filenames: list[str] | None
    prompt_template_id: str | None
    prompt_template_name: str | None
    output_tos_path: str
    las_task_id: str | None
    status: str
    progress_message: str | None
    error_message: str | None
    generated_script_id: str | None
    generated_script_preview: list[str] | None = None
    submitted_at: UTCDatetime | None
    completed_at: UTCDatetime | None
    created_at: UTCDatetime
    updated_at: UTCDatetime


class VideoJobSummary(BaseModel):
    id: str
    title: str
    video_count: int
    prompt_template_name: str | None
    status: str
    generated_script_id: str | None
    error_message: str | None
    created_at: UTCDatetime
    updated_at: UTCDatetime


class AccessVerifyRequest(BaseModel):
    passphrase: str


class AccessVerifyResponse(BaseModel):
    ok: bool


# ===== 视频超分辨 =====


class SuperResUploadFileSpec(BaseModel):
    filename: str
    content_type: str | None = None


class SuperResUploadUrlRequest(BaseModel):
    files: list[SuperResUploadFileSpec]


class SuperResUploadEntry(BaseModel):
    filename: str
    presigned_url: str
    public_url: str
    oss_uri: str
    key: str


class SuperResUploadUrlResponse(BaseModel):
    job_id: str
    expires_in: int
    entries: list[SuperResUploadEntry]


class SuperResJobItemSpec(BaseModel):
    filename: str
    oss_uri: str
    public_url: str
    key: str


class SuperResJobCreateRequest(BaseModel):
    job_id: str
    title: str
    bit_rate: int = Field(default=10, ge=1, le=20)
    items: list[SuperResJobItemSpec]
    original_filenames: list[str] | None = None


class SuperResJobItemOut(BaseModel):
    index: int
    filename: str
    input_oss_uri: str
    input_public_url: str
    viapi_job_id: str | None
    viapi_status: str | None
    raw_output_url: str | None
    output_oss_uri: str | None
    output_public_url: str | None
    status: str
    error: str | None


class SuperResJobOut(BaseModel):
    id: str
    title: str
    video_count: int
    bit_rate: int
    items: list[SuperResJobItemOut]
    original_filenames: list[str] | None
    output_oss_prefix: str
    status: str
    progress_message: str | None
    error_message: str | None
    succeeded_count: int
    failed_count: int
    submitted_at: UTCDatetime | None
    completed_at: UTCDatetime | None
    created_at: UTCDatetime
    updated_at: UTCDatetime


class SuperResJobSummary(BaseModel):
    id: str
    title: str
    video_count: int
    bit_rate: int
    status: str
    succeeded_count: int
    failed_count: int
    error_message: str | None
    created_at: UTCDatetime
    updated_at: UTCDatetime


# ===== 视频字幕提取-翻译-合并 =====


class SubtitleUploadFileSpec(BaseModel):
    filename: str
    content_type: str | None = None


class SubtitleUploadUrlRequest(BaseModel):
    files: list[SubtitleUploadFileSpec]


class SubtitleUploadEntry(BaseModel):
    filename: str
    # 阿里云上海 OSS（VIAPI 字幕 OCR 用）
    oss_presigned_url: str
    oss_public_url: str
    oss_uri: str
    oss_key: str
    # 新加坡 TOS（烧录视频源 + 产物存储）
    tos_presigned_url: str
    tos_public_url: str
    tos_uri: str
    tos_key: str


class SubtitleUploadUrlResponse(BaseModel):
    job_id: str
    expires_in: int
    entries: list[SubtitleUploadEntry]


class SubtitleJobItemSpec(BaseModel):
    filename: str
    # OSS
    oss_uri: str
    oss_public_url: str
    oss_key: str
    # 新加坡 TOS
    tos_uri: str
    tos_public_url: str
    tos_key: str


class SubtitleJobCreateRequest(BaseModel):
    job_id: str
    title: str
    subtitle_source: str = Field(default="chinese", pattern="^(chinese|all)$")
    enable_translate: bool = False
    enable_burn: bool = False
    placement_mode: str = Field(default="safe_bottom", pattern="^(safe_bottom|simple_bottom)$")
    target_lang: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    items: list[SubtitleJobItemSpec]
    original_filenames: list[str] | None = None


class SubtitleJobItemOut(BaseModel):
    index: int
    filename: str
    # 输入：OSS（VIAPI 用）+ 新加坡 TOS（烧录源）
    input_oss_uri: str
    input_oss_public_url: str
    input_tos_uri: str
    input_tos_public_url: str
    # VIAPI
    viapi_job_id: str | None
    viapi_status: str | None
    # SRT 产物（新加坡 TOS）
    srt_tos_uri: str | None
    srt_tos_public_url: str | None
    # 译文 SRT（新加坡 TOS）
    translated_srt_tos_uri: str | None
    translated_srt_tos_public_url: str | None
    # 输出视频（新加坡 TOS）
    output_video_tos_uri: str | None
    output_video_tos_public_url: str | None
    status: str
    error: str | None


class SubtitleJobOut(BaseModel):
    id: str
    title: str
    video_count: int
    subtitle_source: str
    enable_translate: bool
    enable_burn: bool
    placement_mode: str
    target_lang: str | None
    model_provider: str | None
    model_name: str | None
    items: list[SubtitleJobItemOut]
    original_filenames: list[str] | None
    output_tos_prefix: str
    status: str
    progress_message: str | None
    error_message: str | None
    succeeded_count: int
    failed_count: int
    submitted_at: UTCDatetime | None
    completed_at: UTCDatetime | None
    created_at: UTCDatetime
    updated_at: UTCDatetime


class SubtitleJobSummary(BaseModel):
    id: str
    title: str
    video_count: int
    subtitle_source: str
    enable_translate: bool
    enable_burn: bool
    status: str
    succeeded_count: int
    failed_count: int
    error_message: str | None
    created_at: UTCDatetime
    updated_at: UTCDatetime


# ===== 视频字幕擦除 + 翻译（IMS/ICE） =====


class SubtitleEraseUploadFileSpec(BaseModel):
    filename: str
    content_type: str = "video/mp4"


class SubtitleEraseUploadUrlRequest(BaseModel):
    files: list[SubtitleEraseUploadFileSpec]
    job_id: str | None = None


class SubtitleEraseUploadEntry(BaseModel):
    filename: str
    presigned_url: str
    public_url: str
    oss_uri: str
    key: str


class SubtitleEraseUploadUrlResponse(BaseModel):
    job_id: str
    expires_in: int
    entries: list[SubtitleEraseUploadEntry]


class SubtitleEraseMultipartPartInfo(BaseModel):
    part_number: int
    offset: int
    size: int
    presigned_url: str


class SubtitleEraseMultipartUploadUrlRequest(BaseModel):
    filename: str
    content_type: str = "video/mp4"
    file_size: int = Field(ge=1)
    job_id: str | None = None
    index: int = Field(default=0, ge=0)


class SubtitleEraseMultipartUploadUrlResponse(BaseModel):
    job_id: str
    upload_id: str
    key: str
    oss_uri: str
    public_url: str
    part_size: int
    parts: list[SubtitleEraseMultipartPartInfo]
    expires_in: int


class SubtitleEraseCompletePart(BaseModel):
    part_number: int
    etag: str


class SubtitleEraseCompleteMultipartRequest(BaseModel):
    job_id: str
    key: str
    upload_id: str
    parts: list[SubtitleEraseCompletePart]


class SubtitleEraseCompleteMultipartResponse(BaseModel):
    public_url: str
    oss_uri: str


class SubtitleEraseAbortMultipartRequest(BaseModel):
    key: str
    upload_id: str


class SubtitleEraseAbortMultipartResponse(BaseModel):
    ok: bool = True


class SubtitleEraseJobItemSpec(BaseModel):
    filename: str
    oss_uri: str
    public_url: str
    key: str | None = None
    drama_index: int = 0
    episode_index: int = 0


class SubtitleEraseJobCreateRequest(BaseModel):
    job_id: str
    title: str
    detext_mode: str = Field(default="advanced", pattern="^(basic|advanced)$")
    translate_mode: str = Field(default="llm", pattern="^(aliyun|llm)$")
    burn_mode: str = Field(default="mps", pattern="^(local|aliyun|mps)$")
    placement_mode: str = Field(default="safe_bottom", pattern="^(safe_bottom|simple_bottom)$")
    source_lang: str | None = None
    target_langs: list[str]
    model_provider: str | None = None
    model_name: str | None = None
    qps: int = Field(default=30, ge=1, le=100)

    caption_fps: int = Field(default=5, ge=2, le=10)
    caption_lang: str = "ch_ml"
    caption_track: str = "main"
    caption_roi: str | None = None
    caption_sep: bool = False

    detext_limit_region: str | None = None

    burn_font_size: int = Field(default=5, ge=1, le=30)  # 占视频高度百分比
    burn_font_color: str = "#FFFFFF"
    burn_font_color_opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    burn_x: float = Field(default=0.5, ge=0.0, le=1.0)
    burn_y: float = Field(default=0.82, ge=0.0, le=1.0)
    burn_text_width: float = Field(default=0.9, ge=0.1, le=1.0)

    items: list[SubtitleEraseJobItemSpec]
    original_filenames: list[str] | None = None

    @field_validator("target_langs")
    @classmethod
    def at_least_one_lang(cls, v: list[str]) -> list[str]:
        if not v or not all(isinstance(x, str) and x.strip() for x in v):
            raise ValueError("target_langs 必须至少包含一个非空语言代码")
        return v


class SubtitleEraseRerunRequest(BaseModel):
    """重新运行已有任务时可修改的参数（不含视频文件列表）。"""

    detext_mode: str = Field(pattern="^(basic|advanced)$")
    translate_mode: str = Field(pattern="^(aliyun|llm)$")
    burn_mode: str = Field(pattern="^(local|aliyun|mps)$")
    placement_mode: str = Field(pattern="^(safe_bottom|simple_bottom)$")
    source_lang: str | None = None
    target_langs: list[str]
    model_provider: str | None = None
    model_name: str | None = None
    qps: int = Field(ge=1, le=100)
    caption_fps: int = Field(ge=2, le=10)
    caption_lang: str
    caption_track: str
    caption_roi: str | None = None
    caption_sep: bool
    detext_limit_region: str | None = None
    burn_font_size: int = Field(ge=1, le=30)  # 占视频高度百分比
    burn_font_color: str
    burn_font_color_opacity: float = Field(ge=0.0, le=1.0)
    burn_x: float = Field(ge=0.0, le=1.0)
    burn_y: float = Field(ge=0.0, le=1.0)
    burn_text_width: float = Field(ge=0.1, le=1.0)

    # 强制重做共享阶段(默认 False,自动复用已成功产物)
    force_redetext: bool = False
    force_recaption: bool = False

    @field_validator("target_langs")
    @classmethod
    def at_least_one_lang(cls, v: list[str]) -> list[str]:
        if not v or not all(isinstance(x, str) and x.strip() for x in v):
            raise ValueError("target_langs 必须至少包含一个非空语言代码")
        return v


class SubtitleEraseTranslationItemOut(BaseModel):
    """单语言的翻译+烧录产物。"""

    translated_srt_oss_uri: str | None = None
    translated_srt_public_url: str | None = None
    output_video_oss_uri: str | None = None
    output_public_url: str | None = None
    translation_job_id: str | None = None
    translation_status: str | None = None
    mps_job_id: str | None = None
    burn_ass_oss_uri: str | None = None
    output_video_tos_uri: str | None = None
    output_video_tos_public_url: str | None = None
    output_video_bj_tos_uri: str | None = None
    output_video_bj_tos_public_url: str | None = None
    bj_fetch_error: str | None = None
    stage: str = "pending"
    status: str = "pending"
    error: str | None = None


class SubtitleEraseJobItemOut(BaseModel):
    index: int
    drama_index: int
    episode_index: int
    filename: str
    input_oss_uri: str
    input_public_url: str

    # 跨语言共享产物(擦除 + 字幕提取,只做一次)
    caption_job_id: str | None
    caption_status: str | None
    source_srt_oss_uri: str | None
    source_srt_public_url: str | None = None
    cleaned_srt_oss_uri: str | None
    cleaned_srt_public_url: str | None = None

    detext_job_id: str | None
    detext_status: str | None
    clean_video_oss_uri: str | None
    clean_video_public_url: str | None = None

    warning: str | None = None

    # 每语言独立的翻译+烧录产物
    translations: dict[str, SubtitleEraseTranslationItemOut]

    # 视频时长(秒),阶段 0 用 ffprobe 探测后填充
    duration_seconds: float | None = None

    # item 级汇总状态
    stage: str
    status: str
    error: str | None


class SubtitleEraseJobOut(BaseModel):
    id: str
    title: str
    drama_count: int
    video_count: int

    detext_mode: str
    translate_mode: str
    burn_mode: str
    placement_mode: str
    source_lang: str | None
    target_langs: list[str]
    model_provider: str | None
    model_name: str | None
    qps: int

    caption_fps: int
    caption_lang: str
    caption_track: str
    caption_roi: str | None
    caption_sep: bool

    detext_limit_region: str | None

    burn_font_size: int
    burn_font_color: str
    burn_font_color_opacity: float
    burn_x: float
    burn_y: float
    burn_text_width: float

    items: list[SubtitleEraseJobItemOut]
    original_filenames: list[str] | None
    output_oss_prefix: str
    output_tos_prefix: str | None
    status: str
    progress_message: str | None
    error_message: str | None
    succeeded_count: int
    failed_count: int
    detexted_count: int
    captioned_count: int
    total_duration_seconds: float
    submitted_at: UTCDatetime | None
    completed_at: UTCDatetime | None
    created_at: UTCDatetime
    updated_at: UTCDatetime


class SubtitleEraseJobSummary(BaseModel):
    id: str
    title: str
    drama_count: int
    video_count: int
    detext_mode: str
    translate_mode: str
    burn_mode: str
    target_langs: list[str]
    status: str
    succeeded_count: int
    failed_count: int
    detexted_count: int
    captioned_count: int
    total_duration_seconds: float
    error_message: str | None
    created_at: UTCDatetime
    updated_at: UTCDatetime


# ===== 阿里云 IMS 一站式语音级视频翻译 =====

IMS_SPEECH_TARGET_LANGUAGES = {
    "zh", "zh-tw", "en", "ja", "ko", "yue", "de", "fr", "es", "ar",
    "tr", "ru", "pt", "vi", "ms", "th", "id", "sichuan", "tianjin",
}


class ImsSpeechRect(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def within_canvas(self) -> "ImsSpeechRect":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("区域必须完全位于视频画布内")
        return self

    def as_list(self) -> list[float]:
        return [self.x, self.y, self.width, self.height]


class ImsSpeechJobItemSpec(BaseModel):
    filename: str
    oss_uri: str
    public_url: str
    key: str | None = None
    drama_index: int = Field(default=0, ge=0)
    episode_index: int = Field(default=0, ge=0)


class ImsSpeechJobCreateRequest(BaseModel):
    job_id: str
    title: str
    source_language: str
    target_languages: list[str]
    text_source: str = Field(pattern="^(ASR|OCR|OCR_ASR)$")
    detext_mode: str = Field(default="auto", pattern="^(none|auto|custom)$")
    detext_areas: list[ImsSpeechRect] | None = None
    ocr_area: ImsSpeechRect | None = None
    bilingual_subtitle: bool = False
    subtitle_enabled: bool = True
    skip_song: bool = False
    font_color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    font_color_opacity: float = Field(default=1, ge=0, le=1)
    subtitle_y: float = Field(default=0.76, ge=0, le=1)
    items: list[ImsSpeechJobItemSpec]
    original_filenames: list[str] | None = None

    @field_validator("target_languages")
    @classmethod
    def validate_target_languages(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(v.strip() for v in values if v.strip()))
        if not normalized:
            raise ValueError("target_languages 必须至少包含一个目标语言")
        unsupported = [v for v in normalized if v not in IMS_SPEECH_TARGET_LANGUAGES]
        if unsupported:
            raise ValueError(f"IMS 语音翻译不支持目标语言: {unsupported}")
        return normalized

    @model_validator(mode="after")
    def validate_recognizer_and_regions(self) -> "ImsSpeechJobCreateRequest":
        allowed_sources = (
            {"zh", "en", "fr", "tr"}
            if self.text_source == "ASR"
            else {"zh", "en"}
        )
        if self.source_language not in allowed_sources:
            raise ValueError(
                f"{self.text_source} 不支持源语言 {self.source_language}"
            )
        if self.detext_mode == "custom" and not self.detext_areas:
            raise ValueError("自定义擦除模式必须提供 detext_areas")
        if not self.items:
            raise ValueError("视频列表不能为空")
        return self


class ImsSpeechTranslationItemOut(BaseModel):
    status: str = "pending"
    error: str | None = None
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


class ImsSpeechJobItemOut(BaseModel):
    index: int
    drama_index: int
    episode_index: int
    filename: str
    input_oss_uri: str
    input_public_url: str
    ims_job_id: str | None = None
    ims_status: str | None = None
    detext_video_url: str | None = None
    detext_video_media_id: str | None = None
    translations: dict[str, ImsSpeechTranslationItemOut]
    stage: str = "pending"
    status: str = "pending"
    error: str | None = None


class ImsSpeechJobOut(BaseModel):
    id: str
    title: str
    drama_count: int
    video_count: int
    source_language: str
    target_languages: list[str]
    text_source: str
    config: dict
    items: list[ImsSpeechJobItemOut]
    original_filenames: list[str] | None
    output_oss_prefix: str
    status: str
    progress_message: str | None
    error_message: str | None
    succeeded_count: int
    partial_failed_count: int
    failed_count: int
    submitted_at: UTCDatetime | None
    completed_at: UTCDatetime | None
    created_at: UTCDatetime
    updated_at: UTCDatetime


class ImsSpeechJobSummary(BaseModel):
    id: str
    title: str
    drama_count: int
    video_count: int
    source_language: str
    target_languages: list[str]
    text_source: str
    status: str
    succeeded_count: int
    partial_failed_count: int
    failed_count: int
    error_message: str | None
    created_at: UTCDatetime


# ===== 百度云 VOD 视频翻译(字幕擦除 + 翻译 + 语音翻译)=====


class BaiduVodUploadFileSpec(BaseModel):
    filename: str
    content_type: str | None = None


class BaiduVodUploadUrlRequest(BaseModel):
    files: list[BaiduVodUploadFileSpec]
    job_id: str | None = None


class BaiduVodUploadEntry(BaseModel):
    filename: str
    presigned_url: str
    public_url: str
    bos_uri: str
    key: str


class BaiduVodUploadUrlResponse(BaseModel):
    job_id: str
    expires_in: int
    entries: list[BaiduVodUploadEntry]


class BaiduVodMultipartPartInfo(BaseModel):
    part_number: int
    offset: int
    size: int
    presigned_url: str


class BaiduVodMultipartUploadUrlRequest(BaseModel):
    filename: str
    content_type: str
    file_size: int
    job_id: str | None = None
    index: int = 0


class BaiduVodMultipartUploadUrlResponse(BaseModel):
    job_id: str
    upload_id: str
    key: str
    bos_uri: str
    public_url: str
    part_size: int
    parts: list[BaiduVodMultipartPartInfo]
    expires_in: int


class BaiduVodCompletePart(BaseModel):
    part_number: int
    etag: str = ""


class BaiduVodCompleteMultipartRequest(BaseModel):
    job_id: str
    key: str
    upload_id: str
    parts: list[BaiduVodCompletePart]


class BaiduVodCompleteMultipartResponse(BaseModel):
    public_url: str
    bos_uri: str


class BaiduVodAbortMultipartRequest(BaseModel):
    key: str
    upload_id: str


class BaiduVodAbortMultipartResponse(BaseModel):
    ok: bool


class BaiduVodJobItemSpec(BaseModel):
    filename: str
    oss_uri: str  # 阿里云 OSS 公网 URL(用于 fetch_media 拉取到百度 VOD)
    public_url: str
    key: str | None = None
    drama_index: int = 0
    episode_index: int = 0


def _validate_voice_mode(obj) -> object:
    """跨字段校验:voice_mode 与 target_langs / voice_list 的组合。

    - VOICE_CLONE: 不做语言白名单校验(百度官方文档仅列部分语言,
      但实际 API 接受更广,如 pt-PT 葡萄牙语能跑通。语言支持由百度决定,
      在 backend 层硬拒绝会阻断原本能工作的组合)
    - AI_DUB: voice_list 必填且只能 1 个音色 ID
    - speech 未选时 voice_mode 应为 None(忽略不报错,防御性清空)
    """
    voice_mode = obj.voice_mode
    has_speech = "speech" in (obj.translation_type_list or [])

    if not has_speech:
        # 字幕翻译不需要 voice_mode,防御性清空避免下游误用
        obj.voice_mode = None
        obj.voice_list = None
        return obj

    if not voice_mode:
        raise ValueError(
            "translation_type_list 含 speech 时必须配置 voice_mode"
            "(VOICE_CLONE 多角色复刻 / AI_DUB 单音色 AI 配音)"
        )

    if voice_mode not in ("VOICE_CLONE", "AI_DUB"):
        raise ValueError(
            f"不支持的 voice_mode: {voice_mode}(允许: VOICE_CLONE / AI_DUB)"
        )

    if voice_mode == "VOICE_CLONE":
        # VOICE_CLONE 不需要 voice_list,清空避免误传
        obj.voice_list = None
    elif voice_mode == "AI_DUB":
        voice_list = obj.voice_list or []
        if not voice_list:
            raise ValueError(
                "AI_DUB 必须提供 voice_list(音色 ID 列表),"
                "音色 ID 需从百度 VOD 控制台音色列表查询,"
                "且 voiceId 必须匹配目标语言。"
            )
        if len(voice_list) > 1:
            raise ValueError(
                f"AI_DUB 当前仅支持 1 个音色,收到 {len(voice_list)} 个"
            )
    return obj


class BaiduVodOcrArea(BaseModel):
    """百度 VOD OCR 区域配置(画面坐标,可选)"""
    x: int
    y: int
    width: int
    height: int
    start: int = 0


class BaiduVodFontConfig(BaseModel):
    """字幕烧录字体配置"""
    family: str = "Hei"  # Hei/Song/Kai/Yuan
    alignment: str = "center"  # center/left/right
    size: int = 48
    bold: bool = False
    color: str = "#FFFFFFFF"
    outline_thickness: int = 2
    outline_color: str = "#000000FF"
    padding: int = 8


class BaiduVodJobCreateRequest(BaseModel):
    job_id: str
    title: str
    project_type: str = Field(default="ShortSeries", pattern="^(ShortSeries|Ecommerce)$")
    source_language: str
    target_langs: list[str]
    # 翻译配置
    translation_type_list: list[str] = Field(default_factory=lambda: ["subtitle"])  # subtitle/speech
    voice_mode: str | None = None  # VOICE_CLONE/AI_DUB,仅含 speech 时必填
    voice_list: list[str] | None = None  # AI_DUB 必填,音色 ID 列表(百度只支持 1 个)
    # 字幕配置
    recognition_type: str = "OCR"  # OCR/ASR
    text_type_list: list[str] = Field(default_factory=lambda: ["dialog"])  # dialog/castName/castDescription/other
    target_subtitle_compose: bool = True  # 烧录译文字幕到视频
    desubtitle_enabled: bool = True  # 擦除原字幕
    desubtitle_model: str = "v4"  # v4/v3
    desubtitle_type: str = "global"  # global 整片字幕区擦除 / dialog 仅 OCR 检测框擦除
    ocr_area_list: list[BaiduVodOcrArea] | None = None  # 空=全画面
    font_config: BaiduVodFontConfig = Field(default_factory=BaiduVodFontConfig)
    # 限流
    qps: int | None = Field(default=None, ge=1, le=100, deprecated=True)
    # 视频列表
    items: list[BaiduVodJobItemSpec]
    original_filenames: list[str] | None = None

    @field_validator("target_langs")
    @classmethod
    def at_least_one_lang(cls, v: list[str]) -> list[str]:
        if not v or not all(isinstance(x, str) and x.strip() for x in v):
            raise ValueError("target_langs 必须至少包含一个非空语言代码")
        return v

    @field_validator("translation_type_list")
    @classmethod
    def at_least_one_type(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("translation_type_list 必须至少包含一种类型(subtitle/speech)")
        for t in v:
            if t not in ("subtitle", "speech"):
                raise ValueError(f"不支持的 translation_type: {t}")
        return v

    @field_validator("text_type_list")
    @classmethod
    def normalize_text_type_list(cls, v: list[str]) -> list[str]:
        # 百度 VOD 官方支持的 textTypeList 取值:
        # dialog / castName / castDescription / other
        # 历史曾用 "title",百度端已改名为 "castName",这里做一次兼容映射。
        if not v:
            raise ValueError("text_type_list 必须至少包含一种类型(dialog/castName/castDescription/other)")
        out: list[str] = []
        for t in v:
            if t == "title":
                if "castName" not in out:
                    out.append("castName")
                continue
            if t not in ("dialog", "castName", "castDescription", "other"):
                raise ValueError(f"不支持的 text_type: {t}(允许: dialog/castName/castDescription/other)")
            if t not in out:
                out.append(t)
        return out

    @model_validator(mode="after")
    def validate_voice_mode(self) -> "BaiduVodJobCreateRequest":
        return _validate_voice_mode(self)


class BaiduVodRerunRequest(BaseModel):
    project_type: str = Field(pattern="^(ShortSeries|Ecommerce)$")
    source_language: str
    target_langs: list[str]
    translation_type_list: list[str]
    voice_mode: str | None = None
    voice_list: list[str] | None = None  # AI_DUB 必填,音色 ID 列表(百度只支持 1 个)
    recognition_type: str
    text_type_list: list[str]
    target_subtitle_compose: bool
    desubtitle_enabled: bool
    desubtitle_model: str
    desubtitle_type: str
    ocr_area_list: list[BaiduVodOcrArea] | None = None
    font_config: BaiduVodFontConfig
    qps: int | None = Field(default=None, ge=1, le=100, deprecated=True)
    force_reregister: bool = False  # 强制重新注册 media(不复用 baidu_media_id)
    force_retranslate: bool = False  # 强制重新提交翻译任务
    target_langs_to_add: list[str] | None = None  # 追加新语言(不影响已有语言产物)

    @field_validator("target_langs")
    @classmethod
    def at_least_one_lang(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("target_langs 必须至少包含一个语言")
        return v

    @field_validator("text_type_list")
    @classmethod
    def normalize_text_type_list(cls, v: list[str]) -> list[str]:
        # 百度 VOD 官方支持的 textTypeList 取值:
        # dialog / castName / castDescription / other
        # 历史曾用 "title",百度端已改名为 "castName",这里做一次兼容映射。
        if not v:
            raise ValueError("text_type_list 必须至少包含一种类型(dialog/castName/castDescription/other)")
        out: list[str] = []
        for t in v:
            if t == "title":
                if "castName" not in out:
                    out.append("castName")
                continue
            if t not in ("dialog", "castName", "castDescription", "other"):
                raise ValueError(f"不支持的 text_type: {t}(允许: dialog/castName/castDescription/other)")
            if t not in out:
                out.append(t)
        return out

    @model_validator(mode="after")
    def validate_voice_mode(self) -> "BaiduVodRerunRequest":
        return _validate_voice_mode(self)


class BaiduVodRuntimeLimitsOut(BaseModel):
    global_qps: int
    max_concurrent_jobs: int
    max_concurrent_episodes: int


class BaiduVodTranslationItemOut(BaseModel):
    """单语言的翻译任务产物"""
    baidu_task_id: str | None = None
    status: str = "pending"  # READY/RUNNING/SUCCESS/FAILED/pending
    stage: str = "pending"  # pending/uploading/registering/submitting/translating/done
    error: str | None = None
    final_video_url: str | None = None
    desubtitle_video_url: str | None = None
    cover_url: str | None = None
    source_srt_url: str | None = None
    target_srt_url: str | None = None


class BaiduVodJobItemOut(BaseModel):
    index: int
    drama_index: int
    episode_index: int
    filename: str
    input_oss_uri: str
    input_public_url: str
    input_bos_key: str | None = None
    input_bos_uri: str | None = None
    baidu_media_id: str | None = None
    baidu_upload_task_id: str | None = None
    duration_seconds: float | None = None
    warning: str | None = None
    translations: dict[str, BaiduVodTranslationItemOut]
    stage: str
    status: str
    error: str | None


class BaiduVodJobOut(BaseModel):
    id: str
    title: str
    drama_count: int
    video_count: int
    baidu_project_id: str | None
    project_type: str
    source_language: str
    target_langs: list[str]
    translation_config: dict
    subtitle_config: dict
    qps: int
    items: list[BaiduVodJobItemOut]
    original_filenames: list[str] | None
    output_bos_prefix: str
    status: str
    progress_message: str | None
    error_message: str | None
    succeeded_count: int
    failed_count: int
    registered_count: int
    total_duration_seconds: float
    submitted_at: UTCDatetime | None
    completed_at: UTCDatetime | None
    created_at: UTCDatetime
    updated_at: UTCDatetime


class BaiduVodJobSummary(BaseModel):
    id: str
    title: str
    drama_count: int
    video_count: int
    project_type: str
    source_language: str
    target_langs: list[str]
    status: str
    succeeded_count: int
    failed_count: int
    registered_count: int
    total_duration_seconds: float
    error_message: str | None
    created_at: UTCDatetime


# ---------------------- Starling 短剧翻配 ----------------------


class StarlingDramaUploadFileSpec(BaseModel):
    filename: str
    content_type: str = "video/mp4"


class StarlingDramaUploadUrlRequest(BaseModel):
    files: list[StarlingDramaUploadFileSpec]
    job_id: str | None = None


class StarlingDramaUploadEntry(BaseModel):
    filename: str
    presigned_url: str
    public_url: str
    oss_uri: str
    key: str


class StarlingDramaUploadUrlResponse(BaseModel):
    job_id: str
    expires_in: int
    entries: list[StarlingDramaUploadEntry]


class StarlingDramaMultipartPartInfo(BaseModel):
    part_number: int
    offset: int
    size: int
    presigned_url: str


class StarlingDramaMultipartUploadUrlRequest(BaseModel):
    filename: str
    content_type: str = "video/mp4"
    file_size: int = Field(ge=1)
    job_id: str | None = None
    index: int = Field(default=0, ge=0)


class StarlingDramaMultipartUploadUrlResponse(BaseModel):
    job_id: str
    upload_id: str
    key: str
    oss_uri: str
    public_url: str
    part_size: int
    parts: list[StarlingDramaMultipartPartInfo]
    expires_in: int


class StarlingDramaCompletePart(BaseModel):
    part_number: int
    etag: str


class StarlingDramaCompleteMultipartRequest(BaseModel):
    job_id: str
    key: str
    upload_id: str
    parts: list[StarlingDramaCompletePart]


class StarlingDramaCompleteMultipartResponse(BaseModel):
    public_url: str
    oss_uri: str


class StarlingDramaAbortMultipartRequest(BaseModel):
    key: str
    upload_id: str


class StarlingDramaAbortMultipartResponse(BaseModel):
    ok: bool = True


class StarlingDramaJobItemSpec(BaseModel):
    filename: str
    oss_uri: str
    public_url: str
    drama_index: int = 0
    episode_index: int = 0


class StarlingDramaJobCreateRequest(BaseModel):
    job_id: str
    title: str
    drama_name: str
    source_lang: str
    target_langs: list[str]

    subtitle_removal_mode: str = Field(default="BASIC", pattern="^(NONE|BASIC|ADVANCED)$")
    burn_target_subtitle: bool = True
    subtitle_style_template: str = "white-black-outline-v1"

    dubbing_enabled: bool = True
    dubbing_speaker_mode: str = Field(
        default="AUTO_MULTI_SPEAKER", pattern="^(AUTO_MULTI_SPEAKER|REUSE_DRAMA_SPEAKERS)$"
    )
    dubbing_emotion_mode: str = Field(default="STANDARD", pattern="^(STANDARD|HIGH_EMOTION)$")
    dubbing_preserve_bg_audio: bool = True

    workflow_mode: str = Field(
        default="FULLY_AUTOMATIC", pattern="^(FULLY_AUTOMATIC|MANUAL_REVIEW)$"
    )
    max_retry_count: int = Field(default=2, ge=0, le=10)

    items: list[StarlingDramaJobItemSpec]
    original_filenames: list[str] | None = None

    @field_validator("target_langs")
    @classmethod
    def at_least_one_lang(cls, v: list[str]) -> list[str]:
        if not v or not all(isinstance(x, str) and x.strip() for x in v):
            raise ValueError("target_langs 必须至少包含一个非空语言代码")
        return v


class StarlingDramaTranslationOut(BaseModel):
    starling_subtask_id: str | None = None
    ai_flow_status: str | None = None
    submit_status: str | None = None
    suppression_status: str | None = None
    products: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None


class StarlingDramaJobItemOut(BaseModel):
    drama_index: int
    episode_number: int
    source_filename: str
    source_oss_uri: str
    source_video_url: str | None = None
    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None

    starling_video_id: str | None = None
    upload_batch_id: str | None = None
    upload_status: str | None = None

    translations: dict[str, StarlingDramaTranslationOut]
    status: str
    error: str | None = None


class StarlingDramaJobOut(BaseModel):
    id: str
    title: str
    drama_name: str
    source_lang: str
    target_langs: list[str]

    starling_project_id: str | None
    starling_task_id: str | None

    subtitle_removal_mode: str
    burn_target_subtitle: bool
    subtitle_style_template: str

    dubbing_enabled: bool
    dubbing_speaker_mode: str
    dubbing_emotion_mode: str
    dubbing_preserve_bg_audio: bool

    workflow_mode: str
    max_retry_count: int

    items: list[StarlingDramaJobItemOut]
    original_filenames: list[str] | None
    output_oss_prefix: str
    output_tos_prefix: str | None = None
    status: str
    progress_message: str | None
    error_message: str | None
    succeeded_count: int
    failed_count: int
    submitted_at: UTCDatetime | None
    completed_at: UTCDatetime | None
    created_at: UTCDatetime
    updated_at: UTCDatetime


class StarlingDramaJobSummary(BaseModel):
    id: str
    title: str
    drama_name: str
    source_lang: str
    target_langs: list[str]
    status: str
    progress_message: str | None
    error_message: str | None
    succeeded_count: int
    failed_count: int
    submitted_at: UTCDatetime | None
    completed_at: UTCDatetime | None
    created_at: UTCDatetime


class StarlingDramaRerunRequest(BaseModel):
    """重新运行失败子任务（重置对应 item 的 translations）。"""

    target_langs: list[str] | None = None
    episode_indexes: list[int] | None = None  # 指定集重跑，None=全部失败项
