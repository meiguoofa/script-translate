import re
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Script Translate"
    api_prefix: str = "/api"
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    storage_root: str = "./storage"
    default_provider: str = "doubao"
    prompt_version: str = "v1"
    batch_size: int = 20
    upload_max_size_mb: int = 20

    openai_api_key: str | None = None
    deepseek_api_key: str | None = None
    doubao_api_key: str | None = None
    tongyi_api_key: str | None = None
    zhipu_api_key: str | None = None
    wenwen_api_key: str | None = Field(default=None, alias="WENWEN-API-KEY")

    openai_base_url: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    doubao_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    doubao_models_raw: str | None = Field(default=None, alias="DOUBAO_MODELS")
    tongyi_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    wenwen_base_url: str = "https://api.wenwen-ai.com/v1"

    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_root).resolve()

    @property
    def uploads_path(self) -> Path:
        return self.storage_path / "uploads"

    @property
    def generated_path(self) -> Path:
        return self.storage_path / "generated"

    def _read_doubao_models_from_env_file(self) -> list[str]:
        env_file = self.model_config.get("env_file")
        if not env_file:
            return []

        env_path = Path(env_file)
        if not env_path.is_absolute():
            env_path = Path.cwd() / env_path
        if not env_path.exists():
            return []

        models: list[str] = []
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line.startswith("#"):
                continue
            comment = line[1:].strip()
            if not comment:
                continue
            for item in comment.split(","):
                model = item.strip()
                if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", model):
                    models.append(model)
        return models

    @property
    def doubao_models(self) -> list[str]:
        models: list[str] = []
        seen: set[str] = set()
        raw_models: list[str] = []
        if self.doubao_models_raw:
            raw_models.extend(self.doubao_models_raw.split(","))
        raw_models.extend(self._read_doubao_models_from_env_file())

        for item in raw_models:
            model = item.strip()
            if not model or model in seen:
                continue
            seen.add(model)
            models.append(model)
        return models
