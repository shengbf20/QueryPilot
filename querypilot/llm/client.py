"""DeepSeek / OpenAI-compatible LLM client."""

from __future__ import annotations

from openai import OpenAI

from querypilot.config import get_settings


def get_llm_client() -> OpenAI:
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY is not set in .env")
    return OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )
