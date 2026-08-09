"""Probe non-empty sizes for Hard H01–H12 designs."""

from __future__ import annotations

from querypilot.db import execute


def show(title: str, sql: str) -> None:
    r = execute(sql, max_rows=30)
    print(title, "rows=", r.row_count, "preview=", r.rows[:3] if r.rows else None)


def main() -> None:
    # H01: silver card male Q1 pnl cohort size
    show(
        "H01 silver male hold any A股 mkt>1000",
        """
        WITH custinfo AS (
          SELECT a.pty_id
          FROM ads_cust_info_d a
          JOIN dim_public l ON a.cust_lvl_cd = l.code AND l.code_type_id = '100'
          JOIN dim_public g ON a.gender_cd = g.code AND g.code_type_id = '500'
          WHERE l."describe" = '紫金理财银卡客户' AND g."describe" = '男'
        ),
        hold AS (
          SELECT h.pty_id
          FROM dwd_cust_hold_d h
          JOIN dim_product p ON h.prdt_id = p.prdt_id
          WHERE h.data_dt = '20260331' AND p.prdt_type_name = 'A股'
            AND coalesce(h.mkt_val, 0) > 1000
          GROUP BY h.pty_id
        )
        SELECT COUNT(*) FROM custinfo c JOIN hold h ON c.pty_id = h.pty_id
        """,
    )
    show(
        "H02 avg>30w and stock trade>10w then hold taxonomy",
        """
        WITH days AS (
          SELECT (DATE '2026-03-31' - DATE '2026-01-01')::INTEGER + 1 AS d
        ),
        cust_avg AS (
          SELECT pty_id,
                 SUM(coalesce(nm_tot_aset,0)+coalesce(fc_pur_aset,0))/(SELECT d FROM days) AS avg_aset
          FROM dws_cust_aset_d
          WHERE data_dt BETWEEN '20260101' AND '20260331'
          GROUP BY pty_id
          HAVING SUM(coalesce(nm_tot_aset,0)+coalesce(fc_pur_aset,0))/(SELECT d FROM days) > 300000
        ),
        cust_tran AS (
          SELECT t.pty_id
          FROM dwd_cust_tran_d t
          JOIN dim_product p ON t.prdt_id = p.prdt_id
          WHERE t.data_dt BETWEEN '20260101' AND '20260331'
            AND p.up_prdt_type_id = 'PT040000'
          GROUP BY t.pty_id
          HAVING SUM(coalesce(t.buy_amt,0)+coalesce(t.sell_amt,0)) > 100000
        ),
        cohort AS (
          SELECT a.pty_id FROM cust_avg a JOIN cust_tran t ON a.pty_id = t.pty_id
        )
        SELECT COUNT(DISTINCT h.pty_id), COUNT(*)
        FROM cohort c
        JOIN dwd_cust_hold_d h ON c.pty_id = h.pty_id AND h.data_dt = '20260331'
        JOIN dim_product p ON h.prdt_id = p.prdt_id
        """,
    )
    show(
        "H03 occ retire female age>=60 aset>10w by org",
        """
        WITH aset AS (
          SELECT pty_id, coalesce(nm_tot_aset,0)+coalesce(fc_pur_aset,0) AS total_aset
          FROM dws_cust_aset_d WHERE data_dt='20260331'
        )
        SELECT COUNT(*)
        FROM ads_cust_info_d a
        JOIN dim_public o ON a.prof_cd=o.code AND o.code_type_id='700'
        JOIN dim_public g ON a.gender_cd=g.code AND g.code_type_id='500'
        JOIN aset s ON a.pty_id=s.pty_id
        JOIN dim_branch b ON a.org_id=b.org_id
        WHERE o."describe"='非公职 离/退休' AND g."describe"='女'
          AND a.cust_age >= 60 AND s.total_aset > 100000
        """,
    )
    show(
        "H04 cash_in>10w and hold fund",
        """
        WITH fin AS (
          SELECT pty_id FROM dws_cust_fin_d
          WHERE data_dt BETWEEN '20260101' AND '20260331'
          GROUP BY pty_id HAVING SUM(coalesce(cash_in,0)) > 100000
        ),
        hold AS (
          SELECT DISTINCT h.pty_id
          FROM dwd_cust_hold_d h
          JOIN dim_product p ON h.prdt_id=p.prdt_id
          WHERE h.data_dt='20260331' AND p.up_prdt_type_id='PT050000'
        )
        SELECT COUNT(*) FROM fin f JOIN hold h ON f.pty_id=h.pty_id
        """,
    )
    show(
        "H05 fc A股 trade Q1 amt",
        """
        SELECT COUNT(DISTINCT t.pty_id), SUM(coalesce(t.buy_amt,0)+coalesce(t.sell_amt,0))
        FROM dwd_cust_tran_d t
        JOIN dim_product p ON t.prdt_id=p.prdt_id
        WHERE t.data_dt BETWEEN '20260101' AND '20260331'
          AND t.sys_source='fc' AND p.prdt_type_name='A股'
        """,
    )
    show(
        "H06 rake>100 and buy_cnt+sell_cnt>10 by org",
        """
        WITH active AS (
          SELECT pty_id
          FROM dwd_cust_tran_d
          WHERE data_dt BETWEEN '20260101' AND '20260331'
          GROUP BY pty_id
          HAVING SUM(coalesce(buy_rake,0)+coalesce(sell_rake,0)) > 100
             AND SUM(coalesce(buy_cnt,0)+coalesce(sell_cnt,0)) > 10
        )
        SELECT COUNT(*), COUNT(DISTINCT b.org_name)
        FROM active a
        JOIN ads_cust_info_d c ON a.pty_id=c.pty_id
        JOIN dim_branch b ON c.org_id=b.org_id
        """,
    )
    show(
        "H07 top5 branch trade",
        """
        SELECT b.org_name, SUM(coalesce(t.buy_amt,0)+coalesce(t.sell_amt,0)) AS amt
        FROM dwd_cust_tran_d t
        JOIN ads_cust_info_d c ON t.pty_id=c.pty_id
        JOIN dim_branch b ON c.org_id=b.org_id
        WHERE t.data_dt BETWEEN '20260101' AND '20260331'
        GROUP BY b.org_name
        ORDER BY amt DESC
        LIMIT 5
        """,
    )
    show(
        "H10 华昌化工 trade + 海陆重工 hold",
        """
        WITH t AS (
          SELECT DISTINCT t.pty_id FROM dwd_cust_tran_d t
          JOIN dim_product p ON t.prdt_id=p.prdt_id
          WHERE t.data_dt BETWEEN '20260101' AND '20260331' AND p.prdt_name='华昌化工'
        ),
        h AS (
          SELECT DISTINCT h.pty_id FROM dwd_cust_hold_d h
          JOIN dim_product p ON h.prdt_id=p.prdt_id
          WHERE h.data_dt='20260331' AND h.sys_source='nm' AND p.prdt_name='海陆重工'
        )
        SELECT COUNT(*) FROM t JOIN h ON t.pty_id=h.pty_id
        """,
    )


if __name__ == "__main__":
    main()
