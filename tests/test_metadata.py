"""Tests for table metadata YAML."""

import duckdb
import pytest

from querypilot.config import get_settings
from querypilot.metadata_engine import (
    EXPECTED_TABLES,
    load_all_tables,
    validate_all,
)
from querypilot.metadata_engine.value_descriptors import load_value_descriptor_config


def test_all_tables_loaded():
    tables = load_all_tables()
    assert set(tables.keys()) == set(EXPECTED_TABLES)


def test_validation_passes():
    result = validate_all()
    assert result.ok, result.errors


def test_ads_cust_info_has_code_columns():
    tables = load_all_tables()
    meta = tables["ads_cust_info_d"]
    coded = {c.name: c.code_type_id for c in meta.columns if c.code_type_id}
    assert coded["gender_cd"] == "500"
    assert coded["edu_cd"] == "600"
    assert coded["prof_cd"] == "700"
    assert coded["cust_lvl_cd"] == "100"
    assert coded["cust_status"] == "200"


def test_ads_cust_info_notes_forbid_default_data_dt_join():
    """Hard rule: cross-table joins must not default to data_dt equality."""
    meta = load_all_tables()["ads_cust_info_d"]
    notes_text = "\n".join(meta.notes)
    assert "pty_id" in notes_text
    assert "data_dt" in notes_text
    assert any(
        ("不对齐" in n or "不要默认加 data_dt" in n or "只用 pty_id" in n)
        for n in meta.notes
    ), meta.notes


def test_cust_type_enum_values_match_static_enums():
    """Table YAML and value_descriptors must agree on cust_type codes."""
    meta = load_all_tables()["ads_cust_info_d"]
    col = meta.get_column("cust_type")
    assert col is not None
    static = load_value_descriptor_config().static_enums.get("cust_type", {})
    assert static, "value_descriptors.static_enums.cust_type missing"
    if col.enum_ref:
        assert col.enum_ref == "cust_type"
    assert col.enum_values == static


def test_dim_public_describe_sql_name():
    tables = load_all_tables()
    col = tables["dim_public"].get_column("describe")
    assert col is not None
    assert col.sql_name == '"describe"'


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
def test_yaml_columns_match_duckdb_schema():
    """Live check: YAML column sets equal DuckDB DESCRIBE (not just DB_COLUMNS)."""
    tables = load_all_tables()
    con = duckdb.connect(str(get_settings().db_path), read_only=True)
    try:
        for table_name, meta in tables.items():
            rows = con.execute(f"DESCRIBE {table_name}").fetchall()
            db_cols = {str(row[0]) for row in rows}
            assert meta.column_names == db_cols, (
                f"{table_name}: yaml={sorted(meta.column_names)} "
                f"db={sorted(db_cols)}"
            )
    finally:
        con.close()
