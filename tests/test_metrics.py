"""Tests for metric-tree load and prune-note injection (accuracy step 3)."""

from __future__ import annotations

from querypilot.metadata_engine import SchemaPruner, load_metadata, load_metrics, metrics_for_tables


def test_load_metrics_has_core_formulas():
    metrics = load_metrics()
    ids = {m.id for m in metrics}
    assert "total_aset" in ids
    assert "avg_daily_aset" in ids
    assert "product_type_levels" in ids
    total = next(m for m in metrics if m.id == "total_aset")
    assert "nm_tot_aset" in total.formula
    assert "fc_pur_aset" in total.formula


def test_bundle_loads_metrics():
    md = load_metadata(load_db_codes=False)
    assert len(md.metrics) >= 5


def test_metrics_for_tables_filters_by_intersection():
    metrics = load_metrics()
    hit = metrics_for_tables(metrics, ["dws_cust_aset_d", "ads_cust_info_d"])
    ids = {m.id for m in hit}
    assert "total_aset" in ids
    assert "age_bucket_labels" in ids
    assert "trade_amt" not in ids


def test_prune_notes_include_metric_koujing():
    md = load_metadata(load_db_codes=False)
    pruned = SchemaPruner(md).prune(
        "不同客户年龄段资产分布情况，如下规则：1、小于30 2、大于等于30，小于50"
    )
    text = "\n".join(pruned.notes)
    assert "总资产" in text or "nm_tot_aset" in text
    assert "[60,)" in text or "年龄段" in text
    assert "20260331" in text


def test_prune_product_notes_distinguish_type_levels():
    md = load_metadata(load_db_codes=False)
    pruned = SchemaPruner(md).prune(
        "查询科创板交易量大于25万的客户营业部分布情况"
    )
    text = "\n".join(pruned.notes) + "\n" + pruned.format_for_prompt(md, include_values=False)
    assert "prdt_type_name" in text
    assert "科创板" in text or "二级" in text
