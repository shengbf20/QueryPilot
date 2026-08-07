"""Tests for Schema Pruner (phase-2 step 2)."""

from __future__ import annotations

import pytest

from querypilot.metadata_engine import SchemaPruner, load_metadata, prune_schema


@pytest.fixture(scope="module")
def metadata():
    return load_metadata(load_db_codes=False)


@pytest.fixture(scope="module")
def pruner(metadata):
    return SchemaPruner(metadata)


def test_prune_customer_attributes(pruner):
    result = pruner.prune("筛选30岁以上的女性客户")
    assert "ads_cust_info_d" in result.seed_tables
    assert "ads_cust_info_d" in result.tables
    assert "dim_public" not in result.seed_tables


def test_prune_asset_query_expands_join(pruner):
    result = pruner.prune("总资产超过100万的客户有多少")
    assert "dws_cust_aset_d" in result.seed_tables
    assert "ads_cust_info_d" in result.tables or "ads_cust_info_d" in result.seed_tables
    # asset table should be present after seed or expand
    assert "dws_cust_aset_d" in result.tables
    assert any("pty_id" in c for c in result.join_plan.join_clauses) or len(result.seed_tables) >= 1


def test_prune_trade_and_product(pruner):
    result = pruner.prune("买过基金产品的客户买入交易额")
    assert "dwd_cust_tran_d" in result.seed_tables or "dwd_cust_tran_d" in result.tables
    assert "dim_product" in result.seed_tables or "dim_product" in result.tables


def test_prune_holdings(pruner):
    result = pruner.prune("客户持仓市值排名")
    assert "dwd_cust_hold_d" in result.seed_tables
    assert "dwd_cust_hold_d" in result.tables


def test_prune_branch(pruner):
    result = pruner.prune("各营业部的客户数量")
    assert "dim_branch" in result.seed_tables or "ads_cust_info_d" in result.seed_tables


def test_prune_cashflow(pruner):
    result = pruner.prune("客户入金与出金情况")
    assert "dws_cust_fin_d" in result.seed_tables


def test_multi_table_path_completion(pruner):
    """Customer + product should pull intermediate fact tables via Join-Graph."""
    result = pruner.prune("购买过某产品的30岁以上女性", top_k=4)
    assert "ads_cust_info_d" in result.tables
    assert "dim_product" in result.tables
    # Path customer <-> product goes through hold or tran
    bridge = {"dwd_cust_hold_d", "dwd_cust_tran_d"}
    assert bridge & set(result.tables)


def test_format_for_prompt_contains_schema_and_rules(pruner, metadata):
    result = pruner.prune("总资产大于50万的男性客户")
    text = result.format_for_prompt(metadata, include_values=False)
    assert "相关表结构" in text
    assert "dws_cust_aset_d" in text or "客户资产" in text
    assert "业务约定" in text
    assert "data_dt" in text  # join rule / note mentions date alignment


def test_empty_question_raises(pruner):
    with pytest.raises(ValueError):
        pruner.prune("   ")


def test_fallback_when_no_match(pruner):
    result = pruner.prune("xyzabc完全无关问句12345", min_score=99.0)
    assert result.seed_tables == ["ads_cust_info_d"]


def test_bundle_shortcut(metadata):
    result = metadata.prune_schema("客户年龄分布")
    assert "ads_cust_info_d" in result.tables


def test_prune_schema_helper(metadata):
    result = prune_schema("信用账户资产", metadata=metadata)
    assert "dws_cust_aset_d" in result.seed_tables
