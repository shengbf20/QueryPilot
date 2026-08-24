"""新表自助接入端到端验证（服务经理域模拟表，logs/08 场景）。

验证目录扫描发现 → 元数据校验 → 剪枝 cue 命中 → Join-Graph 扩张全链路，
全程零代码改动（仅新增 YAML / CSV / import_data.py 登记）。
"""

from __future__ import annotations

import pytest

from querypilot.config import get_settings
from querypilot.metadata_engine import (
    SchemaPruner,
    discover_table_names,
    load_all_tables,
    load_metadata,
    validate_all,
)


def test_new_tables_discovered_without_code_change():
    """目录扫描自动发现两张新表。"""
    names = discover_table_names()
    assert "dim_mgr_info" in names
    assert "dwd_cust_mgr_rel_d" in names
    tables = load_all_tables()
    assert tables["dim_mgr_info"].alias == "服务经理信息表"
    assert tables["dwd_cust_mgr_rel_d"].alias == "客户服务关系表"


def test_validation_ok_with_new_tables():
    """validate_all 含 join_graph 注册一致性检查，全绿。"""
    result = validate_all()
    assert result.ok, result.errors


@pytest.fixture(scope="module")
def pruner():
    return SchemaPruner(load_metadata(load_db_codes=False))


def test_prune_manager_question_hits_new_tables(pruner):
    """服务经理问句 → 命中 cue 强制补表 + Join-Graph 扩张带出客户表。"""
    result = pruner.prune("服务经理名下有多少客户")
    assert "dwd_cust_mgr_rel_d" in result.seed_tables
    assert "dim_mgr_info" in result.seed_tables or "dim_mgr_info" in result.tables
    # 客户枢纽注入（fact 表 + 客户线索词）
    assert "ads_cust_info_d" in result.tables


def test_prune_manager_with_asset_pulls_fact_tables(pruner):
    """经理 + 资产组合问句：资产表也进上下文。"""
    result = pruner.prune("服务经理名下客户的总资产")
    assert "dws_cust_aset_d" in result.tables
    assert "dwd_cust_mgr_rel_d" in result.tables


def test_prompt_renders_new_table_schema(pruner):
    """新表 schema 进入 prompt（「相关表结构」段）。"""
    result = pruner.prune("服务经理名下有多少客户")
    md = load_metadata(load_db_codes=False)
    text = result.format_for_prompt(md, include_values=False)
    assert "服务经理信息表" in text
    assert "dwd_cust_mgr_rel_d" in text
    # Join 提示含服务关系桥接
    join_section = text.split("建议 Join:")[-1]
    assert "mgr_id" in join_section or "pty_id" in join_section


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
def test_sql_smoke_join_three_tables():
    """DB 冒烟：客户 ↔ 服务关系 ↔ 经理 三表 join 行数与模拟数据一致。"""
    import duckdb

    con = duckdb.connect(str(get_settings().db_path), read_only=True)
    try:
        cnt = con.execute(
            """
            SELECT COUNT(*)
            FROM dwd_cust_mgr_rel_d r
            JOIN ads_cust_info_d c ON r.pty_id = c.pty_id
            JOIN dim_mgr_info m ON r.mgr_id = m.mgr_id
            """
        ).fetchone()[0]
        assert cnt == 300
        top = con.execute(
            """
            SELECT m.mgr_name, COUNT(*) AS cnt
            FROM dwd_cust_mgr_rel_d r
            JOIN dim_mgr_info m ON r.mgr_id = m.mgr_id
            GROUP BY m.mgr_name
            ORDER BY cnt DESC
            LIMIT 1
            """
        ).fetchone()
        assert top is not None and top[1] > 0
    finally:
        con.close()
