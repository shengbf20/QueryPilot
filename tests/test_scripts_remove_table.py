"""scripts/remove_table.py 测试：各删除目标 / 降级 / 反向核验 / CLI 守护。

自建试验床：真实库副本 + 导入风险表 CSV，用 A5 register 在元数据副本上
真实登记一遍（含 import_data.py 条目），再测 remove 的逐项撤销。
不碰仓库真实文件。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import pytest

import scripts.remove_table as rt
from querypilot.config import get_settings, ROOT_DIR
from querypilot.table_ops.register import RegistrationAnswers, register_table
from scripts.add_table import (
    ROOT,
    SCRIPT_PATH as ADD_SCRIPT_PATH,
    build_entry_text,
    infer_columns,
    insert_entry,
)

TABLE = "dwd_cust_risk_assess_d"
RISK_CSV = ROOT / "data_sim" / f"{TABLE}.csv"
RISK_COLUMNS = [
    ("data_dt", "VARCHAR"),
    ("pty_id", "VARCHAR"),
    ("risk_lvl_cd", "VARCHAR"),
    ("risk_score", "INTEGER"),
    ("assess_dt", "VARCHAR"),
    ("expire_dt", "VARCHAR"),
]
LOOKUP_EDGE = {
    "id": f"{TABLE}_to_dim_public",
    "from": TABLE,
    "to": "dim_public",
    "join": {"risk_lvl_cd": "code"},
    "type": "lookup",
    "rules": ["dim_public_lookup"],
    "filter": {"code_type_id": "400"},
}


@pytest.fixture(scope="module")
def _risk_db_path(tmp_path_factory):
    """真实库副本 + 导入风险表 CSV（模块级建一次，测试只读）。"""
    db = tmp_path_factory.mktemp("db") / "risk_test.duckdb"
    shutil.copy(get_settings().db_path, db)
    con = duckdb.connect(str(db))
    try:
        col_defs = ", ".join(f"{n} {t}" for n, t in RISK_COLUMNS)
        con.execute(f"CREATE TABLE {TABLE} ({col_defs})")
        con.execute(
            f"INSERT INTO {TABLE} SELECT * FROM read_csv(?, header = true, sample_size = -1)",
            [str(RISK_CSV)],
        )
    finally:
        con.close()
    return db


@pytest.fixture()
def script_copy(tmp_path: Path, _risk_db_path: Path) -> Path:
    """import_data.py 副本 + add_table.py 风格的自动登记条目。"""
    copy = tmp_path / "import_data.py"
    shutil.copy(ADD_SCRIPT_PATH, copy)
    insert_entry(copy, build_entry_text(TABLE, infer_columns(RISK_CSV), csv_dir=ROOT / "data_sim"))
    return copy


@pytest.fixture()
def metadata_copy(tmp_path: Path, _risk_db_path: Path) -> Path:
    """元数据副本 + A5 真实登记风险表（register 会清进程缓存）。"""
    meta = tmp_path / "metadata"
    shutil.copytree(ROOT_DIR / "metadata", meta)
    con = duckdb.connect(str(_risk_db_path), read_only=True)
    try:
        register_table(
            RegistrationAnswers(
                table=TABLE,
                alias="客户风险评估",
                description="dwd 层客户风险评估表，记录客户风险等级与评分",
                granularity="客户级",
                column_descriptions={
                    "data_dt": "数据日期",
                    "pty_id": "客户号",
                    "risk_lvl_cd": "风险等级代码",
                    "risk_score": "风险评分",
                    "assess_dt": "评估日期",
                    "expire_dt": "失效日期",
                },
                join_edges=[LOOKUP_EDGE],
                cue_words=["风险", "风险等级", "激进型"],
            ),
            metadata_dir=meta,
            con=con,
        )
    finally:
        con.close()
    return meta


# ---------- 1. import_data.py 条目删除 ----------


def test_remove_import_entry(script_copy: Path, _risk_db_path: Path):
    assert rt.import_entry_exists(script_copy.read_text(encoding="utf-8"), TABLE)
    assert rt.remove_import_entry(script_copy, TABLE)
    text = script_copy.read_text(encoding="utf-8")
    assert not rt.import_entry_exists(text, TABLE)
    # 自动登记注释行一并删除
    assert f"# --- {TABLE}" not in text
    # 其他条目不受影响
    assert '"ads_cust_info_d"' in text
    import ast

    ast.parse(text)  # 仍是合法 Python


def test_remove_import_entry_missing_is_noop(script_copy: Path):
    assert not rt.remove_import_entry(script_copy, "no_such_table")


def test_handwritten_table_needs_force(script_copy: Path):
    """原始赛题表（无自动登记注释）默认拒绝。"""
    assert rt.import_entry_exists(script_copy.read_text(encoding="utf-8"), "ads_cust_info_d")
    assert not rt.entry_is_auto_registered(script_copy.read_text(encoding="utf-8"), "ads_cust_info_d")


# ---------- 3. join_graph 删除 ----------


def test_remove_join_graph_entries(metadata_copy: Path):
    from querypilot.metadata_engine.join_graph_loader import load_join_graph

    path = metadata_copy / "join_graph.yaml"
    entry_removed, edges_removed = rt.remove_join_graph_entries(path, TABLE)
    assert entry_removed and edges_removed == 1  # ..._to_dim_public lookup 边

    graph = load_join_graph(path)
    assert TABLE not in graph.tables
    assert not any(
        e.from_table == TABLE or e.to_table == TABLE for e in graph.edges.values()
    )
    # 其他表/边不受影响
    assert "ads_cust_info_d" in graph.tables
    assert "dim_mgr_info" in graph.tables
    assert any(e.id == "rel_to_customer" for e in graph.edges.values())


# ---------- 4. pruning 删除 ----------


def test_remove_pruning_entries(metadata_copy: Path):
    from querypilot.metadata_engine.pruning_config import load_pruning_config

    path = metadata_copy / "pruning.yaml"
    fact_removed, cues_removed = rt.remove_pruning_entries(path, TABLE)
    assert fact_removed and cues_removed

    config = load_pruning_config(path)
    assert TABLE not in config.fact_tables
    assert all(t != TABLE for _, t in config.domain_seed_cues)
    # 其他表条目不受影响
    assert "dwd_cust_tran_d" in config.fact_tables
    assert any(t == "dwd_cust_tran_d" for _, t in config.domain_seed_cues)


def test_remove_pruning_flow_style_cue(metadata_copy: Path):
    """flow 风格触发词条目（`cues: [..]` 单行）也要能删。"""
    path = metadata_copy / "pruning.yaml"
    text = path.read_text(encoding="utf-8")
    assert "    table: dwd_cust_tran_d" in text  # 仓库里确实存在 flow 风格条目
    _, cues_removed = rt.remove_pruning_entries(path, "dwd_cust_tran_d")
    assert cues_removed


# ---------- 5. value_descriptors 引用删除 + 降级 ----------


def test_remove_value_descriptor_refs_demotes_empty_code_type(metadata_copy: Path):
    from querypilot.metadata_engine.value_descriptors import load_value_descriptor_config

    path = metadata_copy / "value_descriptors.yaml"
    demoted = rt.remove_value_descriptor_refs(path, TABLE)
    assert demoted == ["400"]  # 风险偏好只有这一个引用，清空后整体降级

    registry = load_value_descriptor_config(path)
    assert "400" not in registry.code_types
    assert registry.unused_code_types.get("400") == "风险偏好"
    # 其他 code_types 不受影响
    assert "100" in registry.code_types


def test_remove_value_descriptor_refs_keeps_shared_code_type(tmp_path: Path):
    """多个表共用一个 code_type 时，只删引用、条目保留。"""
    path = tmp_path / "value_descriptors.yaml"
    path.write_text(
        'code_types:\n  "100":\n    label: 客户等级\n    column_refs:\n'
        "      - table: ads_cust_info_d\n        column: cust_lvl_cd\n"
        "      - table: other_table\n        column: lvl_cd\n",
        encoding="utf-8",
    )
    demoted = rt.remove_value_descriptor_refs(path, "other_table")
    assert demoted == []
    assert "column: lvl_cd" not in path.read_text(encoding="utf-8")
    assert "column: cust_lvl_cd" in path.read_text(encoding="utf-8")


# ---------- 6. DuckDB DROP ----------


@pytest.fixture()
def db_copy(tmp_path: Path) -> Path:
    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    con.execute(f"CREATE TABLE {TABLE} (pty_id VARCHAR)")
    con.execute(f"INSERT INTO {TABLE} VALUES ('p1')")
    con.execute("CREATE TABLE keep_me (id INTEGER)")
    con.close()
    return db


def test_drop_db_table(db_copy: Path):
    assert rt.db_table_exists(db_copy, TABLE)
    assert rt.drop_db_table(db_copy, TABLE)
    assert not rt.db_table_exists(db_copy, TABLE)
    # 其他表不受影响
    assert rt.db_table_exists(db_copy, "keep_me")


def test_drop_db_table_missing_is_noop(db_copy: Path):
    assert not rt.drop_db_table(db_copy, "no_such_table")


# ---------- 反向核验 ----------


def test_verify_removal_all_clear(script_copy: Path, metadata_copy: Path):
    rt.remove_import_entry(script_copy, TABLE)
    rt.delete_table_yaml(metadata_copy, TABLE)
    rt.remove_join_graph_entries(metadata_copy / "join_graph.yaml", TABLE)
    rt.remove_pruning_entries(metadata_copy / "pruning.yaml", TABLE)
    rt.remove_value_descriptor_refs(metadata_copy / "value_descriptors.yaml", TABLE)
    assert rt.verify_removal(metadata_copy, TABLE) == []


def test_verify_removal_reports_residuals(metadata_copy: Path):
    issues = rt.verify_removal(metadata_copy, TABLE)
    assert issues  # 未删除时应有残留报告
    assert any("join_graph" in i for i in issues)


# ---------- CLI 全流程 ----------


def test_cli_dry_run_writes_nothing(
    tmp_path: Path, script_copy: Path, metadata_copy: Path, monkeypatch, capsys
):
    monkeypatch.setattr(rt, "SCRIPT_PATH", script_copy)
    monkeypatch.setattr(rt, "METADATA_DIR", metadata_copy)
    monkeypatch.setattr(rt, "DB_PATH", tmp_path / "absent.duckdb")

    before_script = script_copy.read_text(encoding="utf-8")
    before_vd = (metadata_copy / "value_descriptors.yaml").read_text(encoding="utf-8")

    assert rt.main([TABLE, "--dry-run"]) == 0
    assert script_copy.read_text(encoding="utf-8") == before_script
    assert (metadata_copy / "value_descriptors.yaml").read_text(encoding="utf-8") == before_vd
    assert "dry-run" in capsys.readouterr().out


def test_cli_full_removal(
    tmp_path: Path, script_copy: Path, metadata_copy: Path, db_copy: Path, monkeypatch, capsys
):
    monkeypatch.setattr(rt, "SCRIPT_PATH", script_copy)
    monkeypatch.setattr(rt, "METADATA_DIR", metadata_copy)
    monkeypatch.setattr(rt, "DB_PATH", db_copy)

    assert rt.main([TABLE]) == 0
    out = capsys.readouterr().out
    assert "反向核验通过" in out

    assert not rt.import_entry_exists(script_copy.read_text(encoding="utf-8"), TABLE)
    assert not (metadata_copy / "tables" / f"{TABLE}.yaml").exists()
    assert rt.verify_removal(metadata_copy, TABLE) == []
    assert not rt.db_table_exists(db_copy, TABLE)
    assert rt.db_table_exists(db_copy, "keep_me")


def test_cli_refuses_handwritten_table(
    script_copy: Path, metadata_copy: Path, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(rt, "SCRIPT_PATH", script_copy)
    monkeypatch.setattr(rt, "METADATA_DIR", metadata_copy)
    monkeypatch.setattr(rt, "DB_PATH", tmp_path / "absent.duckdb")

    before = script_copy.read_text(encoding="utf-8")
    assert rt.main(["ads_cust_info_d"]) == 1
    assert script_copy.read_text(encoding="utf-8") == before


def test_cli_unknown_table_reports_nothing(
    script_copy: Path, metadata_copy: Path, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(rt, "SCRIPT_PATH", script_copy)
    monkeypatch.setattr(rt, "METADATA_DIR", metadata_copy)
    monkeypatch.setattr(rt, "DB_PATH", tmp_path / "absent.duckdb")
    assert rt.main(["no_such_table"]) == 1