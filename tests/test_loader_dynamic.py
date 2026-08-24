"""Tests for dynamic table discovery (metadata/tables directory scan)."""

from __future__ import annotations

import shutil
from pathlib import Path

from querypilot.config import get_settings
from querypilot.metadata_engine import discover_table_names, load_all_tables


def test_discover_table_names_sorted():
    names = discover_table_names()
    assert names == sorted(names)
    assert "ads_cust_info_d" in names
    assert "dim_public" in names
    assert len(names) >= 8


def test_load_all_tables_empty_dir(tmp_path: Path):
    """空目录返回空 dict，不崩溃（上层 validator 负责报错）。"""
    assert load_all_tables(tmp_path) == {}


def test_new_table_yaml_is_loaded_without_code_change(tmp_path: Path):
    """动态生效性：往目录放一个新表 YAML 即被加载，无需改任何代码。"""
    src = get_settings().metadata_dir / "tables"
    shutil.copytree(src, tmp_path, dirs_exist_ok=True)
    (tmp_path / "dwd_new_table_d.yaml").write_text(
        """\
table: dwd_new_table_d
alias: 新示例表
layer: dwd
description: 测试用新表（动态发现）
primary_key: [pty_id]
usage:
  - 测试
notes: []
columns:
  - name: pty_id
    type: VARCHAR
    description: 客户号
""",
        encoding="utf-8",
    )

    tables = load_all_tables(tmp_path)
    assert "dwd_new_table_d" in tables
    assert tables["dwd_new_table_d"].alias == "新示例表"
    assert "dwd_new_table_d" in discover_table_names(tmp_path)
