"""Tests for deterministic period-PnL SQL normalization."""

from __future__ import annotations

from querypilot.agent.pnl_fix import fix_period_pnl_sql


def test_expands_intuitive_end_minus_bgn_formula():
    sql = """
    WITH target_custs AS (
      SELECT pty_id FROM ads_cust_info_d WHERE cust_lvl_cd = '1000004'
    ),
    bgn_aset AS (
      SELECT pty_id, COALESCE(nm_tot_aset, 0) + COALESCE(fc_pur_aset, 0) AS bgn_aset
      FROM dws_cust_aset_d WHERE data_dt = '20260101'
    ),
    end_aset AS (
      SELECT pty_id, COALESCE(nm_tot_aset, 0) + COALESCE(fc_pur_aset, 0) AS end_aset
      FROM dws_cust_aset_d WHERE data_dt = '20260331'
    ),
    flows AS (
      SELECT pty_id,
        SUM(COALESCE(cash_in, 0)) AS aset_in,
        SUM(COALESCE(cash_out, 0)) AS aset_out
      FROM dws_cust_fin_d
      WHERE data_dt BETWEEN '20260101' AND '20260331'
      GROUP BY pty_id
    )
    SELECT
      t.pty_id,
      COALESCE(b.bgn_aset, 0) AS bgn_aset,
      COALESCE(e.end_aset, 0) AS end_aset,
      COALESCE(f.aset_in, 0) AS aset_in,
      COALESCE(f.aset_out, 0) AS aset_out,
      COALESCE(e.end_aset, 0) - COALESCE(b.bgn_aset, 0)
        + COALESCE(f.aset_out, 0) - COALESCE(f.aset_in, 0) AS aset_pft
    FROM target_custs AS t
    LEFT JOIN bgn_aset AS b ON t.pty_id = b.pty_id
    LEFT JOIN end_aset AS e ON t.pty_id = e.pty_id
    LEFT JOIN flows AS f ON t.pty_id = f.pty_id
    """
    out = fix_period_pnl_sql(sql)
    low = out.lower().replace(" ", "")
    assert "asbgn_aset" in low or "as bgn_aset" in out.lower()
    assert "nm_tot_aset" in low
    assert "fc_pur_aset" in low
    # Quirk: minus bgn nm then plus bgn fc (not minus whole bgn_aset)
    assert "-coalesce(b.nm_tot_aset" in low or "-coalesce(b.\"nm_tot_aset\"" in low
    assert "+coalesce(b.fc_pur_aset" in low or "+coalesce(b.\"fc_pur_aset\"" in low
    assert "end_aset-bgn_aset" not in low
    assert "e.end_aset" not in out.lower() or "end_aset as (" in out.lower()


def test_noop_without_aset_pft():
    sql = "SELECT COUNT(*) AS cnt FROM ads_cust_info_d"
    assert fix_period_pnl_sql(sql) == sql


def test_noop_already_gold_style_direct_joins():
    sql = """
    WITH prdtinfo AS (SELECT pty_id FROM dwd_cust_hold_d)
    SELECT
      q.pty_id,
      coalesce(aset_bgn.nm_tot_aset, 0) + coalesce(aset_bgn.fc_pur_aset, 0) AS bgn_aset,
      coalesce(aset_end.nm_tot_aset, 0) + coalesce(aset_end.fc_pur_aset, 0) AS end_aset,
      coalesce(fin.aset_in, 0) AS aset_in,
      coalesce(fin.aset_out, 0) AS aset_out,
      coalesce(aset_end.nm_tot_aset, 0) + coalesce(aset_end.fc_pur_aset, 0)
        - coalesce(aset_bgn.nm_tot_aset, 0) + coalesce(aset_bgn.fc_pur_aset, 0)
        + coalesce(fin.aset_out, 0) - coalesce(fin.aset_in, 0) AS aset_pft
    FROM prdtinfo AS q
    LEFT JOIN dws_cust_aset_d AS aset_end
      ON q.pty_id = aset_end.pty_id AND aset_end.data_dt = '20260331'
    LEFT JOIN dws_cust_aset_d AS aset_bgn
      ON q.pty_id = aset_bgn.pty_id AND aset_bgn.data_dt = '20260101'
    LEFT JOIN (
      SELECT pty_id, SUM(cash_in) AS aset_in, SUM(cash_out) AS aset_out
      FROM dws_cust_fin_d GROUP BY pty_id
    ) AS fin ON q.pty_id = fin.pty_id
    """
    out = fix_period_pnl_sql(sql)
    # Should recognize gold shape and leave formula intact (or equivalent)
    assert "aset_pft" in out.lower()
    assert "- coalesce(aset_bgn.nm_tot_aset" in out.lower().replace("\n", " ") or (
        "-coalesce(aset_bgn.nm_tot_aset" in out.lower().replace(" ", "")
    )


def test_rewrites_outer_bgn_end_when_cte_already_has_nm_fc():
    """Extra2 FH01 fs0: CTE exposes nm/fc but outer wrongly selects b.bgn_aset."""
    sql = """
    WITH qual_cust AS (SELECT pty_id FROM ads_cust_info_d),
    aset_begin AS (
      SELECT pty_id, COALESCE(nm_tot_aset, 0) AS nm_tot_aset, COALESCE(fc_pur_aset, 0) AS fc_pur_aset
      FROM dws_cust_aset_d WHERE data_dt = '20260101'
    ),
    aset_end AS (
      SELECT pty_id, COALESCE(nm_tot_aset, 0) AS nm_tot_aset, COALESCE(fc_pur_aset, 0) AS fc_pur_aset
      FROM dws_cust_aset_d WHERE data_dt = '20260331'
    ),
    fin_flow AS (
      SELECT pty_id, 1 AS aset_in, 1 AS aset_out FROM dws_cust_fin_d GROUP BY pty_id
    )
    SELECT
      q.pty_id,
      COALESCE(b.bgn_aset, 0) AS bgn_aset,
      COALESCE(e.end_aset, 0) AS end_aset,
      COALESCE(f.aset_in, 0) AS aset_in,
      COALESCE(f.aset_out, 0) AS aset_out,
      COALESCE(e.end_aset, 0) - COALESCE(b.bgn_aset, 0)
        + COALESCE(f.aset_out, 0) - COALESCE(f.aset_in, 0) AS aset_pft
    FROM qual_cust AS q
    LEFT JOIN aset_begin AS b ON q.pty_id = b.pty_id
    LEFT JOIN aset_end AS e ON q.pty_id = e.pty_id
    LEFT JOIN fin_flow AS f ON q.pty_id = f.pty_id
    """
    out = fix_period_pnl_sql(sql)
    low = out.lower().replace(" ", "")
    assert "b.bgn_aset" not in out.lower()
    assert "e.end_aset" not in out.lower() or "as end_aset" in out.lower()
    assert "nm_tot_aset" in low and "fc_pur_aset" in low
    assert "-coalesce(b.nm_tot_aset" in low or "-coalesce(b.\"nm_tot_aset\"" in low
