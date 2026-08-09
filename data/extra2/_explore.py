"""Extra2 Step S2 exploration; writes UTF-8 report next to this file."""

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
        "cust_type raw",
        """
        SELECT cust_type, COUNT(*) n FROM ads_cust_info_d
        WHERE data_dt='20260531' GROUP BY 1 ORDER BY n DESC LIMIT 20
        """,
    )
    show(
        "cust_type with dim_public any type",
        """
        SELECT a.cust_type, p.code_type_id, p."describe", COUNT(*) n
        FROM ads_cust_info_d a
        LEFT JOIN dim_public p ON a.cust_type = p.code
        WHERE a.data_dt='20260531'
        GROUP BY 1,2,3 ORDER BY n DESC LIMIT 30
        """,
    )
    show(
        "status non-normal",
        """
        SELECT a.cust_status, p."describe", COUNT(*) n
        FROM ads_cust_info_d a
        LEFT JOIN dim_public p ON a.cust_status=p.code AND p.code_type_id='200'
        WHERE a.data_dt='20260531' AND a.cust_status <> '2000001'
        GROUP BY 1,2 ORDER BY n DESC
        """,
    )
    show(
        "city top",
        """
        SELECT city_name, COUNT(*) n FROM ads_cust_info_d
        WHERE data_dt='20260531' GROUP BY 1 ORDER BY n DESC LIMIT 15
        """,
    )
    show(
        "up_org",
        """
        SELECT b.up_org_name, COUNT(DISTINCT a.pty_id) n
        FROM ads_cust_info_d a
        JOIN dim_branch b ON a.org_id=b.org_id
        WHERE a.data_dt='20260531'
        GROUP BY 1 ORDER BY n DESC LIMIT 15
        """,
    )
    show(
        "branch top",
        """
        SELECT b.org_name, COUNT(DISTINCT a.pty_id) n
        FROM ads_cust_info_d a
        JOIN dim_branch b ON a.org_id=b.org_id
        WHERE a.data_dt='20260531'
        GROUP BY 1 ORDER BY n DESC LIMIT 10
        """,
    )
    show(
        "fc_bal thresholds",
        """
        SELECT
          SUM(CASE WHEN coalesce(fc_bal,0)>0 THEN 1 ELSE 0 END) gt0,
          SUM(CASE WHEN coalesce(fc_bal,0)>1000 THEN 1 ELSE 0 END) gt1k,
          SUM(CASE WHEN coalesce(fc_bal,0)>10000 THEN 1 ELSE 0 END) gt1w,
          SUM(CASE WHEN coalesce(fc_bal,0)>50000 THEN 1 ELSE 0 END) gt5w
        FROM dws_cust_aset_d WHERE data_dt='20260331'
        """,
    )
    show(
        "nm_bal thresholds",
        """
        SELECT
          SUM(CASE WHEN coalesce(nm_bal,0)>50000 THEN 1 ELSE 0 END) gt5w,
          SUM(CASE WHEN coalesce(nm_bal,0)>100000 THEN 1 ELSE 0 END) gt10w
        FROM dws_cust_aset_d WHERE data_dt='20260331'
        """,
    )
    show(
        "hold mkt sum thresholds",
        """
        WITH h AS (
          SELECT pty_id, SUM(coalesce(mkt_val,0)) s FROM dwd_cust_hold_d
          WHERE data_dt='20260331' GROUP BY 1
        )
        SELECT
          SUM(CASE WHEN s>50000 THEN 1 ELSE 0 END) gt5w,
          SUM(CASE WHEN s>100000 THEN 1 ELSE 0 END) gt10w,
          SUM(CASE WHEN s>500000 THEN 1 ELSE 0 END) gt50w
        FROM h
        """,
    )
    show(
        "fare Q1",
        """
        WITH t AS (
          SELECT pty_id, SUM(coalesce(buy_fare,0)+coalesce(sell_fare,0)) f
          FROM dwd_cust_tran_d
          WHERE data_dt BETWEEN '20260101' AND '20260331'
          GROUP BY 1
        )
        SELECT
          SUM(CASE WHEN f>10 THEN 1 ELSE 0 END) gt10,
          SUM(CASE WHEN f>50 THEN 1 ELSE 0 END) gt50,
          SUM(CASE WHEN f>100 THEN 1 ELSE 0 END) gt100,
          SUM(CASE WHEN f>200 THEN 1 ELSE 0 END) gt200
        FROM t
        """,
    )
    show(
        "assign Q1",
        """
        WITH f AS (
          SELECT pty_id,
            SUM(coalesce(assign_in,0)) ai, SUM(coalesce(assign_out,0)) ao
          FROM dws_cust_fin_d
          WHERE data_dt BETWEEN '20260101' AND '20260331'
          GROUP BY 1
        )
        SELECT
          SUM(CASE WHEN ai>0 THEN 1 ELSE 0 END) ai_any,
          SUM(CASE WHEN ao>0 THEN 1 ELSE 0 END) ao_any,
          SUM(CASE WHEN ai>1000 THEN 1 ELSE 0 END) ai_1k,
          SUM(CASE WHEN ao>1000 THEN 1 ELSE 0 END) ao_1k,
          SUM(CASE WHEN ai>10000 THEN 1 ELSE 0 END) ai_1w,
          SUM(CASE WHEN ao>10000 THEN 1 ELSE 0 END) ao_1w
        FROM f
        """,
    )
    show(
        "product hold not 天天发",
        """
        SELECT p.prdt_name, p.sor_prdt_id, COUNT(DISTINCT h.pty_id) n
        FROM dwd_cust_hold_d h
        JOIN dim_product p ON h.prdt_id=p.prdt_id
        WHERE h.data_dt='20260331' AND p.prdt_name NOT LIKE '%天天发%'
        GROUP BY 1,2 ORDER BY n DESC LIMIT 25
        """,
    )
    show(
        "fc hold products",
        """
        SELECT p.prdt_name, COUNT(DISTINCT h.pty_id) n
        FROM dwd_cust_hold_d h
        JOIN dim_product p ON h.prdt_id=p.prdt_id
        WHERE h.data_dt='20260331' AND h.sys_source='fc'
        GROUP BY 1 ORDER BY n DESC LIMIT 15
        """,
    )
    show(
        "up_prdt types",
        """
        SELECT p.up_prdt_type_name, p.up_prdt_type_id, COUNT(DISTINCT h.pty_id) n
        FROM dwd_cust_hold_d h JOIN dim_product p ON h.prdt_id=p.prdt_id
        WHERE h.data_dt='20260331'
        GROUP BY 1,2 ORDER BY n DESC
        """,
    )
    show(
        "prdt_type_name top",
        """
        SELECT p.prdt_type_name, COUNT(DISTINCT h.pty_id) n
        FROM dwd_cust_hold_d h JOIN dim_product p ON h.prdt_id=p.prdt_id
        WHERE h.data_dt='20260331'
        GROUP BY 1 ORDER BY n DESC LIMIT 15
        """,
    )
    show(
        "edu",
        """
        SELECT p."describe", a.edu_cd, COUNT(*) n
        FROM ads_cust_info_d a
        JOIN dim_public p ON a.edu_cd=p.code AND p.code_type_id='600'
        WHERE a.data_dt='20260531'
        GROUP BY 1,2 ORDER BY n DESC
        """,
    )
    show(
        "lvl",
        """
        SELECT p."describe", a.cust_lvl_cd, COUNT(*) n
        FROM ads_cust_info_d a
        JOIN dim_public p ON a.cust_lvl_cd=p.code AND p.code_type_id='100'
        WHERE a.data_dt='20260531'
        GROUP BY 1,2 ORDER BY n DESC
        """,
    )
    show(
        "age 40-50",
        """
        SELECT COUNT(*) n FROM ads_cust_info_d
        WHERE data_dt='20260531' AND cust_age>=40 AND cust_age<50
        """,
    )
    show(
        "window Jan15-Feb15 trade",
        """
        SELECT COUNT(DISTINCT pty_id) n,
          SUM(CASE WHEN coalesce(buy_amt,0)+coalesce(sell_amt,0)>0 THEN 1 ELSE 0 END)
        FROM dwd_cust_tran_d
        WHERE data_dt BETWEEN '20260115' AND '20260215'
        """,
    )
    show(
        "same product trade and hold Q1",
        """
        WITH tr AS (
          SELECT DISTINCT pty_id, prdt_id FROM dwd_cust_tran_d
          WHERE data_dt BETWEEN '20260101' AND '20260331'
        ),
        ho AS (
          SELECT DISTINCT pty_id, prdt_id FROM dwd_cust_hold_d
          WHERE data_dt='20260331'
        )
        SELECT COUNT(*) n FROM tr JOIN ho USING (pty_id, prdt_id)
        """,
    )
    show(
        "same product top names",
        """
        WITH tr AS (
          SELECT DISTINCT pty_id, prdt_id FROM dwd_cust_tran_d
          WHERE data_dt BETWEEN '20260101' AND '20260331'
        ),
        ho AS (
          SELECT DISTINCT pty_id, prdt_id FROM dwd_cust_hold_d
          WHERE data_dt='20260331'
        )
        SELECT p.prdt_name, COUNT(*) n
        FROM tr JOIN ho USING (pty_id, prdt_id)
        JOIN dim_product p ON tr.prdt_id=p.prdt_id
        GROUP BY 1 ORDER BY n DESC LIMIT 15
        """,
    )
    show(
        "cash net in Q1",
        """
        WITH f AS (
          SELECT pty_id,
            SUM(coalesce(cash_in,0)-coalesce(cash_out,0)) net
          FROM dws_cust_fin_d
          WHERE data_dt BETWEEN '20260101' AND '20260331'
          GROUP BY 1
        )
        SELECT
          SUM(CASE WHEN net>50000 THEN 1 ELSE 0 END) gt5w,
          SUM(CASE WHEN net>100000 THEN 1 ELSE 0 END) gt10w,
          SUM(CASE WHEN net>200000 THEN 1 ELSE 0 END) gt20w
        FROM f
        """,
    )
    show(
        "sell Q1 hav count sample",
        """
        SELECT COUNT(*) AS people FROM (
          SELECT pty_id FROM dwd_cust_tran_d
          WHERE data_dt BETWEEN '20260101' AND '20260331'
          GROUP BY pty_id
          HAVING SUM(coalesce(sell_amt,0)) > 200000
        ) t
        """,
    )
    show(
        "buy window 0115-0215",
        """
        SELECT COUNT(*) AS people FROM (
          SELECT pty_id FROM dwd_cust_tran_d
          WHERE data_dt BETWEEN '20260115' AND '20260215'
          GROUP BY pty_id
          HAVING SUM(coalesce(buy_amt,0)) > 50000
        ) t
        """,
    )
    show(
        "fc tran window 0115-0215",
        """
        SELECT COUNT(*) AS people FROM (
          SELECT pty_id FROM dwd_cust_tran_d
          WHERE data_dt BETWEEN '20260115' AND '20260215' AND sys_source='fc'
          GROUP BY pty_id
          HAVING SUM(coalesce(buy_amt,0)+coalesce(sell_amt,0)) > 50000
        ) t
        """,
    )
    show(
        "gold lvl female",
        """
        SELECT COUNT(*) n
        FROM ads_cust_info_d a
        JOIN dim_public l ON a.cust_lvl_cd=l.code AND l.code_type_id='100'
        JOIN dim_public g ON a.gender_cd=g.code AND g.code_type_id='500'
        WHERE a.data_dt='20260531'
          AND l."describe"='紫金理财金卡客户'
          AND g."describe"='女'
        """,
    )
    show(
        "sor_prdt sample not 940018",
        """
        SELECT p.sor_prdt_id, p.prdt_name, COUNT(DISTINCT t.pty_id) n
        FROM dwd_cust_tran_d t
        JOIN dim_product p ON t.prdt_id=p.prdt_id
        WHERE t.data_dt BETWEEN '20260101' AND '20260331'
          AND p.sor_prdt_id <> '940018'
        GROUP BY 1,2 ORDER BY n DESC LIMIT 15
        """,
    )
    show(
        "avg aset Feb window 30d",
        """
        WITH daily AS (
          SELECT pty_id, data_dt,
            coalesce(nm_tot_aset,0)+coalesce(fc_pur_aset,0) AS total_aset
          FROM dws_cust_aset_d
          WHERE data_dt BETWEEN '20260201' AND '20260228'
        ),
        avg_a AS (
          SELECT pty_id, SUM(total_aset)/28.0 AS avg_aset
          FROM daily GROUP BY 1
        )
        SELECT
          SUM(CASE WHEN avg_aset>200000 THEN 1 ELSE 0 END) gt20w,
          SUM(CASE WHEN avg_aset>300000 THEN 1 ELSE 0 END) gt30w,
          SUM(CASE WHEN avg_aset>500000 THEN 1 ELSE 0 END) gt50w
        FROM avg_a
        """,
    )
    show(
        "two window trade cmp sample",
        """
        WITH w1 AS (
          SELECT pty_id, SUM(coalesce(buy_amt,0)+coalesce(sell_amt,0)) amt
          FROM dwd_cust_tran_d
          WHERE data_dt BETWEEN '20260101' AND '20260131' GROUP BY 1
        ),
        w2 AS (
          SELECT pty_id, SUM(coalesce(buy_amt,0)+coalesce(sell_amt,0)) amt
          FROM dwd_cust_tran_d
          WHERE data_dt BETWEEN '20260301' AND '20260331' GROUP BY 1
        )
        SELECT COUNT(*) n
        FROM w1 JOIN w2 USING (pty_id)
        WHERE w2.amt > w1.amt AND w2.amt > 100000
        """,
    )
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} lines={len(lines)}")


if __name__ == "__main__":
    main()
