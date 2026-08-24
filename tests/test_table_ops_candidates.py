"""A3 键候选 / A4 枚举候选生成器测试（含对手写元数据的逆向验证）。"""

from __future__ import annotations

import pytest

from querypilot.config import get_settings
from querypilot.metadata_engine import load_join_graph, load_metadata
from querypilot.table_ops.candidates import (
    ColumnProfile,
    build_key_registry,
    _classify,
    _enum_classify,
    enum_candidates,
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


# ---------- A4 枚举候选 ----------


def test_enum_classify_thresholds():
    # 全量命中且 >= 2 个值才 high；单值平凡包含只报 medium
    assert _enum_classify(1.0, 2) == "high"
    assert _enum_classify(1.0, 1) == "medium"
    assert _enum_classify(0.9, 5) == "medium"


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
class TestEnumReverseCheck:
    """机器从裸表跑出的枚举候选应覆盖人工写的全部字典/枚举配置。"""

    @pytest.mark.parametrize(
        "code_type_id",
        ["100", "200", "500", "600", "700"],
    )
    def test_rediscovers_dim_public_code_types(self, metadata, code_type_id):
        """value_descriptors.code_types 的 5 个 column_refs 应全部被机器复原。"""
        refs = metadata.values.code_types[code_type_id].column_refs
        assert refs, f"{code_type_id} 无 column_refs"
        for ref in refs:
            cands = enum_candidates(ref.table, metadata=metadata)
            match = [
                c
                for c in cands
                if c.column == ref.column and c.kind == "dict" and c.match_key == code_type_id
            ]
            assert match, f"{code_type_id}: {ref.table}.{ref.column} 未命中字典候选"
            best = max(match, key=lambda c: c.containment)
            assert best.confidence == "high", f"{code_type_id}: {best.confidence}"
            assert best.suggested_column == {
                "code_type_id": code_type_id,
                "lookup": "dim_public",
            }
            # 含义应从 dim_public 解析出来（如性别 5000002=男）
            assert all(v for v in best.value_meanings.values())

    @pytest.mark.parametrize(
        "table,column,enum_ref,expect_high",
        [
            ("dwd_cust_tran_d", "sys_source", "sys_source", True),
            ("dwd_cust_hold_d", "sys_source", "sys_source", True),
            ("dws_cust_fin_d", "sys_source", "sys_source", True),
            ("dwd_cust_hold_d", "ccy", "ccy", True),
            ("dwd_cust_tran_d", "ccy", "ccy", False),  # 单值平凡包含 → medium
            ("ads_cust_info_d", "cust_type", "cust_type", False),  # 单值 → medium
        ],
    )
    def test_rediscovers_static_enum_refs(self, metadata, table, column, enum_ref, expect_high):
        cands = enum_candidates(table, metadata=metadata)
        match = [
            c for c in cands if c.column == column and c.kind == "static" and c.match_key == enum_ref
        ]
        assert match, f"{table}.{column} 未命中静态枚举 {enum_ref}"
        best = max(match, key=lambda c: c.containment)
        assert (best.confidence == "high") is expect_high
        assert best.suggested_column == {"enum_ref": enum_ref}

    def test_new_enum_skeleton_for_mgr_title(self, metadata):
        """dim_mgr_info.mgr_title（3 个值、无字典）应产出待填含义的新枚举骨架。"""
        cands = enum_candidates("dim_mgr_info", metadata=metadata)
        match = [c for c in cands if c.column == "mgr_title"]
        assert match and match[0].kind == "new"
        c = match[0]
        assert c.confidence == "medium"
        assert set(c.value_meanings) == {"VP", "高级经理", "经理"}
        assert all(m == "" for m in c.value_meanings.values())
        assert c.suggested_column == {
            "enum_values": {"VP": "", "高级经理": "", "经理": ""}
        }

    def test_no_dict_false_positive_on_text_columns(self, metadata):
        """自由文本/维度/键/日期列不应产生 dict/static 候选。

        「new」候选允许出现（如 prov_name/city_name）——机械层无法判断
        自释义文本是否需要字典，交由问卷 Q6 人工确认，默认 medium。
        """
        cands = enum_candidates("ads_cust_info_d", metadata=metadata)
        no_dict = {"prov_name", "city_name", "name", "org_id", "pty_id", "data_dt"}
        for c in cands:
            if c.column in no_dict:
                assert c.kind == "new", f"{c.column} 误报 {c.kind} 候选"
