from dataclasses import asdict, dataclass

from app.config import Settings
from app.llm.base import BaseLLMProvider
from app.llm.providers import OpenAICompatibleProvider


@dataclass(slots=True)
class ModelDefinition:
    provider: str
    name: str
    label: str
    target_langs: list[str]
    default: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._providers: dict[str, BaseLLMProvider] = {}
        self._models: list[ModelDefinition] = []
        self._register_external_providers()
        self._validate_default_provider()

    def _add_model(
        self,
        *,
        provider: str,
        name: str,
        label: str,
        target_langs: list[str],
        default: bool = False,
    ) -> None:
        self._models.append(
            ModelDefinition(
                provider=provider,
                name=name,
                label=label,
                target_langs=target_langs,
                default=default,
            )
        )

    def _register_external_providers(self) -> None:
        if self.settings.deepseek_api_key:
            self._providers["deepseek"] = OpenAICompatibleProvider(
                "deepseek",
                self.settings.deepseek_api_key,
                self.settings.deepseek_base_url,
            )
            self._add_model(
                provider="deepseek",
                name="deepseek-chat",
                label="DeepSeek Chat",
                target_langs=["zh", "en", "th", "ar"],
                default=self.settings.default_provider == "deepseek",
            )
        if self.settings.openai_api_key:
            self._providers["openai"] = OpenAICompatibleProvider(
                "openai",
                self.settings.openai_api_key,
                self.settings.openai_base_url,
            )
            self._add_model(
                provider="openai",
                name="gpt-4.1-mini",
                label="OpenAI GPT-4.1 Mini",
                target_langs=["zh", "en", "th", "ar"],
                default=self.settings.default_provider == "openai",
            )
        if self.settings.doubao_api_key:
            self._providers["doubao"] = OpenAICompatibleProvider(
                "doubao",
                self.settings.doubao_api_key,
                self.settings.doubao_base_url,
            )
            for index, model_name in enumerate(self.settings.doubao_models):
                self._add_model(
                    provider="doubao",
                    name=model_name,
                    label=model_name,
                    target_langs=["zh", "en", "th", "ar"],
                    default=self.settings.default_provider == "doubao" and index == 0,
                )
        if self.settings.tongyi_api_key:
            self._providers["tongyi"] = OpenAICompatibleProvider(
                "tongyi",
                self.settings.tongyi_api_key,
                self.settings.tongyi_base_url,
            )
            self._add_model(
                provider="tongyi",
                name="qwen-plus",
                label="Tongyi Qwen Plus",
                target_langs=["zh", "en", "th", "ar"],
                default=self.settings.default_provider == "tongyi",
            )
        if self.settings.zhipu_api_key:
            self._providers["zhipu"] = OpenAICompatibleProvider(
                "zhipu",
                self.settings.zhipu_api_key,
                self.settings.zhipu_base_url,
            )
            self._add_model(
                provider="zhipu",
                name="glm-4.5-air",
                label="Zhipu GLM 4.5 Air",
                target_langs=["zh", "en", "th", "ar"],
                default=self.settings.default_provider == "zhipu",
            )

    def _validate_default_provider(self) -> None:
        if self.settings.default_provider == "doubao" and not self.settings.doubao_api_key:
            raise ValueError("DOUBAO_API_KEY is required when DEFAULT_PROVIDER=doubao.")
        if self.settings.default_provider == "doubao" and not self.settings.doubao_models:
            raise ValueError("DOUBAO_MODELS is required when DEFAULT_PROVIDER=doubao.")
        if not self._providers:
            raise ValueError("No LLM providers are configured. Set at least one API key.")
        if self.settings.default_provider not in self._providers:
            raise ValueError(
                f"DEFAULT_PROVIDER `{self.settings.default_provider}` is not configured with a usable API key."
            )

    def list_models(self) -> list[ModelDefinition]:
        return self._models

    def get_provider(self, name: str) -> BaseLLMProvider:
        provider = self._providers.get(name)
        if provider is None:
            raise KeyError(f"Provider `{name}` is not configured.")
        return provider
