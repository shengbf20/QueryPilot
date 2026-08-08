"""Tests for L2 EXPLAIN fence + 1-Shot correction (phase-2 step 5)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from querypilot.config import get_settings
from querypilot.metadata_engine import load_metadata
from querypilot.safety import (
    CORRECTION_SYSTEM,
    build_correction_prompt,
    correct_sql_once,
    run_explain,
    validate_with_l2,
)


def _api_key_ready() -> bool:
    key = get_settings().deepseek_api_key
    return bool(key) and not key.startswith("sk-your")


requires_live_llm = pytest.mark.skipif(
    not _api_key_ready(),
    reason="DEEPSEEK_API_KEY not set (or still placeholder in .env)",
)

requires_db = pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)


@pytest.fixture(scope="module")
def metadata():
    return load_metadata(load_db_codes=False)


# ---------------------------------------------------------------------------
# Correction prompt (no LLM / DB)
# ---------------------------------------------------------------------------


def test_build_correction_prompt_includes_error_and_sql():
    text = build_correction_prompt(
        question="女性客户数",
        failed_sql="SELECT bad_col FROM ads_cust_info_d",
        error='Binder Error: Referenced column "bad_col" not found',
        schema_context="表: ads_cust_info_d",
    )
    assert "女性客户数" in text
    assert "bad_col" in text
    assert "Binder Error" in text
    assert "ads_cust_info_d" in text
    assert "JSON" in text
    assert "只尝试一次" in text


def test_correction_system_limits_to_one_fix():
    assert "只修正错误" in CORRECTION_SYSTEM
    assert "一次失败 SQL" in CORRECTION_SYSTEM or "DuckDB 报错" in CORRECTION_SYSTEM
    assert "JSON" in CORRECTION_SYSTEM


# ---------------------------------------------------------------------------
# EXPLAIN only
# ---------------------------------------------------------------------------


@requires_db
def test_run_explain_ok():
    result = run_explain("SELECT COUNT(*) AS n FROM ads_cust_info_d")
    assert result.ok
    assert result.error is None


@requires_db
def test_run_explain_fail_unknown_column():
    result = run_explain("SELECT totally_missing_col_xyz FROM ads_cust_info_d")
    assert not result.ok
    assert result.error


@requires_db
def test_validate_l2_passes_without_correction(metadata):
    result = validate_with_l2(
        "SELECT cust_age FROM ads_cust_info_d LIMIT 1",
        question="年龄",
        metadata=metadata,
        enable_correction=True,
    )
    assert result.ok
    assert not result.corrected
    assert not result.degraded
    assert result.attempts == 1


@requires_db
def test_validate_l2_degrades_when_correction_disabled(metadata):
    result = validate_with_l2(
        "SELECT totally_missing_col_xyz FROM ads_cust_info_d",
        question="测试",
        metadata=metadata,
        enable_correction=False,
    )
    assert not result.ok
    assert result.degraded
    assert result.explain_error
    assert "correction disabled" in result.message.lower() or "EXPLAIN failed" in result.message


# ---------------------------------------------------------------------------
# Fake client 1-Shot paths
# ---------------------------------------------------------------------------


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self._content = content
        self.last_kwargs: dict[str, Any] | None = None
        self.calls = 0

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls += 1
        self.last_kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))],
            model=kwargs.get("model", "fake-model"),
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(content))


class _RaisingCompletions:
    def __init__(self) -> None:
        self.calls = 0
        self.last_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls += 1
        self.last_kwargs = kwargs
        raise RuntimeError("simulated LLM failure")


class _RaisingClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=_RaisingCompletions())


@requires_db
def test_validate_l2_corrects_once_with_fake_client(metadata):
    bad = "SELECT cust_agge_typo_zzz FROM ads_cust_info_d"
    # First EXPLAIN fails; fake LLM returns a valid SQL.
    client = _FakeClient(
        '{"sql":"SELECT cust_age FROM ads_cust_info_d","rationale":"修正列名","uses_cte":false}'
    )
    result = validate_with_l2(
        bad,
        question="客户年龄",
        schema_context="表: ads_cust_info_d\n字段: cust_age",
        metadata=metadata,
        allowed_tables={"ads_cust_info_d"},
        client=client,
    )
    assert result.ok, result.message
    assert result.corrected
    assert not result.degraded
    assert "cust_age" in result.sql
    assert client.chat.completions.calls == 1
    assert result.attempts == 2
    assert result.original_sql == bad
    assert result.l1_after_correction is not None
    assert result.l1_after_correction.ok
    system = client.chat.completions.last_kwargs["messages"][0]["content"]
    assert system == CORRECTION_SYSTEM
    assert "只修正错误" in system


@requires_db
def test_validate_l2_degrades_when_correction_still_invalid(metadata):
    bad = "SELECT totally_missing_col_xyz FROM ads_cust_info_d"
    client = _FakeClient(
        '{"sql":"SELECT another_missing_col_abc FROM ads_cust_info_d",'
        '"rationale":"仍错误","uses_cte":false}'
    )
    result = validate_with_l2(
        bad,
        question="测试",
        metadata=metadata,
        allowed_tables={"ads_cust_info_d"},
        client=client,
    )
    assert not result.ok
    assert result.degraded
    assert result.corrected
    assert client.chat.completions.calls == 1  # only one shot
    assert result.attempts == 2
    assert "一次纠错" in result.message or result.explain_error


@requires_db
def test_validate_l2_degrades_when_correction_fails_l1(metadata):
    bad = "SELECT totally_missing_col_xyz FROM ads_cust_info_d"
    # Correction introduces unauthorized table → L1 blocks before second EXPLAIN.
    client = _FakeClient(
        '{"sql":"SELECT * FROM secret_table","rationale":"坏修正","uses_cte":false}'
    )
    result = validate_with_l2(
        bad,
        question="测试",
        metadata=metadata,
        allowed_tables={"ads_cust_info_d"},
        client=client,
    )
    assert not result.ok
    assert result.degraded
    assert result.corrected
    assert result.sql == bad
    assert result.original_sql == bad
    assert result.attempts == 2
    assert client.chat.completions.calls == 1
    assert result.l1_after_correction is not None
    assert not result.l1_after_correction.ok
    assert "L1" in result.message


@requires_db
def test_validate_l2_degrades_when_correction_raises(metadata):
    bad = "SELECT totally_missing_col_xyz FROM ads_cust_info_d"
    client = _RaisingClient()
    result = validate_with_l2(
        bad,
        question="测试",
        metadata=metadata,
        allowed_tables={"ads_cust_info_d"},
        client=client,
    )
    assert not result.ok
    assert result.degraded
    assert result.sql == bad
    assert result.original_sql == bad
    assert result.attempts == 2
    assert client.chat.completions.calls == 1
    assert "1-Shot correction failed" in result.message
    assert "simulated LLM failure" in result.message


@requires_db
def test_correct_sql_once_with_fake_client():
    client = _FakeClient(
        '{"sql":"SELECT 1 AS n","rationale":"ok","uses_cte":false}'
    )
    sql, rationale, raw = correct_sql_once(
        question="q",
        failed_sql="SELECT bad",
        error="err",
        client=client,
    )
    assert sql == "SELECT 1 AS n"
    assert rationale == "ok"
    assert raw["sql"] == "SELECT 1 AS n"
    kwargs = client.chat.completions.last_kwargs
    assert kwargs is not None
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["messages"][0]["content"] == CORRECTION_SYSTEM
    assert "err" in kwargs["messages"][1]["content"]
    assert "只尝试一次" in kwargs["messages"][1]["content"]


# ---------------------------------------------------------------------------
# Live DeepSeek + DuckDB
# ---------------------------------------------------------------------------


@requires_db
@requires_live_llm
def test_live_l2_passes_good_sql(metadata):
    result = validate_with_l2(
        "SELECT COUNT(*) AS cnt FROM ads_cust_info_d WHERE cust_age > 30",
        question="30岁以上客户数",
        metadata=metadata,
    )
    assert result.ok
    assert not result.corrected


@requires_db
@requires_live_llm
def test_live_l2_one_shot_fixes_bad_column(metadata):
    # Enter L2 with a clearly invalid column (L1 not applied on the original here).
    bad = "SELECT not_a_real_column_42 FROM ads_cust_info_d LIMIT 5"
    result = validate_with_l2(
        bad,
        question="查看客户列表（任意合理字段即可）",
        schema_context=metadata.format_table_schema("ads_cust_info_d", include_values=False),
        metadata=metadata,
        allowed_tables={"ads_cust_info_d"},
    )
    # Strong success: corrected and EXPLAIN ok. Soft success: graceful degrade, still one shot.
    assert result.attempts <= 2
    if result.ok:
        assert result.corrected
        assert "not_a_real_column_42" not in result.sql
        assert run_explain(result.sql).ok
    else:
        assert result.degraded
        assert result.message
