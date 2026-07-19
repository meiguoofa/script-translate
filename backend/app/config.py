import re
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "Script Translate"
    api_prefix: str = "/api"
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    storage_root: str = "./storage"
    default_provider: str = "mobinova"
    prompt_version: str = "v1"
    batch_size: int = 20
    upload_max_size_mb: int = 20

    openai_api_key: str | None = None
    deepseek_api_key: str | None = None
    doubao_api_key: str | None = None
    tongyi_api_key: str | None = None
    zhipu_api_key: str | None = None
    wenwen_api_key: str | None = Field(default=None, alias="WENWEN-API-KEY")
    mobinova_api_key: str | None = None
    mobinova_base_url: str = "https://mobinova.cc/v1"

    openai_base_url: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    doubao_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    doubao_models_raw: str | None = Field(default=None, alias="DOUBAO_MODELS")
    tongyi_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    wenwen_base_url: str = "https://api.wenwen-ai.com/v1"

    access_passphrase: str | None = None

    las_api_key: str | None = None
    las_base_url: str = "https://operator.las.cn-beijing.volces.com"
    las_operator_id: str = "las_short_drama_script_gen"
    las_operator_version: str = "v1"
    las_poll_interval_seconds: int = 10
    las_poll_timeout_seconds: int = 10800

    tos_access_key_id: str | None = None
    tos_secret_access_key: str | None = None
    tos_bucket: str = "test-short-drama"
    tos_region: str = "cn-beijing"
    tos_s3_endpoint: str = "https://tos-s3-cn-beijing.volces.com"
    tos_public_endpoint: str = "tos-cn-beijing.volces.com"
    tos_output_prefix: str = "output"
    tos_upload_prefix: str = "uploads"
    # 新加坡 TOS 桶（视频字幕专用，与北京桶隔离）
    # 服务器在新加坡，走内网 ivolces.com；用户浏览器上传走外网 volces.com
    tos_sg_bucket: str = "telduanju"
    tos_sg_region: str = "ap-southeast-1"
    tos_sg_s3_internal_endpoint: str = "https://tos-s3-ap-southeast-1.ivolces.com"
    tos_sg_s3_public_endpoint: str = "https://tos-s3-ap-southeast-1.volces.com"
    tos_sg_public_endpoint: str = "tos-ap-southeast-1.volces.com"

    aliyun_access_key_id: str | None = Field(default=None, alias="ALIBABA_CLOUD_ACCESS_KEY_ID")
    aliyun_access_key_secret: str | None = Field(
        default=None, alias="ALIBABA_CLOUD_ACCESS_KEY_SECRET"
    )
    aliyun_oss_endpoint: str = "oss-cn-shanghai.aliyuncs.com"
    aliyun_oss_bucket: str = "xzdl-shortdrama"
    aliyun_oss_region: str = "cn-shanghai"
    aliyun_viapi_endpoint: str = "videoenhan.cn-shanghai.aliyuncs.com"
    viapi_poll_interval_seconds: int = 10
    viapi_poll_timeout_seconds: int = 10800
    oss_super_res_upload_prefix: str = "super-resolution-input"
    oss_super_res_output_prefix: str = "super-resolution-output"
    aliyun_videorecog_endpoint: str = "videorecog.cn-shanghai.aliyuncs.com"
    tos_subtitle_input_prefix: str = "subtitle-input"
    tos_subtitle_output_prefix: str = "subtitle-output"
    tos_presign_get_expires_seconds: int = 6 * 3600

    # 阿里云 IMS/ICE（字幕提取/擦除/视频翻译）
    aliyun_ice_endpoint: str = "ice.cn-shanghai.aliyuncs.com"
    ims_poll_interval_seconds: int = 10
    ims_poll_timeout_seconds: int = 10800
    ims_default_qps: int = 30
    # 字幕擦除 job 级全局并发上限。同时最多 N 个 job 真正运行,其余排队
    # (SQLite 单写锁下,N 越大争抢越严重;配合 Aliyun IMS RateLimiter qps=30,N=3 足够)
    max_concurrent_subtitle_erase_jobs: int = 3
    oss_subtitle_erase_input_prefix: str = "subtitle-erase-input"
    oss_subtitle_erase_output_prefix: str = "subtitle-erase-output"

    # 阿里云 MPS（媒体处理，字幕硬压烧录）
    aliyun_mps_endpoint: str = "mts.cn-shanghai.aliyuncs.com"
    aliyun_mps_pipeline_id: str = ""
    aliyun_mps_template_id: str = "d0fa510039bc4081846bc985e4fe0afe"  # 自建 H264 模板，保留原视频分辨率

    # 百度云 VOD + BOS（视频翻译:字幕擦除 + 翻译 + 语音翻译）
    baidu_access_key_id: str = Field(
        default="",
        validation_alias=AliasChoices("BAIDU_ACCESS_KEY_ID", "BAIDUYUN_ACCESS_ID"),
    )
    baidu_access_key_secret: str = Field(
        default="",
        validation_alias=AliasChoices("BAIDU_ACCESS_KEY_SECRET", "BAIDUYUN_SECRET_KEY"),
    )
    baidu_bos_bucket: str = Field(
        default="",
        validation_alias=AliasChoices("BAIDU_BOS_BUCKET", "BAIDU_YUN_BOS"),
    )
    baidu_vod_endpoint: str = "vod.bj.baidubce.com"
    baidu_bos_endpoint: str = "bj.bcebos.com"
    baidu_bos_region: str = "bj"
    baidu_vod_input_prefix: str = "baidu-vod-input"
    baidu_vod_poll_interval_seconds: int = 30
    baidu_vod_poll_timeout_seconds: int = 10800
    baidu_vod_global_qps: int = Field(default=10, ge=1)
    max_concurrent_baidu_vod_jobs: int = Field(default=3, ge=1)
    max_concurrent_baidu_vod_episodes: int = Field(default=3, ge=1)

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
