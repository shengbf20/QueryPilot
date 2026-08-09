"""One-off probe for M09 product level."""
from __future__ import annotations

import duckdb

from querypilot.config import get_settings


def main() -> None:
    con = duckdb.connect(str(get_settings().db_path), read_only=True)
    rows = con.execute(
        """
        SELECT DISTINCT up_prdt_type_id, up_prdt_type_name, prdt_type_id, prdt_type_name
        FROM dim_product
        WHERE up_prdt_type_name LIKE '%开放%'
           OR prdt_type_name LIKE '%开放%'
           OR up_prdt_type_id = 'PT050000'
        ORDER BY 1, 3
        """
    ).fetchall()
    for r in rows:
        print(r)

    gold = con.execute(
        """
        SELECT SUM(coalesce(h.mkt_val, 0))
        FROM dwd_cust_hold_d h
        JOIN dim_product p ON h.prdt_id = p.prdt_id
        WHERE h.data_dt = '20260331' AND p.up_prdt_type_id = 'PT050000'
        """
    ).fetchone()[0]
    wrong = con.execute(
        """
        SELECT SUM(coalesce(h.mkt_val, 0))
        FROM dwd_cust_hold_d h
        JOIN dim_product p ON h.prdt_id = p.prdt_id
        WHERE h.data_dt = '20260331' AND p.prdt_type_name = '开放式基金'
        """
    ).fetchone()[0]
    by_up_name = con.execute(
        """
        SELECT SUM(coalesce(h.mkt_val, 0))
        FROM dwd_cust_hold_d h
        JOIN dim_product p ON h.prdt_id = p.prdt_id
        WHERE h.data_dt = '20260331' AND p.up_prdt_type_name = '开放式基金'
        """
    ).fetchone()[0]
    print("gold_PT050000", gold)
    print("prdt_type_name", wrong)
    print("up_prdt_type_name", by_up_name)
    print(
        "counts",
        con.execute(
            "SELECT COUNT(*) FROM dim_product WHERE up_prdt_type_name='开放式基金'"
        ).fetchone()[0],
        con.execute(
            "SELECT COUNT(*) FROM dim_product WHERE prdt_type_name='开放式基金'"
        ).fetchone()[0],
    )


if __name__ == "__main__":
    main()
