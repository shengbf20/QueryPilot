"""Tests for table metadata YAML."""

import pytest

from querypilot.metadata_engine import (
    EXPECTED_TABLES,
    load_all_tables,
    validate_all,
)


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


def test_dim_public_describe_sql_name():
    tables = load_all_tables()
    col = tables["dim_public"].get_column("describe")
    assert col is not None
    assert col.sql_name == '"describe"'
