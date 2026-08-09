"""Deep-dive Extra-A failures for Step 4 attribution."""

from __future__ import annotations

import json
from pathlib import Path

from querypilot.db import execute

REPORT = Path("logs/eval_reports/extra_all_A_report.json")
OUT = Path("logs/eval_reports/extra_all_A_fail_detail.txt")
FAILED = {"E02", "M08", "M11", "H03", "H05", "H11"}


def main() -> None:
    rep = json.loads(REPORT.read_text(encoding="utf-8"))
    lines: list[str] = []
    for r in rep["results"]:
        if r["case_id"] not in FAILED:
            continue
        lines.append("=" * 60)
        lines.append(
            f"ID={r['case_id']} matched={r['matched']} stage={r['stage']} "
            f"error={r.get('error')}"
        )
        lines.append(f"Q: {r['question']}")
        lines.append("--- GOLD ---")
        lines.append(r.get("gold_sql") or "")
        lines.append("--- PRED ---")
        lines.append(r.get("pred_sql") or "")
        g = r.get("gold_sql") or ""
        p = r.get("pred_sql") or ""
        if g and r.get("gold_ok"):
            try:
                gr = execute(g, max_rows=5)
                lines.append(
                    f"gold exec rows={gr.row_count} cols={list(gr.columns)} sample={gr.rows[:2]}"
                )
            except Exception as exc:  # noqa: BLE001
                lines.append(f"gold exec err {exc}")
        if p and r.get("ask_ok"):
            try:
                pr = execute(p, max_rows=5)
                lines.append(
                    f"pred exec rows={pr.row_count} cols={list(pr.columns)} sample={pr.rows[:2]}"
                )
            except Exception as exc:  # noqa: BLE001
                lines.append(f"pred exec err {exc}")

        # Extra probes for root cause
        if r["case_id"] == "E02":
            for sql, label in [
                (
                    """
                    SELECT COUNT(*) FROM ads_cust_info_d a
                    JOIN dim_public o ON a.prof_cd=o.code AND o.code_type_id='700'
                    JOIN dim_public g ON a.gender_cd=g.code AND g.code_type_id='500'
                    WHERE g."describe"='女' AND o."describe"='非公职 离/退休'
                    """,
                    "exact describe",
                ),
                (
                    """
                    SELECT COUNT(*) FROM ads_cust_info_d a
                    WHERE a.gender_cd='5000003' AND a.prof_cd='7000032'
                    """,
                    "code direct",
                ),
                (
                    """
                    SELECT COUNT(*) FROM ads_cust_info_d a
                    JOIN dim_public o ON a.prof_cd=o.code AND o.code_type_id='700'
                    JOIN dim_public g ON a.gender_cd=g.code AND g.code_type_id='500'
                    WHERE g."describe"='女' AND replace(o."describe",' ','') LIKE '%非公职%离%退休%'
                    """,
                    "fuzzy describe",
                ),
            ]:
                rr = execute(sql)
                lines.append(f"probe E02 {label}: {rr.rows}")

        if r["case_id"] == "M08":
            for sql, label in [
                (
                    """
                    SELECT COUNT(*) FROM (
                      SELECT pty_id FROM dws_cust_fin_d
                      WHERE data_dt BETWEEN '20260101' AND '20260331'
                      GROUP BY pty_id HAVING SUM(coalesce(cash_out,0)) > 100000
                    )
                    """,
                    "cash_out>10w",
                ),
                (
                    """
                    SELECT COUNT(*) FROM (
                      SELECT pty_id FROM dws_cust_fin_d
                      WHERE data_dt BETWEEN '20260101' AND '20260331'
                      GROUP BY pty_id
                      HAVING SUM(coalesce(cash_out,0)+coalesce(tran_out,0)+coalesce(assign_out,0)) > 100000
                    )
                    """,
                    "all_out>10w",
                ),
                (
                    """
                    SELECT COUNT(*) FROM (
                      SELECT pty_id FROM dws_cust_fin_d
                      WHERE data_dt BETWEEN '20260101' AND '20260331'
                      GROUP BY pty_id HAVING SUM(coalesce(cash_out,0)) >= 100000
                    )
                    """,
                    "cash_out>=10w",
                ),
            ]:
                rr = execute(sql)
                lines.append(f"probe M08 {label}: {rr.rows}")

        if r["case_id"] == "H05":
            for sql, label in [
                (
                    """
                    SELECT SUM(coalesce(buy_amt,0)+coalesce(sell_amt,0))
                    FROM dwd_cust_tran_d t JOIN dim_product p ON t.prdt_id=p.prdt_id
                    WHERE t.data_dt BETWEEN '20260101' AND '20260331'
                      AND t.sys_source='fc' AND t.ccy='0' AND p.prdt_type_name='A股'
                    """,
                    "fc+cny+A",
                ),
                (
                    """
                    SELECT SUM(coalesce(buy_amt,0)+coalesce(sell_amt,0))
                    FROM dwd_cust_tran_d t JOIN dim_product p ON t.prdt_id=p.prdt_id
                    WHERE t.data_dt BETWEEN '20260101' AND '20260331'
                      AND t.sys_source='fc' AND p.prdt_type_name='A股'
                    """,
                    "fc+A no ccy",
                ),
                (
                    """
                    SELECT SUM(coalesce(buy_amt,0)+coalesce(sell_amt,0))
                    FROM dwd_cust_tran_d t JOIN dim_product p ON t.prdt_id=p.prdt_id
                    WHERE t.data_dt BETWEEN '20260101' AND '20260331'
                      AND t.sys_source='fc' AND p.up_prdt_type_id='PT040000'
                    """,
                    "fc+stock up type",
                ),
            ]:
                rr = execute(sql)
                lines.append(f"probe H05 {label}: {rr.rows}")

        if r["case_id"] == "H11":
            for sql, label in [
                (
                    """
                    SELECT COUNT(*) FROM (
                      SELECT pty_id FROM dwd_cust_tran_d
                      WHERE data_dt BETWEEN '20260101' AND '20260331'
                      GROUP BY pty_id HAVING SUM(coalesce(sell_amt,0)) > 100000
                    )
                    """,
                    "sell>10w Q1",
                ),
                (
                    """
                    SELECT COUNT(*) FROM (
                      SELECT pty_id FROM dwd_cust_tran_d
                      WHERE data_dt BETWEEN '20260101' AND '20260331'
                      GROUP BY pty_id HAVING SUM(coalesce(sell_amt,0)) >= 100000
                    )
                    """,
                    "sell>=10w",
                ),
                (
                    """
                    SELECT COUNT(*) FROM (
                      SELECT pty_id FROM dwd_cust_tran_d
                      WHERE data_dt BETWEEN '20260101' AND '20260331'
                      GROUP BY pty_id
                      HAVING SUM(coalesce(buy_amt,0)+coalesce(sell_amt,0)) > 100000
                    )
                    """,
                    "buy+sell>10w",
                ),
            ]:
                rr = execute(sql)
                lines.append(f"probe H11 {label}: {rr.rows}")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
