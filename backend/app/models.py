from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Script(Base):
    __tablename__ = "scripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    source_lang: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32))
    raw_text: Mapped[str] = mapped_column(Text)
    raw_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["ScriptLine"]] = relationship(
        back_populates="script",
        cascade="all, delete-orphan",
        order_by="ScriptLine.line_no",
    )
    versions: Mapped[list["TranslationVersion"]] = relationship(
        back_populates="script",
        cascade="all, delete-orphan",
        order_by="TranslationVersion.created_at.desc()",
    )


class ScriptLine(Base):
    __tablename__ = "script_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    script_id: Mapped[str] = mapped_column(ForeignKey("scripts.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    raw_line: Mapped[str] = mapped_column(Text)
    speaker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parenthetical: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dialogue: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_dialogue: Mapped[bool] = mapped_column(Boolean, default=False)

    script: Mapped["Script"] = relationship(back_populates="lines")
    translation_lines: Mapped[list["TranslationLine"]] = relationship(back_populates="line")


class TranslationVersion(Base):
    __tablename__ = "translation_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    script_id: Mapped[str] = mapped_column(ForeignKey("scripts.id", ondelete="CASCADE"), index=True)
    target_lang: Mapped[str] = mapped_column(String(16))
    model_provider: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16))
    prompt_version: Mapped[str] = mapped_column(String(32))
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    script: Mapped["Script"] = relationship(back_populates="versions")
    lines: Mapped[list["TranslationLine"]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
    )
    generated_docs: Mapped[list["GeneratedDoc"]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
    )


class TranslationLine(Base):
    __tablename__ = "translation_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("translation_versions.id", ondelete="CASCADE"), index=True)
    line_id: Mapped[str] = mapped_column(ForeignKey("script_lines.id", ondelete="CASCADE"))
    translated_dialogue: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_line: Mapped[str] = mapped_column(Text)

    version: Mapped["TranslationVersion"] = relationship(back_populates="lines")
    line: Mapped["ScriptLine"] = relationship(back_populates="translation_lines")


class GeneratedDoc(Base):
    __tablename__ = "generated_docs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("translation_versions.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    version: Mapped["TranslationVersion"] = relationship(back_populates="generated_docs")


class CleanedScriptJob(Base):
    __tablename__ = "cleaned_script_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(32))
    original_text: Mapped[str] = mapped_column(Text)
    cleaned_text: Mapped[str] = mapped_column(Text)
    line_count: Mapped[int] = mapped_column(Integer)
    stripped_count: Mapped[int] = mapped_column(Integer)
    output_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_filename: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class VideoScriptJob(Base):
    __tablename__ = "video_script_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    video_count: Mapped[int] = mapped_column(Integer, default=0)
    video_urls_json: Mapped[str] = mapped_column(Text)
    original_filenames_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_template_id: Mapped[str | None] = mapped_column(
        ForeignKey("prompt_templates.id", ondelete="SET NULL"), nullable=True
    )
    prompt_template_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    custom_script_prompt: Mapped[str] = mapped_column(Text)
    output_tos_path: Mapped[str] = mapped_column(Text)
    las_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_script_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_script_id: Mapped[str | None] = mapped_column(
        ForeignKey("scripts.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class VideoSuperResolutionJob(Base):
    __tablename__ = "video_super_resolution_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    video_count: Mapped[int] = mapped_column(Integer, default=0)
    bit_rate: Mapped[int] = mapped_column(Integer)
    items_json: Mapped[str] = mapped_column(Text)
    original_filenames_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_oss_prefix: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class VideoSubtitleJob(Base):
    __tablename__ = "video_subtitle_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    video_count: Mapped[int] = mapped_column(Integer, default=0)
    subtitle_source: Mapped[str] = mapped_column(String(16))
    enable_translate: Mapped[bool] = mapped_column(Boolean, default=False)
    enable_burn: Mapped[bool] = mapped_column(Boolean, default=False)
    placement_mode: Mapped[str] = mapped_column(String(32), default="safe_bottom")
    target_lang: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    items_json: Mapped[str] = mapped_column(Text)
    original_filenames_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_tos_prefix: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class VideoSubtitleEraseJob(Base):
    """视频字幕擦除 + 翻译任务（基于阿里云 IMS/ICE）。

    流程：CaptionExtraction → VideoDetext(基础/高级) → 翻译(阿里云/LLM) → SubmitVideoTranslationJob 烧录 → 输出 mp4
    与 video_subtitle_jobs（videorecog + ffmpeg 烧录）独立共存。
    """

    __tablename__ = "video_subtitle_erase_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    drama_count: Mapped[int] = mapped_column(Integer, default=0)
    video_count: Mapped[int] = mapped_column(Integer, default=0)

    # 流程模式
    detext_mode: Mapped[str] = mapped_column(String(16), default="advanced")  # basic / advanced
    translate_mode: Mapped[str] = mapped_column(String(16), default="llm")  # aliyun / llm
    burn_mode: Mapped[str] = mapped_column(String(16), default="mps")  # local / aliyun / mps
    placement_mode: Mapped[str] = mapped_column(String(32), default="safe_bottom")  # safe_bottom / simple_bottom
    source_lang: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 多语言:JSON 数组,如 ["pt","en"]。旧字段 target_lang 保留做迁移兜底,新代码用 target_langs_json
    target_lang: Mapped[str | None] = mapped_column(String(16), nullable=True)
    target_langs_json: Mapped[str] = mapped_column(String(255), default="[]")
    model_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # QPS（全工程共享限流）
    qps: Mapped[int] = mapped_column(Integer, default=30)

    # 字幕提取参数（前端可调）
    caption_fps: Mapped[int] = mapped_column(Integer, default=5)
    caption_lang: Mapped[str] = mapped_column(String(16), default="ch_ml")
    caption_track: Mapped[str] = mapped_column(String(16), default="main")
    caption_roi: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON "[[top,bottom],[left,right]]"
    caption_sep: Mapped[bool] = mapped_column(Boolean, default=False)

    # 字幕擦除参数
    detext_limit_region: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON "[[x,y,w,h]]"

    # 字幕烧录参数
    burn_font_size: Mapped[int] = mapped_column(Integer, default=72)
    burn_font_color: Mapped[str] = mapped_column(String(16), default="#FFFFFF")
    burn_font_color_opacity: Mapped[float] = mapped_column(Numeric(3, 2), default=1.0)
    burn_x: Mapped[float] = mapped_column(Numeric(3, 2), default=0.5)
    burn_y: Mapped[float] = mapped_column(Numeric(3, 2), default=0.82)
    burn_text_width: Mapped[float] = mapped_column(Numeric(3, 2), default=0.9)

    items_json: Mapped[str] = mapped_column(Text)
    original_filenames_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_oss_prefix: Mapped[str] = mapped_column(Text)
    output_tos_prefix: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class VideoBaiduVodJob(Base):
    """百度云 VOD 视频翻译任务(字幕擦除 + 翻译 + 语音翻译)。

    基于百度 VOD workflow:Project(短剧容器) -> Media(单集视频) -> Task(一集×一语言)。
    items_json 嵌套 translations[lang],与 VideoSubtitleEraseJob 结构对齐。
    """

    __tablename__ = "video_baidu_vod_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    drama_count: Mapped[int] = mapped_column(Integer, default=0)
    video_count: Mapped[int] = mapped_column(Integer, default=0)

    # 百度 VOD 项目 ID(一部短剧一个 project)
    baidu_project_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 项目类型:ShortSeries 短剧 / Ecommerce 电商
    project_type: Mapped[str] = mapped_column(String(32), default="ShortSeries")

    # 语言配置
    source_language: Mapped[str] = mapped_column(String(16))  # 如 zh-CN/en-US
    target_langs_json: Mapped[str] = mapped_column(String(255), default="[]")  # ["en-US","es-ES"]

    # 翻译配置(translationConfig,JSON blob)
    # translationTypeList(subtitle/speech)/voiceMode(VOICE_CLONE/AI_DUB)
    translation_config_json: Mapped[str] = mapped_column(Text, default="{}")

    # 字幕配置(subtitleConfig,JSON blob)
    # recognitionType(OCR/ASR)/textTypeList/targetSubtitleCompose/desubtitleConfig/ocrConfig/fontConfig
    subtitle_config_json: Mapped[str] = mapped_column(Text, default="{}")

    # 输入源(阿里云 OSS URL 列表或百度 BOS key,JSON blob)
    # 每个 item 有 input_oss_uri / input_bos_key / baidu_media_id
    items_json: Mapped[str] = mapped_column(Text)
    original_filenames_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 百度 BOS 输出前缀(结果落 BOS)
    output_bos_prefix: Mapped[str] = mapped_column(Text)

    # QPS 限流(百度 API 限流)
    qps: Mapped[int] = mapped_column(Integer, default=10)

    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class VideoImsSpeechJob(Base):
    """阿里云 IMS 一站式语音级视频翻译任务。"""

    __tablename__ = "video_ims_speech_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    drama_count: Mapped[int] = mapped_column(Integer, default=0)
    video_count: Mapped[int] = mapped_column(Integer, default=0)
    source_language: Mapped[str] = mapped_column(String(16))
    target_langs_json: Mapped[str] = mapped_column(String(255), default="[]")
    text_source: Mapped[str] = mapped_column(String(16), default="ASR")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    items_json: Mapped[str] = mapped_column(Text)
    original_filenames_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_oss_prefix: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StarlingDramaJob(Base):
    """火山引擎 Starling 短剧全链路翻配任务。

    流程：VideoProjectCreate -> VideoProjectVideoUpload -> VideoProjectSerialTaskCreate
        -> VideoProjectTaskBatchStartAIFlow -> VideoEditorSubmitSubtask
        -> VideoProjectSuppressionStart -> VideoProjectGetTaskProduct -> 归档 OSS

    items_json 嵌套 translations[lang]，结构与 VideoSubtitleEraseJob 对齐。
    Starling 仅作为异步 AI 处理引擎；幂等、重试、版本、产物全部由本地后端掌握。
    """

    __tablename__ = "starling_drama_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    drama_name: Mapped[str] = mapped_column(String(255), index=True)
    source_lang: Mapped[str] = mapped_column(String(16))
    target_langs_json: Mapped[str] = mapped_column(String(255), default="[]")  # ["en"]

    # Starling 对象引用
    starling_project_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    starling_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 字幕处理
    subtitle_removal_mode: Mapped[str] = mapped_column(String(16), default="BASIC")  # NONE/BASIC/ADVANCED
    burn_target_subtitle: Mapped[bool] = mapped_column(Boolean, default=True)
    subtitle_style_template: Mapped[str] = mapped_column(String(64), default="white-black-outline-v1")

    # 配音配置
    dubbing_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    dubbing_speaker_mode: Mapped[str] = mapped_column(String(32), default="AUTO_MULTI_SPEAKER")
    dubbing_emotion_mode: Mapped[str] = mapped_column(String(16), default="STANDARD")
    dubbing_preserve_bg_audio: Mapped[bool] = mapped_column(Boolean, default=True)

    # 工作流配置
    workflow_mode: Mapped[str] = mapped_column(String(24), default="FULLY_AUTOMATIC")
    max_retry_count: Mapped[int] = mapped_column(Integer, default=2)

    # 嵌套子任务（按集 × 目标语言）
    items_json: Mapped[str] = mapped_column(Text)
    original_filenames_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_oss_prefix: Mapped[str] = mapped_column(Text)
    output_tos_prefix: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AppSetting(Base):
    """通用 KV 设置表（key-value）。单行存 JSON blob。

    用于持久化前端表单参数等配置，避免依赖浏览器 localStorage。
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
