"""A3 键候选生成器测试（含对 0da90af 手写元数据的逆向验证）。"""

from __future__ import annotations

import pytest

from querypilot.config import get_settings
from querypilot.metadata_engine import load_join_graph, load_metadata
from querypilot.table_ops.candidates import (
    ColumnProfile,
    build_key_registry,
    _classify,
    key_candidates,
)


@pytest.fixture(scope="module")
def metadata():
    return load_metadata(load_db_codes=False)


# ---------- 注册表（纯元数据，无需 DB） ----------


def test_registry_built_from_join_graph(metadata):
    registry = build_key_registry(metadata)
    keys = {t.column for t in registry}
    assert {"pty_id", "org_id", "prdt_id", "mgr_id", "code"} <= keys
    # 每条边双向注册：customer_to_hold → 两个方向的 pty_id 目标
    pairs = {(t.table, t.target_table) for t in registry if t.column == "pty_id"}
    assert ("ads_cust_info_d", "dwd_cust_hold_d") in pairs
    assert ("dwd_cust_hold_d", "ads_cust_info_d") in pairs
    # lookup 边携带 filter
    lookup = [t for t in registry if t.edge_type == "lookup" and t.target_table == "dim_public"]
    assert lookup and any(t.filter.get("code_type_id") == "500" for t in lookup)


# ---------- 分级与日期排除（纯函数） ----------


def test_classify_thresholds():
    # 同名命中：双重信号（名字+值域），门槛 0.70，容忍事实表孤儿行
    assert _classify(1.0, "name") == "high"
    assert _classify(0.70, "name") == "high"
    assert _classify(0.69, "name") == "medium"
    # 盲扫命中：仅值域信号，门槛 0.90，避免撞值误报
    assert _classify(0.90, "value") == "high"
    assert _classify(0.89, "value") == "medium"
    assert _classify(0.30, "value") == "medium"
    assert _classify(0.29, "value") == "low"


def test_date_column_detection():
    p = ColumnProfile(distinct_values={"20260101", "20260331"}, null_count=0, total_rows=90)
    assert p.is_date
    p2 = ColumnProfile(distinct_values={"C000000000000024"}, null_count=0, total_rows=1)
    assert not p2.is_date


# ---------- 逆向验证：模拟域（对照 0da90af 手写答案） ----------


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
class TestSimDomainReverseCheck:
    """机器从裸表跑出的候选应覆盖人工写的 3 条边。"""

    def test_rel_table_finds_both_edges(self, metadata):
        cands = key_candidates("dwd_cust_mgr_rel_d", metadata=metadata)
        by_target = {c.target_table: c for c in cands}

        # pty_id -> ads_cust_info_d（人工：rel_to_customer, fact, no_default_data_dt）
        c = by_target["ads_cust_info_d"]
        assert c.column == "pty_id" and c.target_column == "pty_id"
        assert c.confidence == "high" and c.containment == 1.0
        assert c.edge_type == "fact"
        assert "no_default_data_dt" in c.suggested_edge["rules"]

        # mgr_id -> dim_mgr_info（人工：rel_to_mgr, dimension）
        m = by_target["dim_mgr_info"]
        assert m.column == "mgr_id" and m.confidence == "high"
        assert m.edge_type == "dimension"

        # data_dt 被排除（日期列），不产生任何 data_dt 候选
        assert all(c.column != "data_dt" for c in cands)

    def test_mgr_table_finds_branch_edge(self, metadata):
        cands = key_candidates("dim_mgr_info", metadata=metadata)
        by_target = {c.target_table: c for c in cands}
        c = by_target["dim_branch"]
        assert c.column == "org_id" and c.confidence == "high" and c.containment == 1.0
        assert c.edge_type == "dimension"


# ---------- 逆向验证：全图参数化（机器应能复原全部人工边） ----------


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
@pytest.mark.parametrize(
    "edge_id",
    [
        e.id
        for e in load_join_graph().edges.values()
    ],
)
def test_machine_rediscovers_every_graph_edge(edge_id, metadata):
    """对 join_graph 每条边：在其一端表上跑候选，应发现指向另一端的 high 候选。"""
    graph = metadata.join_graph
    edge = graph.edges[edge_id]
    left_col, right_col = next(iter(edge.join.items()))

    # 选 join 键所在的一端作为"新表"视角探测
    cands = key_candidates(edge.from_table, metadata=metadata)
    match = [
        c
        for c in cands
        if c.target_table == edge.to_table
        and c.column == left_col
        and c.target_column == right_col
    ]
    if not match:
        # 反向再试（某些边从 from 侧看不到，如 customer_to_* 的 from 是 ads）
        cands = key_candidates(edge.to_table, metadata=metadata)
        match = [
            c
            for c in cands
            if c.target_table == edge.from_table
            and c.column == right_col
            and c.target_column == left_col
        ]
    assert match, f"{edge_id}: 机器未发现边 {edge.from_table}↔{edge.to_table} on {left_col}"
    best = max(match, key=lambda c: c.containment)
    assert best.confidence == "high", f"{edge_id}: 置信度不足 ({best.confidence}, {best.containment})"
