"""Probe non-empty sizes for Extra2 hard/medium gold drafts."""

from __future__ import annotations

from querypilot.db import execute


def show(title: str, sql: str) -> None:
    r = execute(sql, max_rows=20)
    print(f"### {title} row_count={r.row_count}")
    for row in r.rows[:15]:
        print(row)
    print()


def main() -> None:
    show(
        "bond mkt sum",
        """
        SELECT COUNT(DISTINCT h.pty_id) AS custs,
               SUM(coalesce(h.mkt_val,0)) AS mkt
        FROM dwd_cust_hold_d h
        JOIN dim_product p ON h.prdt_id = p.prdt_id
        WHERE h.data_dt = '20260331' AND p.up_prdt_type_id = 'PT030000'
        """,
    )
    show(
        "FH01 gold card + 特变电工 hold mkt>0 Q1 pnl rows",
        """
        WITH cohort AS (
          SELECT DISTINCT a.pty_id
          FROM ads_cust_info_d a
          JOIN dim_public l ON a.cust_lvl_cd = l.code AND l.code_type_id = '100'
          JOIN dwd_cust_hold_d h ON a.pty_id = h.pty_id
          JOIN dim_product p ON h.prdt_id = p.prdt_id
          WHERE a.data_dt = '20260531'
            AND l."describe" = '紫金理财金卡客户'
            AND h.data_dt = '20260331'
            AND p.prdt_name = '特变电工'
            AND coalesce(h.mkt_val, 0) > 0
        )
        SELECT COUNT(*) FROM cohort
        """,
    )
    show(
        "FH01 platinum + 创业板 hold",
        """
        SELECT COUNT(DISTINCT a.pty_id)
        FROM ads_cust_info_d a
        JOIN dim_public l ON a.cust_lvl_cd = l.code AND l.code_type_id = '100'
        JOIN dwd_cust_hold_d h ON a.pty_id = h.pty_id
        JOIN dim_product p ON h.prdt_id = p.prdt_id
        WHERE a.data_dt = '20260531'
          AND l."describe" = '紫金理财白金卡客户'
          AND h.data_dt = '20260331'
          AND p.prdt_type_name = '创业板'
          AND coalesce(h.mkt_val, 0) > 1000
        """,
    )
    show(
        "FH02 feb avg>20w and hold fund type",
        """
        WITH daily AS (
          SELECT pty_id, coalesce(nm_tot_aset,0)+coalesce(fc_pur_aset,0) AS total_aset
          FROM dws_cust_aset_d
          WHERE data_dt BETWEEN '20260201' AND '20260228'
        ),
        avg_a AS (
          SELECT pty_id, SUM(total_aset)/28.0 AS avg_aset FROM daily GROUP BY 1
          HAVING SUM(total_aset)/28.0 > 200000
        ),
        hold_t AS (
          SELECT DISTINCT h.pty_id, p.up_prdt_type_name
          FROM dwd_cust_hold_d h
          JOIN dim_product p ON h.prdt_id = p.prdt_id
          WHERE h.data_dt = '20260331' AND p.up_prdt_type_id = 'PT050000'
        )
        SELECT COUNT(*) FROM avg_a JOIN hold_t USING (pty_id)
        """,
    )
    show(
        "FH03 age40-50 aset>10w city",
        """
        WITH aset AS (
          SELECT pty_id, coalesce(nm_tot_aset,0)+coalesce(fc_pur_aset,0) AS total_aset
          FROM dws_cust_aset_d WHERE data_dt='20260331'
        )
        SELECT a.city_name, COUNT(*) n
        FROM ads_cust_info_d a
        JOIN aset s ON a.pty_id = s.pty_id
        WHERE a.data_dt='20260531' AND a.cust_age>=40 AND a.cust_age<50
          AND s.total_aset > 100000
        GROUP BY 1 ORDER BY n DESC
        """,
    )
    show(
        "FH04 netin>5w and stock trade Q1",
        """
        WITH fin AS (
          SELECT pty_id, SUM(coalesce(cash_in,0)-coalesce(cash_out,0)) net
          FROM dws_cust_fin_d
          WHERE data_dt BETWEEN '20260101' AND '20260331'
          GROUP BY 1 HAVING SUM(coalesce(cash_in,0)-coalesce(cash_out,0)) > 50000
        ),
        tr AS (
          SELECT DISTINCT t.pty_id
          FROM dwd_cust_tran_d t
          JOIN dim_product p ON t.prdt_id = p.prdt_id
          WHERE t.data_dt BETWEEN '20260101' AND '20260331'
            AND p.up_prdt_type_id = 'PT040000'
        )
        SELECT COUNT(*) FROM fin JOIN tr USING (pty_id)
        """,
    )
    show(
        "FH05 fc A股 window 0115-0215",
        """
        SELECT COUNT(*) FROM (
          SELECT t.pty_id
          FROM dwd_cust_tran_d t
          JOIN dim_product p ON t.prdt_id = p.prdt_id
          WHERE t.data_dt BETWEEN '20260115' AND '20260215'
            AND t.sys_source='fc' AND p.prdt_type_name='A股'
          GROUP BY t.pty_id
          HAVING SUM(coalesce(buy_amt,0)+coalesce(sell_amt,0)) > 10000
        )
        """,
    )
    show(
        "FH06 gold card high rake org",
        """
        WITH rake AS (
          SELECT pty_id,
            SUM(coalesce(buy_rake,0)+coalesce(sell_rake,0)) rk,
            SUM(coalesce(buy_cnt,0)+coalesce(sell_cnt,0)) cnt
          FROM dwd_cust_tran_d
          WHERE data_dt BETWEEN '20260101' AND '20260331'
          GROUP BY 1
          HAVING SUM(coalesce(buy_rake,0)+coalesce(sell_rake,0)) > 100
             AND SUM(coalesce(buy_cnt,0)+coalesce(sell_cnt,0)) > 5
        )
        SELECT b.org_name, COUNT(*) n
        FROM rake r
        JOIN ads_cust_info_d a ON r.pty_id = a.pty_id AND a.data_dt='20260531'
        JOIN dim_public l ON a.cust_lvl_cd = l.code AND l.code_type_id='100'
        JOIN dim_branch b ON a.org_id = b.org_id
        WHERE l."describe" = '紫金理财金卡客户'
        GROUP BY 1 ORDER BY n DESC
        """,
    )
    show(
        "FH07 top5 cust trade Q1",
        """
        SELECT a.pty_id, SUM(coalesce(buy_amt,0)+coalesce(sell_amt,0)) amt
        FROM dwd_cust_tran_d t
        JOIN ads_cust_info_d a ON t.pty_id=a.pty_id AND a.data_dt='20260531'
        WHERE t.data_dt BETWEEN '20260101' AND '20260331'
        GROUP BY a.pty_id
        ORDER BY amt DESC, a.pty_id
        LIMIT 5
        """,
    )
    show(
        "FH10 特变电工 same + female",
        """
        WITH tr AS (
          SELECT DISTINCT t.pty_id
          FROM dwd_cust_tran_d t
          JOIN dim_product p ON t.prdt_id=p.prdt_id
          WHERE t.data_dt BETWEEN '20260101' AND '20260331'
            AND p.prdt_name='特变电工'
        ),
        ho AS (
          SELECT DISTINCT h.pty_id
          FROM dwd_cust_hold_d h
          JOIN dim_product p ON h.prdt_id=p.prdt_id
          WHERE h.data_dt='20260331' AND p.prdt_name='特变电工'
        )
        SELECT COUNT(*)
        FROM tr JOIN ho USING (pty_id)
        JOIN ads_cust_info_d a ON tr.pty_id=a.pty_id AND a.data_dt='20260531'
        JOIN dim_public g ON a.gender_cd=g.code AND g.code_type_id='500'
        WHERE g."describe"='男'
        """,
    )
    show(
        "FM15 prov aset>50w",
        """
        WITH aset AS (
          SELECT pty_id, coalesce(nm_tot_aset,0)+coalesce(fc_pur_aset,0) AS total_aset
          FROM dws_cust_aset_d WHERE data_dt='20260331'
        )
        SELECT a.prov_name, COUNT(*) n
        FROM ads_cust_info_d a
        JOIN aset s ON a.pty_id=s.pty_id
        WHERE a.data_dt='20260531' AND s.total_aset > 500000
        GROUP BY 1 ORDER BY n DESC
        """,
    )
    show(
        "FM13 up_org trade Q1",
        """
        SELECT b.up_org_name,
               SUM(coalesce(t.buy_amt,0)+coalesce(t.sell_amt,0)) amt
        FROM dwd_cust_tran_d t
        JOIN ads_cust_info_d a ON t.pty_id=a.pty_id AND a.data_dt='20260531'
        JOIN dim_branch b ON a.org_id=b.org_id
        WHERE t.data_dt BETWEEN '20260101' AND '20260331'
        GROUP BY 1
        ORDER BY amt DESC, b.up_org_name
        """,
    )
    show(
        "edu 大专及以下",
        """
        SELECT COUNT(*) FROM ads_cust_info_d a
        JOIN dim_public p ON a.edu_cd=p.code AND p.code_type_id='600'
        WHERE a.data_dt='20260531'
          AND p."describe" IN ('大专','高中','初中及其以下','中专')
        """,
    )
    show(
        "assign count=0 people",
        """
        SELECT COUNT(*) AS cnt FROM (
          SELECT pty_id FROM dws_cust_fin_d
          WHERE data_dt BETWEEN '20260101' AND '20260331'
          GROUP BY pty_id
          HAVING SUM(coalesce(assign_in,0)) > 0
        )
        """,
    )


if __name__ == "__main__":
    main()
