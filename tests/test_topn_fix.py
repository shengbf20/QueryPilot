"""Tests for org_name Top-N re-aggregation fix."""

from __future__ import annotations

from querypilot.agent.topn_fix import fix_org_topn_sql


def test_reaggregates_org_id_grain_to_org_name():
    sql = """
    WITH org_amt AS (
      SELECT c.org_id, SUM(1) AS total_trade_amt
      FROM ads_cust_info_d AS c
      GROUP BY c.org_id
    )
    SELECT b.org_name, o.total_trade_amt
    FROM org_amt AS o
    JOIN dim_branch AS b ON o.org_id = b.org_id
    ORDER BY o.total_trade_amt DESC, b.org_name
    LIMIT 5
    """
    out = fix_org_topn_sql(sql)
    low = out.lower().replace(" ", "")
    assert "groupbyorg_name" in low
    assert "sum(total_trade_amt)" in low
    assert "limit5" in low


def test_noop_when_already_grouped_by_org_name():
    sql = """
    SELECT b.org_name, SUM(t.buy_amt) AS trade_amt
    FROM dwd_cust_tran_d AS t
    JOIN ads_cust_info_d AS c ON t.pty_id = c.pty_id
    JOIN dim_branch AS b ON c.org_id = b.org_id
    GROUP BY b.org_name
    ORDER BY trade_amt DESC, b.org_name
    LIMIT 5
    """
    assert fix_org_topn_sql(sql) == sql
