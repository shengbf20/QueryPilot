"""One-off Step 2a exploration; writes UTF-8 report next to this file."""

from __future__ import annotations

from pathlib import Path

from querypilot.db import execute

OUT = Path(__file__).with_name("_explore_report.txt")
lines: list[str] = []


def show(title: str, sql: str, max_rows: int = 40) -> None:
    r = execute(sql, max_rows=max_rows)
    lines.append(f"### {title} (rows={r.row_count})")
    lines.append("cols: " + ", ".join(r.columns))
    for row in r.rows:
        lines.append(repr(row))
    lines.append("")


def main() -> None:
    show(
        "cust_status",
        """
        SELECT a.cust_status AS code, p."describe" AS name, COUNT(*) AS n
        FROM ads_cust_info_d a
        LEFT JOIN dim_public p ON a.cust_status = p.code AND p.code_type_id = '200'
        GROUP BY 1, 2 ORDER BY n DESC
        """,
    )
    show(
        "prof_cd top",
        """
        SELECT a.prof_cd AS code, p."describe" AS name, COUNT(*) AS n
        FROM ads_cust_info_d a
        LEFT JOIN dim_public p ON a.prof_cd = p.code AND p.code_type_id = '700'
        GROUP BY 1, 2 ORDER BY n DESC LIMIT 15
        """,
    )
    show(
        "edu_cd",
        """
        SELECT a.edu_cd AS code, p."describe" AS name, COUNT(*) AS n
        FROM ads_cust_info_d a
        LEFT JOIN dim_public p ON a.edu_cd = p.code AND p.code_type_id = '600'
        GROUP BY 1, 2 ORDER BY n DESC
        """,
    )
    show(
        "gender",
        """
        SELECT a.gender_cd AS code, p."describe" AS name, COUNT(*) AS n
        FROM ads_cust_info_d a
        LEFT JOIN dim_public p ON a.gender_cd = p.code AND p.code_type_id = '500'
        GROUP BY 1, 2 ORDER BY n DESC
        """,
    )
    show(
        "cust_lvl",
        """
        SELECT a.cust_lvl_cd AS code, p."describe" AS name, COUNT(*) AS n
        FROM ads_cust_info_d a
        LEFT JOIN dim_public p ON a.cust_lvl_cd = p.code AND p.code_type_id = '100'
        GROUP BY 1, 2 ORDER BY n DESC
        """,
    )
    show(
        "female by prof top",
        """
        SELECT p."describe" AS prof, a.prof_cd, COUNT(*) AS n
        FROM ads_cust_info_d a
        JOIN dim_public p ON a.prof_cd = p.code AND p.code_type_id = '700'
        WHERE a.gender_cd = '5000003'
        GROUP BY 1, 2 ORDER BY n DESC LIMIT 10
        """,
    )
    show(
        "edu high school and below",
        """
        SELECT COUNT(*) AS n
        FROM ads_cust_info_d a
        JOIN dim_public p ON a.edu_cd = p.code AND p.code_type_id = '600'
        WHERE p."describe" IN ('小学', '初中', '高中', '中专', '中技', '职高')
        """,
    )
    show(
        "total_aset thresholds 20260331",
        """
        WITH a AS (
          SELECT pty_id,
                 coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) AS total_aset
          FROM dws_cust_aset_d WHERE data_dt = '20260331'
        )
        SELECT COUNT(*) AS n_all,
               SUM(CASE WHEN total_aset > 1000000 THEN 1 ELSE 0 END) AS gt_100w,
               SUM(CASE WHEN total_aset > 500000 THEN 1 ELSE 0 END) AS gt_50w,
               SUM(CASE WHEN total_aset > 100000 THEN 1 ELSE 0 END) AS gt_10w,
               SUM(CASE WHEN total_aset > 50000 THEN 1 ELSE 0 END) AS gt_5w
        FROM a
        """,
    )
    show(
        "nm_bal thresholds 20260331",
        """
        SELECT COUNT(*) AS n,
               SUM(CASE WHEN coalesce(nm_bal, 0) > 100000 THEN 1 ELSE 0 END) AS gt_10w,
               SUM(CASE WHEN coalesce(nm_bal, 0) > 50000 THEN 1 ELSE 0 END) AS gt_5w,
               SUM(CASE WHEN coalesce(nm_bal, 0) > 10000 THEN 1 ELSE 0 END) AS gt_1w,
               SUM(CASE WHEN coalesce(nm_bal, 0) > 1000 THEN 1 ELSE 0 END) AS gt_1k,
               approx_quantile(coalesce(nm_bal, 0), 0.9) AS p90,
               approx_quantile(coalesce(nm_bal, 0), 0.5) AS p50
        FROM dws_cust_aset_d WHERE data_dt = '20260331'
        """,
    )
    show(
        "prov top",
        """
        SELECT prov_name, COUNT(*) AS n FROM ads_cust_info_d
        GROUP BY 1 ORDER BY n DESC LIMIT 10
        """,
    )
    show(
        "org_name top",
        """
        SELECT b.org_name, COUNT(*) AS n
        FROM ads_cust_info_d a
        JOIN dim_branch b ON a.org_id = b.org_id
        GROUP BY 1 ORDER BY n DESC LIMIT 10
        """,
    )
    show(
        "product hold top by name",
        """
        SELECT p.prdt_name, p.prdt_type_name, p.up_prdt_type_name, p.up_prdt_type_id,
               COUNT(DISTINCT h.pty_id) AS cust_n,
               COUNT(*) AS hold_rows
        FROM dwd_cust_hold_d h
        JOIN dim_product p ON h.prdt_id = p.prdt_id
        WHERE h.data_dt = '20260331'
        GROUP BY 1, 2, 3, 4
        ORDER BY cust_n DESC LIMIT 15
        """,
    )
    show(
        "hold mkt_val / hold_cnt thresholds (top product)",
        """
        WITH top_prdt AS (
          SELECT h.prdt_id
          FROM dwd_cust_hold_d h
          WHERE h.data_dt = '20260331'
          GROUP BY 1 ORDER BY COUNT(DISTINCT pty_id) DESC LIMIT 1
        )
        SELECT p.prdt_name, p.sor_prdt_id,
               COUNT(DISTINCT h.pty_id) AS cust_n,
               SUM(CASE WHEN coalesce(h.mkt_val, 0) > 1000 THEN 1 ELSE 0 END) AS mkt_gt_1k,
               SUM(CASE WHEN coalesce(h.mkt_val, 0) > 10000 THEN 1 ELSE 0 END) AS mkt_gt_1w,
               SUM(CASE WHEN coalesce(h.hold_cnt, 0) > 100 THEN 1 ELSE 0 END) AS cnt_gt_100,
               SUM(CASE WHEN coalesce(h.hold_cnt, 0) > 1000 THEN 1 ELSE 0 END) AS cnt_gt_1k
        FROM dwd_cust_hold_d h
        JOIN top_prdt t ON h.prdt_id = t.prdt_id
        JOIN dim_product p ON h.prdt_id = p.prdt_id
        WHERE h.data_dt = '20260331'
        GROUP BY 1, 2
        """,
    )
    show(
        "sys_source hold",
        """
        SELECT sys_source, COUNT(*) AS n, COUNT(DISTINCT pty_id) AS cust_n
        FROM dwd_cust_hold_d WHERE data_dt = '20260331'
        GROUP BY 1 ORDER BY n DESC
        """,
    )
    show(
        "sys_source tran Q1",
        """
        SELECT sys_source, COUNT(*) AS n, COUNT(DISTINCT pty_id) AS cust_n
        FROM dwd_cust_tran_d
        WHERE data_dt BETWEEN '20260101' AND '20260331'
        GROUP BY 1 ORDER BY n DESC
        """,
    )
    show(
        "ccy hold",
        """
        SELECT ccy, COUNT(*) AS n, COUNT(DISTINCT pty_id) AS cust_n,
               SUM(coalesce(mkt_val, 0)) AS mkt_sum
        FROM dwd_cust_hold_d WHERE data_dt = '20260331'
        GROUP BY 1 ORDER BY n DESC
        """,
    )
    show(
        "up_prdt_type hold",
        """
        SELECT p.up_prdt_type_id, p.up_prdt_type_name,
               COUNT(DISTINCT h.pty_id) AS cust_n
        FROM dwd_cust_hold_d h
        JOIN dim_product p ON h.prdt_id = p.prdt_id
        WHERE h.data_dt = '20260331'
        GROUP BY 1, 2 ORDER BY cust_n DESC
        """,
    )
    show(
        "prdt_type_name hold (non 科创板 sample)",
        """
        SELECT p.prdt_type_name, COUNT(DISTINCT h.pty_id) AS cust_n
        FROM dwd_cust_hold_d h
        JOIN dim_product p ON h.prdt_id = p.prdt_id
        WHERE h.data_dt = '20260331'
        GROUP BY 1 ORDER BY cust_n DESC LIMIT 15
        """,
    )
    show(
        "sell/buy thresholds Q1",
        """
        SELECT COUNT(DISTINCT pty_id) AS cust_n,
               SUM(CASE WHEN sell_amt_sum > 100000 THEN 1 ELSE 0 END) AS sell_gt_10w,
               SUM(CASE WHEN sell_amt_sum > 50000 THEN 1 ELSE 0 END) AS sell_gt_5w,
               SUM(CASE WHEN sell_amt_sum > 10000 THEN 1 ELSE 0 END) AS sell_gt_1w,
               SUM(CASE WHEN buy_cnt_sum > 5 THEN 1 ELSE 0 END) AS buy_cnt_gt_5,
               SUM(CASE WHEN buy_cnt_sum > 2 THEN 1 ELSE 0 END) AS buy_cnt_gt_2,
               SUM(CASE WHEN rake_sum > 100 THEN 1 ELSE 0 END) AS rake_gt_100,
               SUM(CASE WHEN rake_sum > 50 THEN 1 ELSE 0 END) AS rake_gt_50,
               SUM(CASE WHEN rake_sum > 10 THEN 1 ELSE 0 END) AS rake_gt_10
        FROM (
          SELECT pty_id,
                 SUM(coalesce(sell_amt, 0)) AS sell_amt_sum,
                 SUM(coalesce(buy_cnt, 0)) AS buy_cnt_sum,
                 SUM(coalesce(buy_rake, 0) + coalesce(sell_rake, 0)) AS rake_sum
          FROM dwd_cust_tran_d
          WHERE data_dt BETWEEN '20260101' AND '20260331'
          GROUP BY pty_id
        )
        """,
    )
    show(
        "fin cash_in/out Q1",
        """
        SELECT COUNT(DISTINCT pty_id) AS cust_n,
               SUM(CASE WHEN cash_in_sum > 100000 THEN 1 ELSE 0 END) AS in_gt_10w,
               SUM(CASE WHEN cash_in_sum > 50000 THEN 1 ELSE 0 END) AS in_gt_5w,
               SUM(CASE WHEN cash_in_sum > 10000 THEN 1 ELSE 0 END) AS in_gt_1w,
               SUM(CASE WHEN cash_out_sum > 100000 THEN 1 ELSE 0 END) AS out_gt_10w,
               SUM(CASE WHEN cash_out_sum > 10000 THEN 1 ELSE 0 END) AS out_gt_1w,
               SUM(CASE WHEN tran_out_sum > 10000 THEN 1 ELSE 0 END) AS tout_gt_1w,
               approx_quantile(cash_in_sum, 0.9) AS in_p90,
               approx_quantile(cash_out_sum, 0.9) AS out_p90
        FROM (
          SELECT pty_id,
                 SUM(coalesce(cash_in, 0)) AS cash_in_sum,
                 SUM(coalesce(cash_out, 0)) AS cash_out_sum,
                 SUM(coalesce(tran_out, 0)) AS tran_out_sum
          FROM dws_cust_fin_d
          WHERE data_dt BETWEEN '20260101' AND '20260331'
          GROUP BY pty_id
        )
        """,
    )
    show(
        "sor_prdt_id sample top hold",
        """
        SELECT p.sor_prdt_id, p.prdt_name, COUNT(DISTINCT h.pty_id) AS cust_n
        FROM dwd_cust_hold_d h
        JOIN dim_product p ON h.prdt_id = p.prdt_id
        WHERE h.data_dt = '20260331' AND p.sor_prdt_id IS NOT NULL AND p.sor_prdt_id <> ''
        GROUP BY 1, 2 ORDER BY cust_n DESC LIMIT 10
        """,
    )
    show(
        "custom window Jan20-Feb28 trade cust",
        """
        SELECT COUNT(DISTINCT pty_id) AS cust_n,
               SUM(coalesce(buy_amt, 0) + coalesce(sell_amt, 0)) AS amt
        FROM dwd_cust_tran_d
        WHERE data_dt BETWEEN '20260120' AND '20260228'
        """,
    )
    show(
        "aset data_dt span",
        """
        SELECT MIN(data_dt) AS mn, MAX(data_dt) AS mx, COUNT(DISTINCT data_dt) AS days
        FROM dws_cust_aset_d
        """,
    )
    show(
        "avg daily aset > 30w cust count Q1 (calendar denom)",
        """
        WITH days AS (
          SELECT (DATE '2026-03-31' - DATE '2026-01-01')::INTEGER + 1 AS d
        ),
        a AS (
          SELECT pty_id,
                 SUM(coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0))
                   / (SELECT d FROM days) AS avg_aset
          FROM dws_cust_aset_d
          WHERE data_dt BETWEEN '20260101' AND '20260331'
          GROUP BY pty_id
        )
        SELECT COUNT(*) AS n_all,
               SUM(CASE WHEN avg_aset > 300000 THEN 1 ELSE 0 END) AS gt_30w,
               SUM(CASE WHEN avg_aset > 100000 THEN 1 ELSE 0 END) AS gt_10w,
               SUM(CASE WHEN avg_aset > 50000 THEN 1 ELSE 0 END) AS gt_5w
        FROM a
        """,
    )
    show(
        "fc hold named product candidates",
        """
        SELECT p.prdt_name, COUNT(DISTINCT h.pty_id) AS cust_n
        FROM dwd_cust_hold_d h
        JOIN dim_product p ON h.prdt_id = p.prdt_id
        WHERE h.data_dt = '20260331' AND h.sys_source = 'fc'
        GROUP BY 1 ORDER BY cust_n DESC LIMIT 10
        """,
    )
    show(
        "non-diamond lvl for pnl alt",
        """
        SELECT p."describe" AS lvl, a.cust_lvl_cd, COUNT(*) AS n
        FROM ads_cust_info_d a
        JOIN dim_public p ON a.cust_lvl_cd = p.code AND p.code_type_id = '100'
        WHERE p."describe" NOT LIKE '%钻石%'
        GROUP BY 1, 2 ORDER BY n DESC
        """,
    )
    show(
        "status normal-like names in dict 200",
        """
        SELECT code, "describe" FROM dim_public
        WHERE code_type_id = '200'
        ORDER BY code
        """,
    )
    show(
        "H10 candidate trade张家港行 hold保税科技",
        """
        WITH t AS (
          SELECT DISTINCT t.pty_id
          FROM dwd_cust_tran_d t
          JOIN dim_product p ON t.prdt_id = p.prdt_id
          WHERE t.data_dt BETWEEN '20260101' AND '20260331'
            AND p.prdt_name = '张家港行'
        ),
        h AS (
          SELECT DISTINCT h.pty_id
          FROM dwd_cust_hold_d h
          JOIN dim_product p ON h.prdt_id = p.prdt_id
          WHERE h.data_dt = '20260331' AND h.sys_source = 'nm'
            AND p.prdt_name = '保税科技'
        )
        SELECT COUNT(*) AS n FROM t INNER JOIN h ON t.pty_id = h.pty_id
        """,
    )
    show(
        "H10 alt trade保税科技 hold张家港行",
        """
        WITH t AS (
          SELECT DISTINCT t.pty_id
          FROM dwd_cust_tran_d t
          JOIN dim_product p ON t.prdt_id = p.prdt_id
          WHERE t.data_dt BETWEEN '20260101' AND '20260331'
            AND p.prdt_name = '保税科技'
        ),
        h AS (
          SELECT DISTINCT h.pty_id
          FROM dwd_cust_hold_d h
          JOIN dim_product p ON h.prdt_id = p.prdt_id
          WHERE h.data_dt = '20260331' AND h.sys_source = 'nm'
            AND p.prdt_name = '张家港行'
        )
        SELECT COUNT(*) AS n FROM t INNER JOIN h ON t.pty_id = h.pty_id
        """,
    )
    show(
        "silver card male count",
        """
        SELECT COUNT(*) AS n
        FROM ads_cust_info_d
        WHERE cust_lvl_cd = '1000004' AND gender_cd = '5000002'
        """,
    )
    show(
        "创业板 hold cust",
        """
        SELECT COUNT(DISTINCT h.pty_id) AS n
        FROM dwd_cust_hold_d h
        JOIN dim_product p ON h.prdt_id = p.prdt_id
        WHERE h.data_dt = '20260331' AND p.prdt_type_name = '创业板'
        """,
    )
    show(
        "H10 better pair scan top",
        """
        WITH tran_prdt AS (
          SELECT t.pty_id, p.prdt_name AS traded
          FROM dwd_cust_tran_d t
          JOIN dim_product p ON t.prdt_id = p.prdt_id
          WHERE t.data_dt BETWEEN '20260101' AND '20260331'
            AND p.prdt_type_name = 'A股'
          GROUP BY 1, 2
        ),
        hold_prdt AS (
          SELECT h.pty_id, p.prdt_name AS held
          FROM dwd_cust_hold_d h
          JOIN dim_product p ON h.prdt_id = p.prdt_id
          WHERE h.data_dt = '20260331' AND h.sys_source = 'nm'
            AND p.prdt_type_name = 'A股'
          GROUP BY 1, 2
        )
        SELECT t.traded, h.held, COUNT(*) AS n
        FROM tran_prdt t
        JOIN hold_prdt h ON t.pty_id = h.pty_id AND t.traded <> h.held
        GROUP BY 1, 2
        HAVING COUNT(*) >= 3
        ORDER BY n DESC
        LIMIT 15
        """,
    )

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
