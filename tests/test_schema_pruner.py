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
    assert "dim_public" not in result.tables
    assert "性别" in result.search_text


def test_prune_asset_query_expands_join(pruner):
    result = pruner.prune("总资产超过100万的客户有多少")
    assert "dws_cust_aset_d" in result.seed_tables
    assert "ads_cust_info_d" in result.seed_tables
    assert "dws_cust_aset_d" in result.tables
    assert "ads_cust_info_d" in result.tables
    assert result.join_plan.join_clauses
    assert all("pty_id" in c for c in result.join_plan.join_clauses)
    assert all("data_dt" not in c for c in result.join_plan.join_clauses)


def test_prune_trade_and_product(pruner):
    result = pruner.prune("买过基金产品的客户买入交易额")
    assert "dwd_cust_tran_d" in result.seed_tables or "dwd_cust_tran_d" in result.tables
    assert "dim_product" in result.seed_tables or "dim_product" in result.tables


def test_prune_gold_q5_trade_and_named_securities(pruner):
    """交易过证券 + 持有证券 → must allow dim_product (was L1 Table not allowed)."""
    result = pruner.prune("26年Q1交易过招商银行，且26年Q1末普通账户持有中国平安的客户")
    assert "dwd_cust_tran_d" in result.tables
    assert "dim_product" in result.tables
    assert "dwd_cust_hold_d" in result.tables


def test_prune_gold_q6_avg_asset_and_trade_volume(pruner):
    """产品大类 + 交易量：tran must survive top_k crowding by asset/hold hubs."""
    result = pruner.prune(
        "26年Q1日均资产大于30万的客户，股票交易量大于10万的，其持有的产品属于哪些产品大类"
    )
    assert "dim_product" in result.tables
    assert "dwd_cust_tran_d" in result.tables
    assert "dws_cust_aset_d" in result.tables
    assert "dwd_cust_hold_d" in result.tables


def test_prune_gold_q7_board_trade_and_branch(pruner):
    """科创板交易量 → dim_product + dwd_cust_tran_d (board type lives on product dim)."""
    result = pruner.prune(
        "查询26年1月10日到26年2月15日期间，科创板交易量大于25万的客户营业部分布情况"
    )
    assert "dim_product" in result.tables
    assert "dwd_cust_tran_d" in result.tables
    assert "dim_branch" in result.tables or "ads_cust_info_d" in result.tables


def test_prune_gold_q3_pnl_includes_fin_and_aset(pruner):
    """盈亏问句必须召回资金流动表与资产表（无独立 pnl 表）。"""
    result = pruner.prune(
        "钻石卡男性客户，年龄大于40岁，持有比亚迪市值超过1000元，他在26年Q1的盈亏情况"
    )
    assert "dws_cust_fin_d" in result.tables
    assert "dws_cust_aset_d" in result.tables
    assert "dwd_cust_hold_d" in result.tables
    assert "dim_product" in result.tables


def test_prune_holdings(pruner):
    result = pruner.prune("客户持仓市值排名")
    assert "dwd_cust_hold_d" in result.seed_tables
    assert "dwd_cust_hold_d" in result.tables


def test_prune_branch(pruner):
    result = pruner.prune("各营业部的客户数量")
    assert "dim_branch" in result.seed_tables or "ads_cust_info_d" in result.seed_tables


def test_prune_branch_customer_injects_ads_hub(pruner):
    """Extra2 FE09: 分公司+客户 must keep ads hub (not dim_branch-only allowlist)."""
    result = pruner.prune("所属分公司为南京分公司的客户有多少人？")
    assert "dim_branch" in result.tables
    assert "ads_cust_info_d" in result.tables
    assert "ads_cust_info_d" in result.seed_tables


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
    assert "data_dt" in text  # notes mention date misalignment
    assert "建议 Join" in text
    # Join hints must use business keys only (notes may still mention data_dt)
    join_section = text.split("建议 Join:")[-1]
    assert "pty_id" in join_section
    assert "data_dt" not in join_section


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
