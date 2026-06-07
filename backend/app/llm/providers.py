import re

import httpx
from openai import AsyncOpenAI

from app.llm.base import BaseLLMProvider, TranslationBatchLine, TranslationBatchResult


LINE_RE = re.compile(r"^(L\d{3})\s*=\s*(.+)$")


def build_prompt(target_lang: str, context: str, lines: list[TranslationBatchLine]) -> str:
    source_lines = "\n".join(f"{line.label} = {line.text}" for line in lines)
    return (
        "你是短剧本地化译者。请只翻译对话内容，不要翻译人物名前缀和括号内动作。\n"
        f"目标语言：{target_lang}\n"
        "要求：口语化、情绪自然、严格返回 `Lxxx = 译文`。\n"
        f"场景上下文：{context or '无'}\n"
        f"待翻译行：\n{source_lines}"
    )


def parse_completion(content: str) -> dict[str, str]:
    translations: dict[str, str] = {}
    for raw_line in content.splitlines():
        match = LINE_RE.match(raw_line.strip())
        if match:
            translations[match.group(1)] = match.group(2).strip()
    return translations


SYSTEM_PROMPT = "你是短剧翻译助手，输出必须为 `Lxxx = 译文` 的纯文本。"


class OpenAICompatibleProvider(BaseLLMProvider):
    def __init__(self, provider_name: str, api_key: str, base_url: str | None = None) -> None:
        self.provider_name = provider_name
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def translate_batch(
        self,
        *,
        model: str,
        target_lang: str,
        context: str,
        lines: list[TranslationBatchLine],
    ) -> TranslationBatchResult:
        response = await self.client.chat.completions.create(
            model=model,
            temperature=0.4,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(target_lang, context, lines)},
            ],
        )
        content = response.choices[0].message.content or ""
        translations = parse_completion(content)
        return TranslationBatchResult(
            translations=translations,
            total_tokens=response.usage.total_tokens if response.usage else 0,
        )


class AnthropicMessagesProvider(BaseLLMProvider):
    def __init__(self, provider_name: str, api_key: str, base_url: str) -> None:
        self.provider_name = provider_name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def translate_batch(
        self,
        *,
        model: str,
        target_lang: str,
        context: str,
        lines: list[TranslationBatchLine],
    ) -> TranslationBatchResult:
        payload = {
            "model": model,
            "max_tokens": 4096,
            "temperature": 0.4,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": build_prompt(target_lang, context, lines)},
            ],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/messages", json=payload, headers=headers
            )
            response.raise_for_status()
            data = response.json()

        content_parts = data.get("content") or []
        content = "".join(
            part.get("text", "") for part in content_parts if part.get("type") == "text"
        )
        translations = parse_completion(content)
        usage = data.get("usage") or {}
        total_tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        return TranslationBatchResult(translations=translations, total_tokens=total_tokens)


class RoutingProvider(BaseLLMProvider):
    """Dispatch translate_batch to different sub-providers based on model name."""

    def __init__(self, provider_name: str, routes: dict[str, BaseLLMProvider]) -> None:
        self.provider_name = provider_name
        self.routes = routes

    async def translate_batch(
        self,
        *,
        model: str,
        target_lang: str,
        context: str,
        lines: list[TranslationBatchLine],
    ) -> TranslationBatchResult:
        sub = self.routes.get(model)
        if sub is None:
            raise KeyError(f"Model `{model}` is not registered under provider `{self.provider_name}`.")
        return await sub.translate_batch(
            model=model, target_lang=target_lang, context=context, lines=lines
        )
