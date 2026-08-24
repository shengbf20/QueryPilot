"""A1 结构自动发现测试（含对手写元数据的逆向验证）。"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from querypilot.config import get_settings
from querypilot.metadata_engine import load_metadata
from querypilot.table_ops.discover import _infer_layer, discover_table

SINGLE_COL_PK_TABLES = {"ads_cust_info_d", "dim_product", "dim_mgr_info"}


@pytest.fixture(scope="module")
def metadata():
    return load_metadata(load_db_codes=False)


# ---------- 层次推断（纯函数） ----------


@pytest.mark.parametrize(
    "table,layer",
    [
        ("dwd_cust_tran_d", "dwd"),
        ("dws_cust_aset_d", "dws"),
        ("ads_cust_info_d", "ads"),
        ("dim_public", "dim"),
        ("ods_raw_x", "ods"),
        ("cust_info", ""),
        ("", ""),
    ],
)
def test_infer_layer_by_prefix(table, layer):
    assert _infer_layer(table) == layer


# ---------- 逆向验证：全部 10 张表 ----------


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
@pytest.mark.parametrize("table", sorted(load_metadata(load_db_codes=False).tables))
def test_layer_matches_handwritten_yaml(table, metadata):
    """前缀约定推断的 layer 应与手写 YAML 一致。"""
    profile = discover_table(table)
    assert profile.suggested_layer == metadata.tables[table].layer


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
class TestPrimaryKeyReverseCheck:
    def test_single_col_pk_discovered(self, metadata):
        """声明的单列主键应出现在主键候选中（候选可多于声明，如备选唯一键）。"""
        for table in SINGLE_COL_PK_TABLES:
            meta = metadata.tables[table]
            (pk_col,) = meta.primary_key
            profile = discover_table(table)
            assert pk_col in profile.primary_key_candidates, table

    @pytest.mark.parametrize(
        "table",
        [
            "dwd_cust_hold_d",
            "dwd_cust_tran_d",
            "dws_cust_fin_d",
            "dws_cust_aset_d",
            "dim_public",
            "dim_branch",
            "dwd_cust_mgr_rel_d",
        ],
    )
    def test_composite_pk_candidates_are_subset(self, table, metadata):
        """组合主键表：发现的单列候选必须落在声明主键集合内（机械上唯一列必属键）。"""
        meta = metadata.tables[table]
        profile = discover_table(table)
        declared = set(meta.primary_key)
        for cand in profile.primary_key_candidates:
            assert cand in declared, f"{table}.{cand} 唯一却不在声明主键内"


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
class TestSimAndAdsProfiles:
    def test_ads_customer_snapshot(self):
        profile = discover_table("ads_cust_info_d")
        assert profile.row_count == 500
        # 快照特征：data_dt 常量 '20260531'，cust_type 常量 'P'
        consts = {c.name for c in profile.columns if c.is_constant}
        assert {"data_dt", "cust_type"} <= consts
        # 日期列：data_dt + birth_dt（YYYYMMDD）
        assert {"data_dt", "birth_dt"} <= set(profile.date_columns)

    def test_sim_mgr_table(self):
        profile = discover_table("dim_mgr_info")
        assert profile.row_count == 20
        # 声明主键 mgr_id 被发现；mgr_name/org_id 亦单列唯一（备选唯一键，属机械事实）
        assert "mgr_id" in profile.primary_key_candidates
        assert profile.get_column("mgr_id").is_unique
        assert not profile.get_column("mgr_title").is_unique  # 3 个职级，非键

    def test_sim_rel_table(self):
        """关系表 300 行 pty_id 全不同 → pty_id 单列唯一（声明主键 [data_dt, pty_id] 的成员）。"""
        profile = discover_table("dwd_cust_mgr_rel_d")
        assert profile.primary_key_candidates == ["pty_id"]
        assert not profile.get_column("mgr_id").is_unique  # 每经理对多客户

    def test_unknown_table_raises(self):
        with pytest.raises(ValueError, match="table not found"):
            discover_table("no_such_table")


# ---------- to_dict（A2 输入）与 CLI ----------


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
def test_to_dict_shape():
    data = discover_table("dim_mgr_info").to_dict()
    assert data["table"] == "dim_mgr_info"
    assert data["suggested_layer"] == "dim"
    assert "mgr_id" in data["primary_key_candidates"]
    col = next(c for c in data["columns"] if c["name"] == "mgr_title")
    assert col["type"] == "VARCHAR"
    assert col["is_constant"] is False and col["is_unique"] is False


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
def test_cli_json_output():
    proc = subprocess.run(
        [sys.executable, "-m", "querypilot.table_ops.discover", "dim_mgr_info", "--json"],
        capture_output=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["suggested_layer"] == "dim"
    assert any(c["name"] == "mgr_id" and c["is_unique"] for c in data["columns"])
