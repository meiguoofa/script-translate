from datetime import datetime

from pydantic import BaseModel


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
    created_at: datetime
    version_count: int


class ScriptDetail(BaseModel):
    id: str
    title: str
    source_lang: str | None
    source_type: str
    created_at: datetime
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
    created_at: datetime
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
    created_at: datetime
    rendered_lines: list[str]
