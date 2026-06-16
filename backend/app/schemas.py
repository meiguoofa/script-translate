from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, PlainSerializer


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
