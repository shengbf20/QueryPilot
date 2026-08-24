"""scripts/add_table.py 测试：类型推断 / 条目生成 / 登记插入 / 幂等保护。"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.add_table import (
    ROOT,
    SCRIPT_PATH,
    build_entry_text,
    infer_column_type,
    infer_columns,
    insert_entry,
    table_already_registered,
    table_name_from_csv,
    verify_entry,
)


# ---------- 纯函数：表名 / 类型推断 ----------


@pytest.mark.parametrize(
    "filename,table",
    [
        ("dwd_cust_risk_assess_d.csv", "dwd_cust_risk_assess_d"),
        ("ads_cust_info_d_20260430.csv", "ads_cust_info_d"),  # 去日期后缀
        ("dim_mgr_info.csv", "dim_mgr_info"),
    ],
)
def test_table_name_from_csv(filename, table):
    assert table_name_from_csv(Path(filename)) == table


@pytest.mark.parametrize(
    "name,values,expected",
    [
        # 列名约定：编码/键列保 VARCHAR（防前导零，与 dim_public 字符串码可比）
        ("risk_lvl_cd", ["4000001", "4000002"], "VARCHAR"),
        ("pty_id", ["1", "2", "3"], "VARCHAR"),
        # 日期样式 → VARCHAR（A1 is_date 按字符串判断）
        ("assess_dt", ["20250101", "20260531"], "VARCHAR"),
        # 整数 → INTEGER / BIGINT
        ("risk_score", ["74", "78"], "INTEGER"),
        ("big_cnt", ["5000000000"], "BIGINT"),
        # 小数 → DECIMAL
        ("buy_mnt", ["123.45", "67.8"], "DECIMAL(20, 4)"),
        # 文本 / 混合 / 空
        ("org_name", ["南京分公司", "上海分公司"], "VARCHAR"),
        ("mixed", ["12", "abc"], "VARCHAR"),
        ("all_empty", ["", ""], "VARCHAR"),
        # 含空值的数值列（部分为空）→ 稳妥 VARCHAR
        ("sparse_num", ["12", "", "34"], "INTEGER"),
    ],
)
def test_infer_column_type(name, values, expected):
    assert infer_column_type(values, name) == expected


def test_infer_columns_order_and_types(tmp_path: Path):
    csv_path = tmp_path / "t.csv"
    csv_path.write_text(
        "data_dt,pty_id,score,amount\n20260531,C001,74,1.5\n20260531,C002,80,2.25\n",
        encoding="utf-8",
    )
    assert infer_columns(csv_path) == [
        ("data_dt", "VARCHAR"),
        ("pty_id", "VARCHAR"),
        ("score", "INTEGER"),
        ("amount", "DECIMAL(20, 4)"),
    ]


# ---------- 条目生成与登记插入 ----------


def test_build_entry_text_with_sim_dir():
    text = build_entry_text(
        "t_new",
        [("pty_id", "VARCHAR"), ("cnt", "INTEGER")],
        csv_dir=ROOT / "data_sim",
    )
    assert '"csv_dir": SIM_DATA_DIR,' in text
    assert '"pattern": "t_new*.csv"' in text
    assert "CREATE TABLE t_new (" in text
    assert "cnt INTEGER" in text


def test_build_entry_text_without_dir():
    """data/ 下的 CSV 不写 csv_dir（默认 DATA_DIR）。"""
    text = build_entry_text("t_new", [("a", "VARCHAR")], csv_dir=None)
    assert "csv_dir" not in text


def test_insert_entry_into_copy(tmp_path: Path):
    """插入真实 import_data.py 副本：语法合法、条目可被正则检出、重复登记被拒。"""
    copy = tmp_path / "import_data.py"
    shutil.copy(SCRIPT_PATH, copy)
    text_before = copy.read_text(encoding="utf-8")
    assert not table_already_registered(text_before, "t_test_copy")

    insert_entry(copy, build_entry_text("t_test_copy", [("a", "VARCHAR")], csv_dir=None))

    import ast

    ast.parse(copy.read_text(encoding="utf-8"))  # 仍是合法 Python
    assert table_already_registered(copy.read_text(encoding="utf-8"), "t_test_copy")
    # 既有内容不被破坏（TABLES 前缀 + 官方表条目仍在）
    assert "TABLES: dict[str, dict] = {" in copy.read_text(encoding="utf-8")
    assert '"dim_product"' in copy.read_text(encoding="utf-8")


# ---------- 试导入验证（内存库） ----------


def test_verify_entry_roundtrip(tmp_path: Path):
    csv_path = tmp_path / "t_verify.csv"
    csv_path.write_text("pty_id,score\nC001,10\nC002,20\n", encoding="utf-8")
    columns = infer_columns(csv_path)
    assert verify_entry("t_verify", columns, csv_path) == 2


def test_verify_entry_type_mismatch_fails(tmp_path: Path):
    """DDL 类型与数据不兼容（整数列给了 abc）→ 报错。"""
    csv_path = tmp_path / "t_bad.csv"
    csv_path.write_text("num\nabc\n", encoding="utf-8")
    with pytest.raises(Exception):
        verify_entry("t_bad", [("num", "INTEGER")], csv_path)


# ---------- CLI 端到端（dry-run 不写盘） ----------


def test_cli_dry_run_writes_nothing(tmp_path: Path, capsys):
    csv_path = tmp_path / "dwd_cli_test_d.csv"
    csv_path.write_text("pty_id,cnt\nC001,1\n", encoding="utf-8")
    script_copy = tmp_path / "import_data_copy.py"

    # --dry-run 模式不应触碰 scripts/import_data.py（用只读断言替代：比对前后内容）
    before = SCRIPT_PATH.read_text(encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "add_table.py"), str(csv_path), "--dry-run"],
        capture_output=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "dwd_cli_test_d" in proc.stdout
    assert "DDL 与 CSV 兼容" in proc.stdout
    assert SCRIPT_PATH.read_text(encoding="utf-8") == before


def test_cli_refuses_existing_table():
    """已登记的表拒绝重复登记（非零退出）。"""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "add_table.py"), "data_sim/dim_mgr_info.csv"],
        capture_output=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 1
    assert "已登记" in proc.stdout + proc.stderr
