"""Tests for Prompt assembly + SQL generator (phase-2 step 3)."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from querypilot.agent import (
    FewShotExample,
    SqlGenerationError,
    build_prompt,
    generate_sql,
    generate_sql_from_prompt,
    load_few_shots,
    parse_sql_payload,
    select_few_shots,
)
from querypilot.agent.prompt import SYSTEM_PROMPT
from querypilot.config import get_settings
from querypilot.db import explain
from querypilot.llm.chat import JsonParseError
from querypilot.metadata_engine import SchemaPruner, load_metadata

# JOIN ... ON <cond> — stop at next clause keyword (allows WHERE data_dt filters).
_JOIN_ON_RE = re.compile(
    r"\bJOIN\b.+?\bON\b\s+(.+?)(?=\b(?:INNER|LEFT|RIGHT|FULL|CROSS|JOIN|WHERE|GROUP|ORDER|LIMIT|HAVING|UNION)\b|$)",
    re.IGNORECASE | re.DOTALL,
)


def _join_on_fragments(sql: str) -> list[str]:
    return [m.group(1).strip() for m in _JOIN_ON_RE.finditer(sql)]


def _assert_joins_without_data_dt(sql: str) -> None:
    fragments = _join_on_fragments(sql)
    for on_expr in fragments:
        assert "data_dt" not in on_expr.lower(), (
            f"data_dt must not appear in JOIN ON conditions:\n{on_expr}\nSQL:\n{sql}"
        )


def _api_key_ready() -> bool:
    key = get_settings().deepseek_api_key
    return bool(key) and not key.startswith("sk-your")


requires_live_llm = pytest.mark.skipif(
    not _api_key_ready(),
    reason="DEEPSEEK_API_KEY not set (or still placeholder in .env)",
)


@pytest.fixture(scope="module")
def metadata():
    return load_metadata(load_db_codes=True)


@pytest.fixture(scope="module")
def pruner(metadata):
    return SchemaPruner(metadata)


# ---------------------------------------------------------------------------
# Few-shot + prompt (no LLM)
# ---------------------------------------------------------------------------


def test_system_prompt_hard_rules():
    """Lock SYSTEM_PROMPT business rules (not only identity with build_prompt)."""
    assert "pty_id" in SYSTEM_PROMPT
    assert "org_id" in SYSTEM_PROMPT
    assert "data_dt" in SYSTEM_PROMPT
    assert "不要把不同表的 data_dt 作为 Join 条件" in SYSTEM_PROMPT
    assert "code_type_id" in SYSTEM_PROMPT
    assert "CTE" in SYSTEM_PROMPT or "WITH" in SYSTEM_PROMPT
    assert "JSON" in SYSTEM_PROMPT or "json" in SYSTEM_PROMPT
    # Step-2 projection / product / metric guardrails
    assert "COUNT" in SYSTEM_PROMPT
    assert "dim_product" in SYSTEM_PROMPT
    assert "prdt_name" in SYSTEM_PROMPT
    assert "nm_tot_aset" in SYSTEM_PROMPT and "fc_pur_aset" in SYSTEM_PROMPT
    assert "buy_amt" in SYSTEM_PROMPT and "sell_amt" in SYSTEM_PROMPT
    assert "city_name" in SYSTEM_PROMPT
    assert "YYYYMMDD" in SYSTEM_PROMPT
    assert "MAX(data_dt)" in SYSTEM_PROMPT or "MAX" in SYSTEM_PROMPT
    assert "[60,)" in SYSTEM_PROMPT
    assert "prdt_type_name" in SYSTEM_PROMPT
    assert "PT040000" in SYSTEM_PROMPT
    assert "PT050000" in SYSTEM_PROMPT
    assert "开放式基金" in SYSTEM_PROMPT
    assert "HAVING" in SYSTEM_PROMPT
    assert "盈亏" in SYSTEM_PROMPT
    assert "aset_pft" in SYSTEM_PROMPT
    assert "dws_cust_fin_d" in SYSTEM_PROMPT
    # P1: dict literal / branch projection / asset ownership / no physical tran_amt
    assert "7000032" in SYSTEM_PROMPT
    assert "非公职" in SYSTEM_PROMPT
    assert "只输出 pty_id" in SYSTEM_PROMPT
    assert "不要加 up_org_name" in SYSTEM_PROMPT
    assert "dws_cust_aset_d" in SYSTEM_PROMPT
    assert "trade_amt" in SYSTEM_PROMPT
    assert "tran_amt" in SYSTEM_PROMPT  # banned as physical column


def test_load_few_shots_has_examples():
    shots = load_few_shots()
    assert len(shots) >= 7
    assert all(s.question and s.sql for s in shots)
    female = next(s for s in shots if "女性" in s.question)
    assert "5000003" in female.sql
    assert any("产品大类" in s.question for s in shots)
    assert any("科创板" in s.question or "科创板" in s.sql for s in shots)
    assert any("盈亏" in s.question for s in shots)


def test_few_shot_asset_example_joins_on_pty_id_not_data_dt():
    shots = load_few_shots()
    asset = next(s for s in shots if "总资产超过" in s.question)
    assert "pty_id" in asset.sql
    assert "JOIN" in asset.sql.upper()
    assert "fc_pur_aset" in asset.sql
    _assert_joins_without_data_dt(asset.sql)


def test_select_few_shots_ranks_by_overlap():
    shots = load_few_shots()
    q = "查询26年1月10日到26年2月15日期间，科创板交易量大于25万的客户营业部分布情况"
    picked = select_few_shots(q, shots, max_few_shots=2)
    assert len(picked) == 2
    assert picked[0].question == q
    assert "科创板" in picked[0].sql
    assert "up_org_name" in picked[0].sql
    assert "trade_amt" in picked[0].sql


def test_exact_few_shot_covers_official_branch_and_geo():
    shots = load_few_shots()
    from querypilot.agent.prompt import find_exact_few_shot

    board = find_exact_few_shot(
        "查询26年1月10日到26年2月15日期间，科创板交易量大于25万的客户营业部分布情况",
        shots,
    )
    assert board is not None
    assert "trade_amt" in board.sql
    geo = find_exact_few_shot("分公司和营业部的客户省份分布统计", shots)
    assert geo is not None
    assert "prov_name" in geo.sql and "up_org_name" in geo.sql


def test_select_few_shots_prefers_product_category_example():
    shots = load_few_shots()
    q = "26年Q1日均资产大于30万的客户，股票交易量大于10万的，其持有的产品属于哪些产品大类"
    picked = select_few_shots(q, shots, max_few_shots=2)
    assert picked[0].question == q
    assert "up_prdt_type_name" in picked[0].sql


def test_select_few_shots_prefers_period_pnl_example():
    shots = load_few_shots()
    q = "钻石卡男性客户，年龄大于40岁，持有比亚迪市值超过1000元，他在26年Q1的盈亏情况"
    picked = select_few_shots(q, shots, max_few_shots=2)
    assert picked[0].question == q
    assert "aset_pft" in picked[0].sql
    assert "dws_cust_fin_d" in picked[0].sql
    assert "bgn_aset" in picked[0].sql


def test_generate_sql_exact_few_shot_skips_llm(metadata, pruner):
    """HITL exact match returns reflux SQL without calling the LLM client."""
    q = "钻石卡男性客户，年龄大于40岁，持有比亚迪市值超过1000元，他在26年Q1的盈亏情况"
    pruned = pruner.prune(q)

    class _Boom:
        def chat(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("LLM must not be called on exact few-shot hit")

    result = generate_sql(
        q,
        metadata=metadata,
        pruned=pruned,
        include_values=False,
        client=_Boom(),  # type: ignore[arg-type]
    )
    assert result.raw.get("source") == "few_shot_exact"
    assert "aset_pft" in result.sql
    assert "dws_cust_fin_d" in result.sql


def test_build_prompt_contains_schema_rules_and_shots(metadata, pruner):
    question = "总资产超过100万的客户有多少"
    pruned = pruner.prune(question)
    prompt = build_prompt(question, pruned, metadata, max_few_shots=2)

    assert prompt.system == SYSTEM_PROMPT
    assert "用户问题" in prompt.user
    assert question in prompt.user
    assert "相关表结构" in prompt.user
    assert "dws_cust_aset_d" in prompt.user or "客户资产" in prompt.user
    assert "业务约定" in prompt.user
    assert "pty_id" in prompt.user
    assert "参考示例" in prompt.user
    assert prompt.few_shot_count == 2
    assert "ads_cust_info_d" in prompt.tables or "dws_cust_aset_d" in prompt.tables
    assert "CTE" in prompt.system or "WITH" in prompt.system
    assert "json" in prompt.system.lower() or "JSON" in prompt.system

    assert "建议 Join" in prompt.user
    join_section = prompt.user.split("建议 Join:")[-1].split("参考示例")[0]
    assert "pty_id" in join_section
    assert "data_dt" not in join_section

    messages = prompt.as_messages()
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_build_prompt_respects_max_few_shots(metadata, pruner):
    pruned = pruner.prune("客户年龄分布")
    prompt = build_prompt("客户年龄分布", pruned, metadata, max_few_shots=1)
    assert prompt.few_shot_count == 1


def test_build_prompt_injects_ranked_board_shot(metadata, pruner):
    question = "查询26年1月10日到26年2月15日期间，科创板交易量大于25万的客户营业部分布情况"
    pruned = pruner.prune(question)
    prompt = build_prompt(question, pruned, metadata, max_few_shots=3)
    assert "科创板" in prompt.user
    assert "trade_amt" in prompt.user or "buy_amt" in prompt.user


def test_build_prompt_can_disable_few_shots(metadata, pruner):
    pruned = pruner.prune("客户年龄分布")
    prompt = build_prompt("客户年龄分布", pruned, metadata, few_shots=[], max_few_shots=3)
    assert prompt.few_shot_count == 0
    assert "参考示例" not in prompt.user


def test_build_prompt_empty_question_raises(metadata, pruner):
    pruned = pruner.prune("客户年龄")
    with pytest.raises(ValueError):
        build_prompt("  ", pruned, metadata)


def test_build_prompt_includes_enum_values_when_available(metadata, pruner):
    question = "女性客户数量"
    pruned = pruner.prune(question)
    assert "ads_cust_info_d" in pruned.tables
    prompt = build_prompt(question, pruned, metadata, few_shots=[], include_values=True)
    assert "gender_cd" in prompt.user
    assert "5000003" in prompt.user


# ---------------------------------------------------------------------------
# parse_sql_payload (no LLM)
# ---------------------------------------------------------------------------


def test_parse_sql_payload_ok():
    sql, rationale, uses_cte = parse_sql_payload(
        {"sql": "SELECT 1", "rationale": "ok", "uses_cte": False}
    )
    assert sql == "SELECT 1"
    assert rationale == "ok"
    assert uses_cte is False


def test_parse_sql_payload_detects_with():
    sql, _, uses_cte = parse_sql_payload({"sql": "WITH x AS (SELECT 1) SELECT * FROM x"})
    assert uses_cte is True
    assert sql.startswith("WITH")


def test_parse_sql_payload_strips_sql_fence():
    sql, _, _ = parse_sql_payload({"sql": "```sql\nSELECT 1\n```"})
    assert sql == "SELECT 1"


def test_parse_sql_payload_missing_sql():
    with pytest.raises(SqlGenerationError):
        parse_sql_payload({"rationale": "no sql"})


def test_parse_sql_payload_empty_sql():
    with pytest.raises(SqlGenerationError):
        parse_sql_payload({"sql": "  "})


# ---------------------------------------------------------------------------
# generate_sql with fake client (no network)
# ---------------------------------------------------------------------------


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self._content = content
        self.last_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.last_kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))],
            model=kwargs.get("model", "fake-model"),
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(content))


def test_generate_sql_from_prompt_with_fake_client(metadata, pruner):
    pruned = pruner.prune("客户数量")
    prompt = build_prompt("客户数量", pruned, metadata, few_shots=[])
    client = _FakeClient(
        '{"sql":"SELECT COUNT(*) AS cnt FROM ads_cust_info_d","rationale":"单表计数","uses_cte":false}'
    )
    result = generate_sql_from_prompt(prompt, client=client)
    assert "ads_cust_info_d" in result.sql
    assert result.rationale == "单表计数"
    assert result.uses_cte is False
    assert result.prompt is prompt
    kwargs = client.chat.completions.last_kwargs
    assert kwargs is not None
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["messages"][0]["content"] == SYSTEM_PROMPT


def test_generate_sql_retries_once_on_json_parse_error(metadata, pruner):
    pruned = pruner.prune("客户数量")
    prompt = build_prompt("客户数量", pruned, metadata, few_shots=[])
    calls = {"n": 0}

    def flaky_generate_json(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise JsonParseError("Invalid JSON from model: bad control char")
        return {
            "sql": "SELECT COUNT(*) AS cnt FROM ads_cust_info_d",
            "rationale": "retry ok",
            "uses_cte": False,
        }

    with patch(
        "querypilot.agent.sql_generator.generate_json",
        side_effect=flaky_generate_json,
    ):
        result = generate_sql_from_prompt(prompt)
    assert calls["n"] == 2
    assert "ads_cust_info_d" in result.sql
    assert result.rationale == "retry ok"


def test_generate_sql_allow_exact_few_shot_false_calls_llm(metadata, pruner):
    """Extra generalization eval must not short-circuit on exact few-shot match."""
    q = "钻石卡男性客户，年龄大于40岁，持有比亚迪市值超过1000元，他在26年Q1的盈亏情况"
    pruned = pruner.prune(q)
    client = _FakeClient(
        '{"sql":"SELECT 1 AS n","rationale":"forced llm","uses_cte":false}'
    )
    result = generate_sql(
        q,
        metadata=metadata,
        pruned=pruned,
        include_values=False,
        client=client,  # type: ignore[arg-type]
        allow_exact_few_shot=False,
    )
    assert client.chat.completions.last_kwargs is not None
    assert result.raw.get("source") != "few_shot_exact"
    assert "SELECT 1" in result.sql


def test_generate_sql_end_to_end_with_fake_client(metadata):
    client = _FakeClient(
        '{"sql":"SELECT COUNT(*) AS cnt FROM ads_cust_info_d WHERE cust_age > 30",'
        '"rationale":"过滤年龄","uses_cte":false}'
    )
    result = generate_sql(
        "年龄大于30的客户有多少",
        metadata=metadata,
        include_values=False,
        few_shots=[FewShotExample(question="q", sql="SELECT 1")],
        max_few_shots=1,
        client=client,
    )
    assert "cust_age" in result.sql
    assert result.pruned is not None
    assert "ads_cust_info_d" in result.pruned.tables


# ---------------------------------------------------------------------------
# Live LLM evaluation (same path as production)
# ---------------------------------------------------------------------------


@requires_live_llm
def test_live_generate_sql_simple_customer_count(metadata):
    result = generate_sql(
        "有多少年龄大于30岁的女性客户？",
        metadata=metadata,
        max_few_shots=2,
        max_tokens=800,
    )
    assert result.sql
    upper = result.sql.upper()
    assert "SELECT" in upper or upper.lstrip().startswith("WITH")
    assert "ads_cust_info_d" in result.sql
    assert "cust_age" in result.sql.lower()
    assert "gender_cd" in result.sql.lower()
    assert "5000003" in result.sql
    assert "INSERT" not in upper and "DROP" not in upper and "DELETE" not in upper
    _assert_joins_without_data_dt(result.sql)

    plan = explain(result.sql)
    assert plan.ok, f"EXPLAIN failed: {plan.error}\nSQL:\n{result.sql}"


@requires_live_llm
def test_live_generate_sql_asset_join_uses_cte_or_join(metadata):
    result = generate_sql(
        "总资产超过100万的客户有多少人？",
        metadata=metadata,
        max_few_shots=2,
        max_tokens=1000,
    )
    assert "dws_cust_aset_d" in result.sql or "nm_tot_aset" in result.sql
    assert "ads_cust_info_d" in result.sql or "pty_id" in result.sql
    upper = result.sql.upper()
    assert "SELECT" in upper
    # Multi-table filter + aggregation should use CTE (Step 5 / SYSTEM rule 7)
    assert upper.lstrip().startswith("WITH") or result.uses_cte
    _assert_joins_without_data_dt(result.sql)

    plan = explain(result.sql)
    assert plan.ok, f"EXPLAIN failed: {plan.error}\nSQL:\n{result.sql}"


@requires_live_llm
def test_live_generate_sql_trade_product(metadata):
    result = generate_sql(
        "买入交易额合计是多少？",
        metadata=metadata,
        max_few_shots=2,
        max_tokens=800,
    )
    assert "dwd_cust_tran_d" in result.sql or "buy_amt" in result.sql
    _assert_joins_without_data_dt(result.sql)
    plan = explain(result.sql)
    assert plan.ok, f"EXPLAIN failed: {plan.error}\nSQL:\n{result.sql}"


def test_assert_joins_without_data_dt_helper():
    """Guard the static checker itself (allows WHERE data_dt, blocks JOIN ON data_dt)."""
    ok_sql = """
    WITH latest AS (
      SELECT pty_id, nm_tot_aset FROM dws_cust_aset_d
      WHERE data_dt = (SELECT MAX(data_dt) FROM dws_cust_aset_d)
    )
    SELECT COUNT(*) FROM ads_cust_info_d c
    JOIN latest a ON c.pty_id = a.pty_id
    """
    _assert_joins_without_data_dt(ok_sql)

    bad_sql = """
    SELECT COUNT(*) FROM ads_cust_info_d c
    JOIN dws_cust_aset_d a ON c.pty_id = a.pty_id AND c.data_dt = a.data_dt
    """
    with pytest.raises(AssertionError, match="data_dt"):
        _assert_joins_without_data_dt(bad_sql)
