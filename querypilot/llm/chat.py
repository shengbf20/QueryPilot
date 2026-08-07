"""Unified DeepSeek chat helpers: generate text / JSON."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from querypilot.config import get_settings
from querypilot.llm.client import get_llm_client

_FENCE_RE = re.compile(r"^```(?:json)?\s*([\s\S]*?)\s*```$", re.IGNORECASE)


@dataclass(frozen=True)
class ChatResult:
    """Normalized chat completion payload."""

    content: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class JsonParseError(ValueError):
    """Raised when the model response cannot be parsed as JSON."""


def _as_message_dicts(
    messages: Sequence[dict[str, str]] | Sequence[tuple[str, str]],
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in messages:
        if isinstance(item, dict):
            out.append({"role": item["role"], "content": item["content"]})
        else:
            role, content = item
            out.append({"role": role, "content": content})
    return out


def chat(
    messages: Sequence[dict[str, str]] | Sequence[tuple[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    response_format: dict[str, str] | None = None,
    client: OpenAI | None = None,
) -> ChatResult:
    """Low-level chat completion against the configured DeepSeek model."""
    settings = get_settings()
    active_client = client or get_llm_client()
    kwargs: dict[str, Any] = {
        "model": model or settings.deepseek_model,
        "messages": _as_message_dicts(messages),
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if response_format is not None:
        kwargs["response_format"] = response_format

    response = active_client.chat.completions.create(**kwargs)
    choice = response.choices[0].message
    content = choice.content or ""
    usage = response.usage
    return ChatResult(
        content=content,
        model=response.model or kwargs["model"],
        prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
        completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        total_tokens=getattr(usage, "total_tokens", None) if usage else None,
    )


def generate(
    prompt: str,
    *,
    system: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    client: OpenAI | None = None,
) -> str:
    """Single-turn text generation. Returns assistant content only."""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return chat(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        client=client,
    ).content


def parse_json_content(content: str) -> dict[str, Any]:
    """Parse JSON from model output, tolerating optional markdown fences."""
    text = content.strip()
    if not text:
        raise JsonParseError("Empty model response")

    match = _FENCE_RE.match(text)
    if match:
        text = match.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise JsonParseError(f"Invalid JSON from model: {exc}") from exc

    if not isinstance(data, dict):
        raise JsonParseError(f"Expected JSON object, got {type(data).__name__}")
    return data


def generate_json(
    prompt: str,
    *,
    system: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    client: OpenAI | None = None,
    use_json_object_format: bool = True,
) -> dict[str, Any]:
    """Generate and parse a JSON object response.

    When ``use_json_object_format`` is True, requests ``response_format=json_object``
    (DeepSeek / OpenAI compatible). The prompt or system message should mention JSON.
    """
    system_msg = system or "You are a helpful assistant that responds with valid JSON only."
    if use_json_object_format and "json" not in system_msg.lower() and "json" not in prompt.lower():
        system_msg = f"{system_msg.rstrip()} Respond with a JSON object."

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": prompt},
    ]
    result = chat(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"} if use_json_object_format else None,
        client=client,
    )
    return parse_json_content(result.content)
