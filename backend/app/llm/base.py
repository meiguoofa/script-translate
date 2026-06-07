from dataclasses import dataclass


@dataclass(slots=True)
class TranslationBatchLine:
    label: str
    line_id: str
    text: str


@dataclass(slots=True)
class TranslationBatchResult:
    translations: dict[str, str]
    total_tokens: int = 0


class BaseLLMProvider:
    provider_name: str

    async def translate_batch(
        self,
        *,
        model: str,
        target_lang: str,
        context: str,
        lines: list[TranslationBatchLine],
    ) -> TranslationBatchResult:
        raise NotImplementedError
