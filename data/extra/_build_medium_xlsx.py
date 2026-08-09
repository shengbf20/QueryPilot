"""Build and validate data/extra/Q&A_medium.xlsx (Step 2c)."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from querypilot.db import execute
from querypilot.eval.dataset import load_qa_cases

OUT = Path(__file__).with_name("Q&A_medium.xlsx")

CASES: list[dict[str, str]] = [
    {
        "id": "M01",
        "theme": "credit_hold",
        "difficulty": "中等",
        "question": "信用账户持有三六零的客户有多少人？",
        "sql": """
SELECT COUNT(DISTINCT h.pty_id) AS cnt
FROM dwd_cust_hold_d AS h
JOIN dim_product AS p ON h.prdt_id = p.prdt_id
WHERE h.data_dt = '20260331'
  AND h.sys_source = 'fc'
  AND p.prdt_name = '三六零'
""".strip(),
    },
    {
        "id": "M02",
        "theme": "credit_tran",
        "difficulty": "中等",
        "question": "2026年一季度信用账户买卖交易金额合计超过10万元的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM (
  SELECT pty_id
  FROM dwd_cust_tran_d
  WHERE data_dt BETWEEN '20260101' AND '20260331'
    AND sys_source = 'fc'
  GROUP BY pty_id
  HAVING SUM(coalesce(buy_amt, 0) + coalesce(sell_amt, 0)) > 100000
) AS t
""".strip(),
    },
    {
        "id": "M03",
        "theme": "sell_only_amt",
        "difficulty": "中等",
        "question": "2026年一季度卖出金额合计超过10万元的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM (
  SELECT pty_id
  FROM dwd_cust_tran_d
  WHERE data_dt BETWEEN '20260101' AND '20260331'
  GROUP BY pty_id
  HAVING SUM(coalesce(sell_amt, 0)) > 100000
) AS t
""".strip(),
    },
    {
        "id": "M04",
        "theme": "buy_cnt",
        "difficulty": "中等",
        "question": "2026年一季度买入笔数合计大于5笔的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM (
  SELECT pty_id
  FROM dwd_cust_tran_d
  WHERE data_dt BETWEEN '20260101' AND '20260331'
  GROUP BY pty_id
  HAVING SUM(coalesce(buy_cnt, 0)) > 5
) AS t
""".strip(),
    },
    {
        "id": "M05",
        "theme": "commission",
        "difficulty": "中等",
        "question": "2026年一季度买卖佣金合计超过100元的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM (
  SELECT pty_id
  FROM dwd_cust_tran_d
  WHERE data_dt BETWEEN '20260101' AND '20260331'
  GROUP BY pty_id
  HAVING SUM(coalesce(buy_rake, 0) + coalesce(sell_rake, 0)) > 100
) AS t
""".strip(),
    },
    {
        "id": "M06",
        "theme": "ccy_hold",
        "difficulty": "中等",
        "question": "2026年3月31日港币持仓的市值合计是多少？",
        "sql": """
SELECT SUM(coalesce(mkt_val, 0)) AS mkt_sum
FROM dwd_cust_hold_d
WHERE data_dt = '20260331'
  AND ccy = '2'
""".strip(),
    },
    {
        "id": "M07",
        "theme": "cash_in_large",
        "difficulty": "中等",
        "question": "2026年一季度现金转入合计超过10万元的客户有哪些？",
        "sql": """
SELECT pty_id
FROM dws_cust_fin_d
WHERE data_dt BETWEEN '20260101' AND '20260331'
GROUP BY pty_id
HAVING SUM(coalesce(cash_in, 0)) > 100000
ORDER BY pty_id
""".strip(),
    },
    {
        "id": "M08",
        "theme": "cash_out_large",
        "difficulty": "中等",
        "question": "2026年一季度现金转出合计超过10万元的客户有哪些？",
        "sql": """
SELECT pty_id
FROM dws_cust_fin_d
WHERE data_dt BETWEEN '20260101' AND '20260331'
GROUP BY pty_id
HAVING SUM(coalesce(cash_out, 0)) > 100000
ORDER BY pty_id
""".strip(),
    },
    {
        "id": "M09",
        "theme": "fund_or_bond_type",
        "difficulty": "中等",
        "question": "2026年3月31日持仓中属于开放式基金的市值合计是多少？",
        "sql": """
SELECT SUM(coalesce(h.mkt_val, 0)) AS mkt_sum
FROM dwd_cust_hold_d AS h
JOIN dim_product AS p ON h.prdt_id = p.prdt_id
WHERE h.data_dt = '20260331'
  AND p.up_prdt_type_id = 'PT050000'
""".strip(),
    },
    {
        "id": "M10",
        "theme": "sor_prdt_id",
        "difficulty": "中等",
        "question": "持有产品代码940018的客户在2026年3月31日有多少人？",
        "sql": """
SELECT COUNT(DISTINCT h.pty_id) AS cnt
FROM dwd_cust_hold_d AS h
JOIN dim_product AS p ON h.prdt_id = p.prdt_id
WHERE h.data_dt = '20260331'
  AND p.sor_prdt_id = '940018'
""".strip(),
    },
    {
        "id": "M11",
        "theme": "nm_vs_total",
        "difficulty": "中等",
        "question": "在2026年3月31日，本币总资产不超过50万、但本外币合计总资产超过50万的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM dws_cust_aset_d
WHERE data_dt = '20260331'
  AND coalesce(nm_tot_aset, 0) <= 500000
  AND coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) > 500000
""".strip(),
    },
    {
        "id": "M12",
        "theme": "trade_window_custom",
        "difficulty": "中等",
        "question": "2026年1月20日至2月28日期间，客户买卖交易金额合计是多少？",
        "sql": """
SELECT SUM(coalesce(buy_amt, 0) + coalesce(sell_amt, 0)) AS trade_amt
FROM dwd_cust_tran_d
WHERE data_dt BETWEEN '20260120' AND '20260228'
""".strip(),
    },
    {
        "id": "M13",
        "theme": "branch_trade_amt",
        "difficulty": "中等",
        "question": "2026年一季度各营业部客户买卖交易金额合计分别是多少？",
        "sql": """
SELECT b.org_name, SUM(coalesce(t.buy_amt, 0) + coalesce(t.sell_amt, 0)) AS trade_amt
FROM dwd_cust_tran_d AS t
JOIN ads_cust_info_d AS c ON t.pty_id = c.pty_id
JOIN dim_branch AS b ON c.org_id = b.org_id
WHERE t.data_dt BETWEEN '20260101' AND '20260331'
GROUP BY b.org_name
ORDER BY trade_amt DESC, b.org_name
""".strip(),
    },
    {
        "id": "M14",
        "theme": "max_data_dt_snapshot",
        "difficulty": "中等",
        "question": "按最新资产快照日统计，总资产超过100万的客户有多少人？",
        "sql": """
WITH latest AS (
  SELECT MAX(data_dt) AS data_dt FROM dws_cust_aset_d
),
aset AS (
  SELECT
    a.pty_id,
    coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0) AS total_aset
  FROM dws_cust_aset_d AS a
  JOIN latest AS l ON a.data_dt = l.data_dt
)
SELECT COUNT(*) AS cnt
FROM aset
WHERE total_aset > 1000000
""".strip(),
    },
]


def _ok_result(sql: str, row_count: int, first_row) -> bool:
    upper = sql.upper()
    if "GROUP BY" in upper or "ORDER BY" in upper and "COUNT(*)" not in upper.split("FROM")[0]:
        # list / group results
        if "COUNT(*)" in upper and "GROUP BY" not in upper:
            return row_count == 1 and first_row is not None and int(first_row[0]) > 0
        return row_count >= 1
    if first_row is None:
        return False
    val = first_row[0]
    if val is None:
        return False
    try:
        return float(val) != 0
    except (TypeError, ValueError):
        return True


def main() -> None:
    print("=== execute + non-empty check ===")
    for case in CASES:
        r = execute(case["sql"], max_rows=2000)
        preview = r.rows[0] if r.rows else None
        ok = _ok_result(case["sql"], r.row_count, preview)
        # refine COUNT-only
        if case["sql"].lstrip().upper().startswith("SELECT COUNT"):
            ok = r.row_count == 1 and preview is not None and int(preview[0]) > 0
        if case["id"] in {"M06", "M09", "M12"}:
            ok = r.row_count == 1 and preview is not None and float(preview[0]) > 0
        if case["id"] in {"M07", "M08", "M13"}:
            ok = r.row_count >= 1
        status = "OK" if ok else "FAIL"
        print(f"{status} {case['id']} rows={r.row_count} preview={preview}")
        if not ok:
            raise SystemExit(f"non-empty check failed: {case['id']}")

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["序号", "问题", "SQL", "难度", "theme"])
    for case in CASES:
        ws.append(
            [case["id"], case["question"], case["sql"], case["difficulty"], case["theme"]]
        )
    wb.save(OUT)
    print(f"wrote {OUT}")

    loaded = load_qa_cases(OUT)
    assert len(loaded) == 14, len(loaded)
    assert [c.id for c in loaded] == [c["id"] for c in CASES]
    assert all(c.difficulty == "中等" for c in loaded)
    assert all(c.extras.get("theme") for c in loaded)

    import yaml

    shots = {
        e["question"].strip()
        for e in yaml.safe_load(
            Path("metadata/few_shots/examples.yaml").read_text(encoding="utf-8")
        )["examples"]
    }
    overlap = [c.id for c in loaded if c.question.strip() in shots]
    assert not overlap, overlap
    print("load_qa_cases OK:", [(c.id, c.extras.get("theme")) for c in loaded])
    print("few-shot overlap:", overlap)


if __name__ == "__main__":
    main()
