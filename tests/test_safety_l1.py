"""Tests for L1 AST safety fence (phase-2 step 4)."""

from __future__ import annotations

import pytest

from querypilot.metadata_engine import load_metadata
from querypilot.safety import guard_sql


@pytest.fixture(scope="module")
def metadata():
    return load_metadata(load_db_codes=False)


# ---------------------------------------------------------------------------
# Readonly / dangerous ops
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM ads_cust_info_d",
        "DROP TABLE ads_cust_info_d",
        "UPDATE ads_cust_info_d SET cust_age = 1",
        "INSERT INTO ads_cust_info_d (pty_id) VALUES ('1')",
        "CREATE TABLE evil AS SELECT 1",
        "TRUNCATE TABLE ads_cust_info_d",
        "COPY ads_cust_info_d TO 'out.csv'",
        "ALTER TABLE ads_cust_info_d ADD COLUMN x INTEGER",
        "GRANT SELECT ON ads_cust_info_d TO someone",
    ],
)
def test_blocks_dangerous_ops(metadata, sql):
    result = guard_sql(sql, metadata=metadata)
    assert not result.ok
    assert any(v.code == "dangerous_op" for v in result.violations)


@pytest.mark.parametrize(
    "sql",
    [
        "ATTACH 'evil.db' AS evil",
        "ATTACH DATABASE 'evil.db' AS evil",
        "DETACH evil",
    ],
)
def test_blocks_attach_detach(metadata, sql):
    """ATTACH/DETACH must not pass; may surface as dangerous_op or parse_error."""
    result = guard_sql(sql, metadata=metadata)
    assert not result.ok
    codes = {v.code for v in result.violations}
    assert codes & {"dangerous_op", "parse_error"}, codes


def test_allows_simple_select(metadata):
    sql = "SELECT cust_age, gender_cd FROM ads_cust_info_d WHERE cust_age > 30"
    result = guard_sql(sql, metadata=metadata)
    assert result.ok, result.violations
    assert "ads_cust_info_d" in result.sql
    assert "cust_age" in result.sql


def test_allows_cte_select(metadata):
    sql = """
    WITH latest AS (
      SELECT pty_id, nm_tot_aset
      FROM dws_cust_aset_d
    )
    SELECT COUNT(*) AS cnt
    FROM ads_cust_info_d AS c
    JOIN latest AS a ON c.pty_id = a.pty_id
    WHERE a.nm_tot_aset > 1000000
    """
    result = guard_sql(sql, metadata=metadata)
    assert result.ok, result.violations
    assert "WITH" in result.sql.upper()


def test_allows_derived_subquery_projected_columns(metadata):
    """JOIN (SELECT ... AS tran_amt) AS b — b.tran_amt must not be unknown_column."""
    sql = """
    SELECT c.up_org_name, c.org_name, SUM(b.tran_amt) AS tran_amt
    FROM ads_cust_info_d AS a
    INNER JOIN (
      SELECT t.pty_id, SUM(t.buy_amt) + SUM(t.sell_amt) AS tran_amt
      FROM dwd_cust_tran_d AS t
      INNER JOIN dim_product AS p
        ON t.prdt_id = p.prdt_id AND p.prdt_type_name = '科创板'
      WHERE t.data_dt BETWEEN '20260110' AND '20260215'
      GROUP BY t.pty_id
      HAVING SUM(t.buy_amt) + SUM(t.sell_amt) > 250000
    ) AS b ON a.pty_id = b.pty_id
    LEFT JOIN dim_branch AS c ON a.org_id = c.org_id
    GROUP BY c.up_org_name, c.org_name
    """
    allowed = {
        "ads_cust_info_d",
        "dwd_cust_tran_d",
        "dim_product",
        "dim_branch",
    }
    result = guard_sql(sql, metadata=metadata, allowed_tables=allowed)
    assert result.ok, result.violations
    assert not any(v.code == "unknown_column" for v in result.violations)


def test_empty_sql(metadata):
    result = guard_sql("   ", metadata=metadata)
    assert not result.ok
    assert result.violations[0].code == "empty_sql"


def test_multiple_statements_blocked(metadata):
    result = guard_sql(
        "SELECT 1 FROM ads_cust_info_d; DROP TABLE ads_cust_info_d",
        metadata=metadata,
    )
    assert not result.ok
    assert any(v.code == "multiple_statements" for v in result.violations)


def test_parse_error(metadata):
    result = guard_sql("SELEECT FROM", metadata=metadata)
    assert not result.ok
    assert any(v.code == "parse_error" for v in result.violations)


# ---------------------------------------------------------------------------
# Table allowlist
# ---------------------------------------------------------------------------


def test_blocks_unauthorized_table(metadata):
    result = guard_sql("SELECT * FROM secret_customers", metadata=metadata)
    assert not result.ok
    assert any(v.code == "unauthorized_table" for v in result.violations)


def test_blocks_unauthorized_table_in_subquery(metadata):
    sql = """
    SELECT pty_id FROM ads_cust_info_d
    WHERE EXISTS (SELECT 1 FROM secret_customers s WHERE s.pty_id = ads_cust_info_d.pty_id)
    """
    result = guard_sql(sql, metadata=metadata)
    assert not result.ok
    assert any(
        v.code == "unauthorized_table" and "secret_customers" in v.message
        for v in result.violations
    )


def test_allowed_tables_subset_blocks_others(metadata):
    sql = """
    SELECT c.pty_id, a.nm_tot_aset
    FROM ads_cust_info_d AS c
    JOIN dws_cust_aset_d AS a ON c.pty_id = a.pty_id
    """
    result = guard_sql(sql, metadata=metadata, allowed_tables={"ads_cust_info_d"})
    assert not result.ok
    assert any(
        v.code == "unauthorized_table" and "dws_cust_aset_d" in v.message for v in result.violations
    )


def test_allowed_tables_subset_accepts(metadata):
    result = guard_sql(
        "SELECT cust_age FROM ads_cust_info_d",
        metadata=metadata,
        allowed_tables={"ads_cust_info_d"},
    )
    assert result.ok, result.violations


# ---------------------------------------------------------------------------
# Column validation + fuzzy fix
# ---------------------------------------------------------------------------


def test_fuzzy_fixes_column_typo(metadata):
    result = guard_sql(
        "SELECT cust_agge FROM ads_cust_info_d",
        metadata=metadata,
    )
    assert result.ok, result.violations
    assert any(f.original == "cust_agge" and f.fixed == "cust_age" for f in result.fixes)
    assert "cust_age" in result.sql
    assert "cust_agge" not in result.sql


def test_fuzzy_fixes_qualified_column(metadata):
    result = guard_sql(
        "SELECT c.gender_cdd FROM ads_cust_info_d AS c",
        metadata=metadata,
    )
    assert result.ok, result.violations
    assert any(f.fixed == "gender_cd" for f in result.fixes)
    assert "gender_cd" in result.sql


def test_unknown_column_without_close_match_blocked(metadata):
    result = guard_sql(
        "SELECT totally_unknown_col_xyz FROM ads_cust_info_d",
        metadata=metadata,
    )
    assert not result.ok
    assert any(v.code == "unknown_column" for v in result.violations)


def test_wrong_table_column_not_fuzzy_fixed(metadata):
    """Asset column on customer table is hallucination — block, do not invent a fix."""
    result = guard_sql(
        "SELECT nm_tot_aset FROM ads_cust_info_d",
        metadata=metadata,
        allowed_tables={"ads_cust_info_d"},
    )
    assert not result.ok
    assert any(v.code == "unknown_column" for v in result.violations)
    assert result.fixes == []
    assert "nm_tot_aset" in result.sql  # failure keeps original SQL


def test_auto_fix_can_be_disabled(metadata):
    result = guard_sql(
        "SELECT cust_agge FROM ads_cust_info_d",
        metadata=metadata,
        auto_fix_columns=False,
    )
    assert not result.ok
    assert any(v.code == "unknown_column" for v in result.violations)
    assert result.fixes == []


def test_star_select_ok(metadata):
    result = guard_sql("SELECT * FROM dim_product", metadata=metadata)
    assert result.ok, result.violations


# ---------------------------------------------------------------------------
# End-to-end with generator-like SQL + optional live SQL
# ---------------------------------------------------------------------------


def test_guards_few_shot_style_sql(metadata):
    sql = """
    SELECT COUNT(*) AS cnt
    FROM ads_cust_info_d
    WHERE cust_age > 30
      AND gender_cd = '5000003'
    """
    result = guard_sql(sql, metadata=metadata)
    assert result.ok, result.violations


def test_cte_alias_not_treated_as_unauthorized_table(metadata):
    sql = """
    WITH cust AS (
      SELECT pty_id, cust_age FROM ads_cust_info_d
    )
    SELECT COUNT(*) FROM cust WHERE cust_age > 40
    """
    result = guard_sql(sql, metadata=metadata)
    assert result.ok, result.violations
    assert not any(v.code == "unauthorized_table" for v in result.violations)


def test_order_by_select_alias_allowed(metadata):
    """Regression: ORDER BY projection alias must not be flagged as unknown_column."""
    sql = """
    SELECT b.org_name, COUNT(c.pty_id) AS cust_cnt
    FROM dim_branch AS b
    LEFT JOIN ads_cust_info_d AS c ON b.org_id = c.org_id
    GROUP BY b.org_name
    ORDER BY cust_cnt DESC
    """
    result = guard_sql(
        sql,
        metadata=metadata,
        allowed_tables={"dim_branch", "ads_cust_info_d"},
    )
    assert result.ok, result.violations
    assert not any(v.code == "unknown_column" for v in result.violations)
    assert "cust_cnt" in result.sql.lower()


def test_order_by_unknown_non_alias_still_blocked(metadata):
    """ORDER BY a name that is not a SELECT alias remains unknown_column."""
    sql = """
    SELECT org_name
    FROM dim_branch
    ORDER BY not_a_real_sort_key_xyz DESC
    """
    result = guard_sql(sql, metadata=metadata, allowed_tables={"dim_branch"})
    assert not result.ok
    assert any(
        v.code == "unknown_column" and "not_a_real_sort_key_xyz" in v.message
        for v in result.violations
    )


# ---------------------------------------------------------------------------
# Live: generated SQL should pass L1
# ---------------------------------------------------------------------------


def _api_key_ready() -> bool:
    from querypilot.config import get_settings

    key = get_settings().deepseek_api_key
    return bool(key) and not key.startswith("sk-your")


@pytest.mark.skipif(not _api_key_ready(), reason="DEEPSEEK_API_KEY not set")
def test_live_generated_sql_passes_l1(metadata):
    from querypilot.agent import generate_sql

    gen = generate_sql(
        "有多少年龄大于30岁的女性客户？",
        metadata=metadata,
        max_few_shots=2,
        max_tokens=600,
    )
    allowed = set(gen.pruned.tables) if gen.pruned else None
    result = guard_sql(gen.sql, metadata=metadata, allowed_tables=allowed)
    assert result.ok, (result.violations, gen.sql)
    assert result.violations == []
    upper = f" {result.sql.upper()} "
    for banned in (
        "DELETE ",
        "DROP ",
        "UPDATE ",
        "INSERT ",
        "TRUNCATE ",
        "CREATE ",
        "COPY ",
        "ALTER ",
        "GRANT ",
    ):
        assert banned not in upper, f"readonly check hit {banned!r} in:\n{result.sql}"
