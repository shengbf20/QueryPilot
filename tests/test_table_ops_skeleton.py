"""A2 YAML 骨架生成测试（含对手写元数据的逆向验证）。

核心命题：手写 YAML 的全部「机械可推导字段」（layer/列名/类型/主键/
code_type_id/enum_ref/enum_values 键集/format）应被骨架完整复原；
语义字段（alias/description/usage/aliases/枚举含义）骨架必须留空。
"""

from __future__ import annotations

import pytest
import yaml

from querypilot.config import get_settings
from querypilot.metadata_engine import load_metadata
from querypilot.metadata_engine.loader import _parse_table
from querypilot.table_ops.discover import build_skeleton, render_skeleton_yaml

SINGLE_COL_PK_TABLES = ["ads_cust_info_d", "dim_product", "dim_mgr_info"]
# 「快照日是否入主键」属业务口径（dim_branch 入、ads 不入），机械不可判定：
# 骨架只提核心唯一键，快照日交问卷 Q3
COMPOSITE_PK_TABLES = [
    "dwd_cust_hold_d",
    "dwd_cust_tran_d",
    "dws_cust_fin_d",
    "dws_cust_aset_d",
    "dim_public",
    "dim_branch",
    "dwd_cust_mgr_rel_d",
]


def _base_type(t: str) -> str:
    return t.split("(", 1)[0]


@pytest.fixture(scope="module")
def metadata():
    return load_metadata(load_db_codes=False)


def _skeleton_col(skeleton: dict, name: str) -> dict:
    return next(c for c in skeleton["columns"] if c["name"] == name)


# ---------- 逆向验证：全部 10 张表 ----------


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
@pytest.mark.parametrize("table", sorted(load_metadata(load_db_codes=False).tables))
def test_physical_fields_match_handwritten(table, metadata):
    """机械可推导字段应与手写 YAML 完全一致。"""
    skeleton = build_skeleton(table, metadata=metadata)
    meta = metadata.tables[table]

    assert skeleton["table"] == table
    assert skeleton["layer"] == meta.layer
    assert [c["name"] for c in skeleton["columns"]] == [c.name for c in meta.columns]
    for hw in meta.columns:
        sk = _skeleton_col(skeleton, hw.name)
        assert _base_type(sk["type"]) == _base_type(hw.type), hw.name
        if hw.format:
            assert sk.get("format") == hw.format, hw.name


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
@pytest.mark.parametrize("table", SINGLE_COL_PK_TABLES)
def test_single_col_pk_matches_handwritten(table, metadata):
    skeleton = build_skeleton(table, metadata=metadata)
    assert skeleton["primary_key"] == metadata.tables[table].primary_key


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
@pytest.mark.parametrize("table", COMPOSITE_PK_TABLES)
def test_composite_pk_core_key_only(table, metadata):
    """组合主键表：骨架只提核心唯一键（⊆ 声明主键），快照日/补全列交人工。"""
    skeleton = build_skeleton(table, metadata=metadata)
    declared = set(metadata.tables[table].primary_key)
    assert set(skeleton["primary_key"]) <= declared
    if not skeleton["primary_key"]:
        assert any("组合主键" in n for n in skeleton["notes"])
    elif any("快照日" in n for n in skeleton["notes"]):
        # 有快照日信号的表必须提示人工确认是否入键（如 dim_branch/dwd_cust_mgr_rel_d）
        assert any("主键是否含快照日" in n for n in skeleton["notes"])
    # 无任何信号的表（如 dim_public 的 [code]）只有核心键候选，Q3 统一确认


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
@pytest.mark.parametrize("table", sorted(load_metadata(load_db_codes=False).tables))
def test_enum_fields_match_handwritten(table, metadata):
    """手写的 code_type_id/enum_ref/enum_values 应被 A4 候选完整复原。"""
    skeleton = build_skeleton(table, metadata=metadata)
    meta = metadata.tables[table]

    for hw in meta.columns:
        sk = _skeleton_col(skeleton, hw.name)
        if hw.code_type_id:
            assert sk.get("code_type_id") == hw.code_type_id, f"{table}.{hw.name}"
            assert sk.get("lookup") == hw.lookup
        if hw.enum_ref:
            # 骨架经 A4 走 enum_ref（手写 YAML 里并排的 enum_values 是同一知识的
            # 冗余渲染，prompt 生成二选一，见 bundle.format_table_schema）
            assert sk.get("enum_ref") == hw.enum_ref, f"{table}.{hw.name}"
        elif hw.enum_values:
            assert set(sk.get("enum_values", {})) == set(hw.enum_values), f"{table}.{hw.name}"


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
@pytest.mark.parametrize("table", sorted(load_metadata(load_db_codes=False).tables))
def test_semantic_fields_left_empty(table, metadata):
    """语义字段必须留空（知识由人注入，logs/08 §3.1）。"""
    skeleton = build_skeleton(table, metadata=metadata)
    assert skeleton["alias"] == ""
    assert skeleton["description"] == ""
    assert skeleton["usage"] == []
    for c in skeleton["columns"]:
        assert c["description"] == ""
        assert c["aliases"] == []
        # 手写未配置枚举的列，骨架不得臆造 dict/static 配置（new 骨架允许）
        hw = metadata.tables[table].get_column(c["name"])
        if not hw.code_type_id:
            assert "code_type_id" not in c, f"{table}.{c['name']} 臆造字典"
        if not hw.enum_ref:
            assert "enum_ref" not in c, f"{table}.{c['name']} 臆造静态枚举"


# ---------- 结构合法性：骨架可被 loader 直接解析 ----------


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
@pytest.mark.parametrize("table", sorted(load_metadata(load_db_codes=False).tables))
def test_skeleton_round_trips_through_loader(table, metadata):
    """渲染出的 YAML 文本可被 loader._parse_table 解析（结构合法）。"""
    text = render_skeleton_yaml(table, metadata=metadata)
    meta = _parse_table(yaml.safe_load(text))
    assert meta.table == table
    assert meta.layer == metadata.tables[table].layer
    assert len(meta.columns) == len(metadata.tables[table].columns)


# ---------- 模拟域专项 ----------


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
class TestSimDomainSkeleton:
    def test_mgr_table_skeleton(self, metadata):
        sk = build_skeleton("dim_mgr_info", metadata=metadata)
        assert sk["primary_key"] == ["mgr_id"]
        title = _skeleton_col(sk, "mgr_title")
        assert set(title["enum_values"]) == {"VP", "经理", "高级经理"}
        assert all(v == "" for v in title["enum_values"].values())

    def test_rel_table_key_columns_are_not_enums(self, metadata):
        """键列（pty_id/mgr_id）不得产枚举骨架——键值域是标识符，不是待解释枚举。"""
        sk = build_skeleton("dwd_cust_mgr_rel_d", metadata=metadata)
        for name in ("pty_id", "mgr_id"):
            assert "enum_values" not in _skeleton_col(sk, name)
        assert sk["primary_key"] == ["pty_id"]  # 核心唯一键；快照日是否入键交 Q3
        assert any("20260531" in n for n in sk["notes"])  # 快照日自动入 notes

    def test_ads_snapshot_note(self, metadata):
        sk = build_skeleton("ads_cust_info_d", metadata=metadata)
        assert any("data_dt 固定为 20260531" in n for n in sk["notes"])
