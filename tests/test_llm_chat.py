"""Tests for LLM chat helpers.

- Local unit tests: JSON parsing (no network).
- Live integration tests: real DeepSeek API via ``querypilot.llm`` (same path as production).
  Skipped when ``DEEPSEEK_API_KEY`` is missing or still a placeholder.
"""

from __future__ import annotations

import pytest

from querypilot.config import get_settings
from querypilot.llm import JsonParseError, chat, generate, generate_json, parse_json_content


def _api_key_ready() -> bool:
    key = get_settings().deepseek_api_key
    return bool(key) and not key.startswith("sk-your")


requires_live_llm = pytest.mark.skipif(
    not _api_key_ready(),
    reason="DEEPSEEK_API_KEY not set (or still placeholder in .env)",
)


# ---------------------------------------------------------------------------
# Local unit tests (no LLM)
# ---------------------------------------------------------------------------


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


def test_parse_json_content_empty():
    with pytest.raises(JsonParseError, match="Empty"):
        parse_json_content("")


# ---------------------------------------------------------------------------
# Live API tests (same code path as runtime)
# ---------------------------------------------------------------------------


@requires_live_llm
def test_live_chat_returns_content():
    result = chat(
        [{"role": "user", "content": "只回复两个字母：OK"}],
        max_tokens=16,
        temperature=0.0,
    )
    assert result.content
    assert "OK" in result.content.upper()
    assert result.model
    assert result.total_tokens is None or result.total_tokens > 0


@requires_live_llm
def test_live_generate_text():
    text = generate(
        "只回复两个字母：OK",
        system="你是简洁助手，严格按用户要求回复。",
        max_tokens=16,
        temperature=0.0,
    )
    assert "OK" in text.upper()


@requires_live_llm
def test_live_generate_json_object():
    data = generate_json(
        '返回一个 JSON 对象，包含字段 ok（布尔值 true）和 echo（字符串 "ping"）。不要其它字段。',
        system="You respond with a JSON object only.",
        max_tokens=64,
        temperature=0.0,
    )
    assert data.get("ok") is True
    assert data.get("echo") == "ping"
