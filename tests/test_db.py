"""Unit tests for DuckDB execution helpers."""

from __future__ import annotations

import duckdb
import pytest

from querypilot.config import get_settings
from querypilot.db import (
    connection,
    execute,
    explain,
    get_connection,
    normalize_sql,
)


@pytest.fixture()
def mem() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE t (id INTEGER, name VARCHAR)")
    con.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b'), (3, 'c')")
    yield con
    con.close()


def test_normalize_sql_strips_semicolon():
    assert normalize_sql("  SELECT 1;  ") == "SELECT 1"


def test_execute_on_memory(mem):
    result = execute("SELECT id, name FROM t ORDER BY id", con=mem)
    assert result.columns == ["id", "name"]
    assert result.row_count == 3
    assert result.to_dicts()[0] == {"id": 1, "name": "a"}


def test_execute_max_rows(mem):
    result = execute("SELECT id FROM t ORDER BY id", con=mem, max_rows=2)
    assert result.row_count == 2
    assert [r[0] for r in result.rows] == [1, 2]


def test_explain_ok(mem):
    result = explain("SELECT id FROM t WHERE id = 1", con=mem)
    assert result.ok
    assert result.error is None
    assert result.plan_rows is not None
    assert len(result.plan_rows) >= 1


def test_explain_invalid_sql(mem):
    result = explain("SELECT missing_col FROM t", con=mem)
    assert not result.ok
    assert result.error
    assert "missing_col" in result.error.lower() or "not found" in result.error.lower() or "Binder" in result.error


def test_explain_empty_sql(mem):
    result = explain("   ", con=mem)
    assert not result.ok
    assert "Empty" in (result.error or "")


def test_explain_idempotent_prefix(mem):
    result = explain("EXPLAIN SELECT 1", con=mem)
    assert result.ok


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
def test_get_connection_and_list_tables():
    with connection(read_only=True) as con:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    assert "ads_cust_info_d" in tables
    assert "dim_product" in tables


@pytest.mark.skipif(
    not get_settings().db_path.exists(),
    reason="competition.duckdb not imported yet",
)
def test_project_db_explain_and_execute():
    con = get_connection(read_only=True)
    try:
        plan = explain(
            "SELECT COUNT(*) AS n FROM ads_cust_info_d",
            con=con,
        )
        assert plan.ok, plan.error
        result = execute(
            "SELECT COUNT(*) AS n FROM ads_cust_info_d",
            con=con,
            max_rows=1,
        )
        assert result.columns == ["n"]
        assert result.row_count == 1
        assert result.rows[0][0] > 0
    finally:
        con.close()
