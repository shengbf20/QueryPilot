"""Tests for result probe + end-to-end pipeline (phase-2 step 6)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from querypilot.agent import ask
from querypilot.config import get_settings
from querypilot.db import QueryResult
from querypilot.metadata_engine import load_metadata
from querypilot.safety import probe_result


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
    return load_metadata(load_db_codes=True)


# ---------------------------------------------------------------------------
# Result probe (no LLM)
# ---------------------------------------------------------------------------


def test_probe_empty_result_suggests_relaxing_age():
    result = QueryResult(columns=["pty_id"], rows=[], row_count=0)
    probe = probe_result("筛选30岁以上的女性客户", result)
    assert probe.triggered
    assert probe.code == "empty_result"
    assert any("30" in s or "年龄" in s for s in probe.suggestions)
    assert any("性别" in s for s in probe.suggestions)


def test_probe_zero_count():
    result = QueryResult(columns=["cnt"], rows=[(0,)], row_count=1)
    probe = probe_result("总资产超过100万的客户有多少", result)
    assert probe.triggered
    assert probe.code == "zero_count"
    assert probe.suggestions


def test_probe_ok_non_empty():
    result = QueryResult(columns=["cnt"], rows=[(12,)], row_count=1)
    probe = probe_result("客户数量", result)
    assert not probe.triggered
    assert probe.code == "ok"


def test_probe_extreme_value():
    result = QueryResult(columns=["nm_tot_aset"], rows=[(1e20,)], row_count=1)
    probe = probe_result("总资产", result)
    assert probe.triggered
    assert probe.code == "extreme_value"


def test_ask_empty_question():
    out = ask("   ")
    assert not out.ok
    assert out.degraded
    assert out.stage == "prune"


# ---------------------------------------------------------------------------
# Pipeline with fake LLM client
# ---------------------------------------------------------------------------


class _FakeCompletions:
    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.calls = 0
        self.last_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls += 1
        self.last_kwargs = kwargs
        content = (
            self._contents.pop(0)
            if self._contents
            else '{"sql":"SELECT 1","rationale":"","uses_cte":false}'
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            model=kwargs.get("model", "fake-model"),
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


class _FakeClient:
    def __init__(self, contents: list[str]) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(contents))


@requires_db
def test_ask_pipeline_with_fake_client_success(metadata):
    client = _FakeClient(
        [
            '{"sql":"SELECT COUNT(*) AS cnt FROM ads_cust_info_d WHERE cust_age > 30",'
            '"rationale":"统计年龄","uses_cte":false}'
        ]
    )
    out = ask(
        "年龄大于30的客户有多少",
        metadata=metadata,
        client=client,
        include_values=False,
        max_few_shots=0,
    )
    assert out.ok, out.message
    assert out.stage == "done"
    assert "ads_cust_info_d" in out.sql
    assert out.row_count == 1
    assert out.columns == ["cnt"]
    assert isinstance(out.rows[0][0], (int, float))
    assert out.tables
    # No L2 correction needed → exactly one LLM call (SQL generation)
    assert client.chat.completions.calls == 1


def test_ask_pipeline_clarify_skips_execute(metadata):
    client = _FakeClient(
        [
            '{"sql":"","rationale":"缺指标","uses_cte":false,'
            '"clarify":"您要统计人数、资产还是持仓？"}'
        ]
    )
    out = ask(
        "帮我看看客户情况",
        metadata=metadata,
        client=client,
        include_values=False,
        max_few_shots=0,
        use_cache=False,
    )
    assert out.ok
    assert out.stage == "clarify"
    assert out.sql == ""
    assert "人数" in out.message
    assert out.extras.get("needs_clarify") is True
    assert out.rows == []
    assert client.chat.completions.calls == 1


@requires_db
def test_ask_pipeline_followup_history_generates_sql(metadata):
    client = _FakeClient(
        [
            '{"sql":"SELECT COUNT(*) AS cnt FROM ads_cust_info_d '
            "WHERE cust_age > 30 AND gender_cd = '5000003'\","
            '"rationale":"补充后可写 SQL","uses_cte":false,"clarify":""}'
        ]
    )
    out = ask(
        "只要30岁以上女性人数",
        metadata=metadata,
        client=client,
        include_values=False,
        max_few_shots=0,
        use_cache=False,
        history=[
            {"role": "user", "content": "帮我看看客户情况"},
            {"role": "assistant", "content": "您要统计人数还是资产？"},
        ],
    )
    assert out.ok, out.message
    assert out.stage == "done"
    assert out.sql
    assert out.stage != "clarify"
    assert client.chat.completions.calls == 1


@requires_db
def test_ask_pipeline_l1_blocks_dangerous_sql(metadata):
    client = _FakeClient(
        [
            '{"sql":"DELETE FROM ads_cust_info_d","rationale":"坏","uses_cte":false}'
        ]
    )
    out = ask(
        "删除客户",
        metadata=metadata,
        client=client,
        include_values=False,
        max_few_shots=0,
    )
    assert not out.ok
    assert out.degraded
    assert out.stage == "l1"
    assert "L1" in out.message
    assert client.chat.completions.calls == 1


@requires_db
def test_ask_pipeline_generate_failure(metadata):
    # generate_sql retries once on JsonParseError; both attempts must fail.
    # (_FakeClient falls back to SELECT 1 when the queue is empty — avoid that.)
    client = _FakeClient(["not-a-json-payload", "still-not-json"])
    out = ask(
        "客户数量",
        metadata=metadata,
        client=client,
        include_values=False,
        max_few_shots=0,
    )
    assert not out.ok
    assert out.degraded
    assert out.stage == "generate"
    assert "SQL 生成失败" in out.message
    assert client.chat.completions.calls == 2


@requires_db
def test_ask_pipeline_l2_degrades_after_failed_correction(metadata):
    # L1-ok (known column) but EXPLAIN fails (unknown function); correction still bad.
    client = _FakeClient(
        [
            '{"sql":"SELECT foo(cust_age) FROM ads_cust_info_d",'
            '"rationale":"坏函数","uses_cte":false}',
            '{"sql":"SELECT bar(cust_age) FROM ads_cust_info_d",'
            '"rationale":"仍坏","uses_cte":false}',
        ]
    )
    out = ask(
        "客户年龄",
        metadata=metadata,
        client=client,
        include_values=False,
        max_few_shots=0,
    )
    assert not out.ok
    assert out.degraded
    assert out.stage == "l2"
    assert client.chat.completions.calls == 2  # generate + one correction


@requires_db
def test_ask_pipeline_l2_corrects_once_then_succeeds(metadata):
    # First SQL: L1 passes, EXPLAIN fails → 1-Shot correction returns executable SQL.
    client = _FakeClient(
        [
            '{"sql":"SELECT foo(cust_age) FROM ads_cust_info_d",'
            '"rationale":"坏函数","uses_cte":false}',
            '{"sql":"SELECT COUNT(*) AS cnt FROM ads_cust_info_d WHERE cust_age > 30",'
            '"rationale":"修正","uses_cte":false}',
        ]
    )
    out = ask(
        "年龄大于30的客户有多少",
        metadata=metadata,
        client=client,
        include_values=False,
        max_few_shots=0,
    )
    assert out.ok, out.message
    assert out.corrected
    assert out.stage == "done"
    assert out.columns == ["cnt"]
    assert client.chat.completions.calls == 2


@requires_db
def test_ask_pipeline_probe_on_impossible_filter(metadata):
    # Impossible age filter → 0 rows / zero count → probe triggers.
    client = _FakeClient(
        [
            '{"sql":"SELECT COUNT(*) AS cnt FROM ads_cust_info_d WHERE cust_age > 200",'
            '"rationale":"极端年龄","uses_cte":false}'
        ]
    )
    out = ask(
        "200岁以上的女性客户有多少",
        metadata=metadata,
        client=client,
        include_values=False,
        max_few_shots=0,
    )
    assert out.ok, out.message
    assert out.stage == "done"
    assert out.extras.get("probe_code") in {"zero_count", "empty_result"}
    assert out.probe_message
    assert out.probe_suggestions
    assert any("200" in s or "年龄" in s or "岁" in s for s in out.probe_suggestions)
    assert any("性别" in s for s in out.probe_suggestions)
    assert client.chat.completions.calls == 1


# ---------------------------------------------------------------------------
# Live end-to-end
# ---------------------------------------------------------------------------


@requires_db
@requires_live_llm
def test_live_ask_simple_customer_count(metadata):
    out = ask(
        "有多少年龄大于30岁的女性客户？",
        metadata=metadata,
        max_few_shots=2,
    )
    assert out.sql
    assert out.stage in {"done", "l1", "l2", "execute", "generate"}
    if out.ok:
        assert out.stage == "done"
        assert "ads_cust_info_d" in out.sql
        upper = f" {out.sql.upper()} "
        for banned in ("DELETE ", "DROP ", "UPDATE ", "INSERT ", "TRUNCATE "):
            assert banned not in upper
        assert out.row_count >= 1 or out.probe_message
    else:
        assert out.degraded
        assert out.message
