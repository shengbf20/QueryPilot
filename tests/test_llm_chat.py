"""Unit tests for LLM chat helpers (no live API required)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from querypilot.llm import JsonParseError, generate, generate_json, parse_json_content
from querypilot.llm.chat import chat


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self._content = content
        self.last_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.last_kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))],
            model=kwargs.get("model", "fake-model"),
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=5, total_tokens=8),
        )


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(content))


def test_parse_json_content_plain():
    assert parse_json_content('{"sql": "SELECT 1"}') == {"sql": "SELECT 1"}


def test_parse_json_content_fenced():
    raw = '```json\n{"sql": "SELECT 1"}\n```'
    assert parse_json_content(raw) == {"sql": "SELECT 1"}


def test_parse_json_content_invalid():
    with pytest.raises(JsonParseError):
        parse_json_content("not-json")


def test_parse_json_content_rejects_array():
    with pytest.raises(JsonParseError, match="JSON object"):
        parse_json_content("[1, 2]")


def test_chat_with_fake_client():
    client = _FakeClient("hello")
    result = chat([{"role": "user", "content": "hi"}], client=client, model="m")
    assert result.content == "hello"
    assert result.model == "m"
    assert result.total_tokens == 8


def test_generate_builds_messages():
    client = _FakeClient("ok")
    text = generate("ping", system="sys", client=client, model="m")
    assert text == "ok"
    kwargs = client.chat.completions.last_kwargs
    assert kwargs is not None
    assert kwargs["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "ping"},
    ]


def test_generate_json_uses_json_object_format():
    client = _FakeClient('{"a": 1}')
    data = generate_json("return json", client=client, model="m")
    assert data == {"a": 1}
    kwargs = client.chat.completions.last_kwargs
    assert kwargs is not None
    assert kwargs["response_format"] == {"type": "json_object"}
