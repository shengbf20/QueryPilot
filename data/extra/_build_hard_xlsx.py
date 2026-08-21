"""Build and validate data/extra/Q&A_hard.xlsx (Step 2d–2e)."""

from __future__ import annotations

from pathlib import Path

import yaml
from openpyxl import Workbook

from querypilot.db import execute
from querypilot.eval.dataset import load_qa_cases

OUT = Path(__file__).with_name("Q&A_hard.xlsx")
ROOT = Path(__file__).resolve().parents[2]

# H02 SQL reused by H12 paraphrase
_SQL_H02 = """
WITH days AS (
  SELECT (DATE '2026-03-31' - DATE '2026-01-01')::INTEGER + 1 AS d
),
cust_avg AS (
  SELECT
    pty_id,
    SUM(coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0)) / (SELECT d FROM days) AS avg_aset
  FROM dws_cust_aset_d
  WHERE data_dt BETWEEN '20260101' AND '20260331'
  GROUP BY pty_id
  HAVING SUM(coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0)) / (SELECT d FROM days) > 300000
),
cust_tran AS (
  SELECT t.pty_id
  FROM dwd_cust_tran_d AS t
  JOIN dim_product AS p ON t.prdt_id = p.prdt_id
  WHERE t.data_dt BETWEEN '20260101' AND '20260331'
    AND p.up_prdt_type_id = 'PT040000'
  GROUP BY t.pty_id
  HAVING SUM(coalesce(t.buy_amt, 0) + coalesce(t.sell_amt, 0)) > 100000
),
cohort AS (
  SELECT a.pty_id
  FROM cust_avg AS a
  INNER JOIN cust_tran AS t ON a.pty_id = t.pty_id
)
SELECT
  p.up_prdt_type_name,
  p.prdt_type_name,
  SUM(coalesce(h.mkt_val, 0)) AS mkt_val
FROM cohort AS c
INNER JOIN dwd_cust_hold_d AS h
  ON c.pty_id = h.pty_id AND h.data_dt = '20260331'
INNER JOIN dim_product AS p ON h.prdt_id = p.prdt_id
GROUP BY p.up_prdt_type_name, p.prdt_type_name
ORDER BY mkt_val DESC, p.up_prdt_type_name, p.prdt_type_name
""".strip()

_SQL_H01 = """
WITH custinfo AS (
  SELECT a.pty_id
  FROM ads_cust_info_d AS a
  JOIN dim_public AS l
    ON a.cust_lvl_cd = l.code AND l.code_type_id = '100'
  JOIN dim_public AS g
    ON a.gender_cd = g.code AND g.code_type_id = '500'
  WHERE l."describe" = '紫金理财银卡客户'
    AND g."describe" = '男'
),
prdtinfo AS (
  SELECT h.pty_id
  FROM dwd_cust_hold_d AS h
  INNER JOIN dim_product AS p ON h.prdt_id = p.prdt_id
  INNER JOIN custinfo AS z ON h.pty_id = z.pty_id
  WHERE h.data_dt = '20260331'
    AND p.prdt_type_name = 'A股'
  GROUP BY h.pty_id
  HAVING SUM(coalesce(h.mkt_val, 0)) > 1000
)
SELECT
  q.pty_id,
  coalesce(aset_bgn.nm_tot_aset, 0) + coalesce(aset_bgn.fc_pur_aset, 0) AS bgn_aset,
  coalesce(aset_end.nm_tot_aset, 0) + coalesce(aset_end.fc_pur_aset, 0) AS end_aset,
  coalesce(fin.aset_in, 0) AS aset_in,
  coalesce(fin.aset_out, 0) AS aset_out,
  coalesce(aset_end.nm_tot_aset, 0) + coalesce(aset_end.fc_pur_aset, 0)
    - (coalesce(aset_bgn.nm_tot_aset, 0) + coalesce(aset_bgn.fc_pur_aset, 0))
    + coalesce(fin.aset_out, 0) - coalesce(fin.aset_in, 0) AS aset_pft
FROM prdtinfo AS q
LEFT JOIN dws_cust_aset_d AS aset_end
  ON q.pty_id = aset_end.pty_id AND aset_end.data_dt = '20260331'
LEFT JOIN dws_cust_aset_d AS aset_bgn
  ON q.pty_id = aset_bgn.pty_id AND aset_bgn.data_dt = '20260101'
LEFT JOIN (
  SELECT
    pty_id,
    SUM(coalesce(cash_in, 0)) + SUM(coalesce(tran_in, 0)) + SUM(coalesce(assign_in, 0)) AS aset_in,
    SUM(coalesce(cash_out, 0)) + SUM(coalesce(tran_out, 0)) + SUM(coalesce(assign_out, 0)) AS aset_out
  FROM dws_cust_fin_d
  WHERE data_dt BETWEEN '20260101' AND '20260331'
  GROUP BY pty_id
) AS fin ON q.pty_id = fin.pty_id
ORDER BY q.pty_id
""".strip()

_SQL_M03 = """
SELECT COUNT(*) AS cnt
FROM (
  SELECT pty_id
  FROM dwd_cust_tran_d
  WHERE data_dt BETWEEN '20260101' AND '20260331'
  GROUP BY pty_id
  HAVING SUM(coalesce(sell_amt, 0)) > 100000
) AS t
""".strip()

_SQL_M14 = """
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
""".strip()

CASES: list[dict[str, str]] = [
    {
        "id": "H01",
        "theme": "period_pnl_alt",
        "difficulty": "困难",
        "question": (
            "紫金理财银卡男性客户，在2026年3月31日持有A股市值合计超过1000元，"
            "请给出他们在26年Q1的盈亏情况（客户号、期初资产、期末资产、流入、流出、盈亏）"
        ),
        "sql": _SQL_H01,
    },
    {
        "id": "H02",
        "theme": "avg_tran_taxonomy",
        "difficulty": "困难",
        "question": (
            "2026年一季度日均资产大于30万，且股票买卖交易金额合计大于10万的客户，"
            "其在2026年3月31日持仓属于哪些产品大类和二级类型？请给出市值合计"
        ),
        "sql": _SQL_H02,
    },
    {
        "id": "H03",
        "theme": "occ_age_aset_org",
        "difficulty": "困难",
        "question": (
            "职业为非公职离退休、女性、年龄大于等于60岁、且2026年3月31日总资产超过10万的客户，"
            "按营业部分布人数分别是多少？"
        ),
        "sql": """
WITH aset AS (
  SELECT
    pty_id,
    coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) AS total_aset
  FROM dws_cust_aset_d
  WHERE data_dt = '20260331'
)
SELECT b.org_name, COUNT(*) AS cnt
FROM ads_cust_info_d AS a
JOIN dim_public AS o
  ON a.prof_cd = o.code AND o.code_type_id = '700'
JOIN dim_public AS g
  ON a.gender_cd = g.code AND g.code_type_id = '500'
JOIN aset AS s ON a.pty_id = s.pty_id
JOIN dim_branch AS b ON a.org_id = b.org_id
WHERE o."describe" = '非公职 离/退休'
  AND g."describe" = '女'
  AND a.cust_age >= 60
  AND s.total_aset > 100000
GROUP BY b.org_name
ORDER BY cnt DESC, b.org_name
""".strip(),
    },
    {
        "id": "H04",
        "theme": "fin_and_hold",
        "difficulty": "困难",
        "question": (
            "2026年一季度现金转入合计超过10万元，且在2026年3月31日仍持有开放式基金的客户有哪些？"
        ),
        "sql": """
WITH fin AS (
  SELECT pty_id
  FROM dws_cust_fin_d
  WHERE data_dt BETWEEN '20260101' AND '20260331'
  GROUP BY pty_id
  HAVING SUM(coalesce(cash_in, 0)) > 100000
),
hold AS (
  SELECT DISTINCT h.pty_id
  FROM dwd_cust_hold_d AS h
  JOIN dim_product AS p ON h.prdt_id = p.prdt_id
  WHERE h.data_dt = '20260331'
    AND p.up_prdt_type_id = 'PT050000'
)
SELECT f.pty_id
FROM fin AS f
INNER JOIN hold AS h ON f.pty_id = h.pty_id
ORDER BY f.pty_id
""".strip(),
    },
    {
        "id": "H05",
        "theme": "fc_ccy_product",
        "difficulty": "困难",
        "question": (
            "2026年一季度，信用账户在人民币币种下的A股买卖交易金额合计是多少？"
        ),
        "sql": """
SELECT SUM(coalesce(t.buy_amt, 0) + coalesce(t.sell_amt, 0)) AS trade_amt
FROM dwd_cust_tran_d AS t
JOIN dim_product AS p ON t.prdt_id = p.prdt_id
WHERE t.data_dt BETWEEN '20260101' AND '20260331'
  AND t.sys_source = 'fc'
  AND t.ccy = '0'
  AND p.prdt_type_name = 'A股'
""".strip(),
    },
    {
        "id": "H06",
        "theme": "rake_active_org",
        "difficulty": "困难",
        "question": (
            "2026年一季度买卖佣金合计超过100元且买卖笔数合计大于10笔的客户，"
            "按营业部统计人数分别是多少？"
        ),
        "sql": """
WITH active AS (
  SELECT pty_id
  FROM dwd_cust_tran_d
  WHERE data_dt BETWEEN '20260101' AND '20260331'
  GROUP BY pty_id
  HAVING SUM(coalesce(buy_rake, 0) + coalesce(sell_rake, 0)) > 100
     AND SUM(coalesce(buy_cnt, 0) + coalesce(sell_cnt, 0)) > 10
)
SELECT b.org_name, COUNT(*) AS cnt
FROM active AS a
JOIN ads_cust_info_d AS c ON a.pty_id = c.pty_id
JOIN dim_branch AS b ON c.org_id = b.org_id
GROUP BY b.org_name
ORDER BY cnt DESC, b.org_name
""".strip(),
    },
    {
        "id": "H07",
        "theme": "topn_marketing",
        "difficulty": "困难",
        "question": "2026年一季度客户买卖交易金额合计最高的前5个营业部是哪些？请给出交易金额",
        "sql": """
SELECT b.org_name, SUM(coalesce(t.buy_amt, 0) + coalesce(t.sell_amt, 0)) AS trade_amt
FROM dwd_cust_tran_d AS t
JOIN ads_cust_info_d AS c ON t.pty_id = c.pty_id
JOIN dim_branch AS b ON c.org_id = b.org_id
WHERE t.data_dt BETWEEN '20260101' AND '20260331'
GROUP BY b.org_name
ORDER BY trade_amt DESC, b.org_name
LIMIT 5
""".strip(),
    },
    {
        "id": "H08",
        "theme": "wide_projection",
        "difficulty": "困难",
        "question": (
            "列出紫金理财银卡男性客户的客户号、年龄、省份和营业部名称，不要额外统计人数"
        ),
        "sql": """
SELECT
  a.pty_id,
  a.cust_age,
  a.prov_name,
  b.org_name
FROM ads_cust_info_d AS a
JOIN dim_public AS l
  ON a.cust_lvl_cd = l.code AND l.code_type_id = '100'
JOIN dim_public AS g
  ON a.gender_cd = g.code AND g.code_type_id = '500'
JOIN dim_branch AS b ON a.org_id = b.org_id
WHERE l."describe" = '紫金理财银卡客户'
  AND g."describe" = '男'
ORDER BY a.pty_id
""".strip(),
    },
    {
        "id": "H09",
        "theme": "latest_vs_fixed",
        "difficulty": "困难",
        "question": (
            "按资产表最新数据日期，列出总资产超过100万的客户号、总资产和快照日期"
        ),
        "sql": """
WITH latest AS (
  SELECT MAX(data_dt) AS data_dt FROM dws_cust_aset_d
)
SELECT
  a.pty_id,
  coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0) AS total_aset,
  a.data_dt
FROM dws_cust_aset_d AS a
JOIN latest AS l ON a.data_dt = l.data_dt
WHERE coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0) > 1000000
ORDER BY a.pty_id
""".strip(),
    },
    {
        "id": "H10",
        "theme": "trade_and_hold_alt",
        "difficulty": "困难",
        "question": (
            "2026年一季度交易过华昌化工，且在2026年3月31日普通账户持有海陆重工的客户有哪些？"
        ),
        "sql": """
WITH cust_tran AS (
  SELECT DISTINCT t.pty_id
  FROM dwd_cust_tran_d AS t
  JOIN dim_product AS p ON t.prdt_id = p.prdt_id
  WHERE t.data_dt BETWEEN '20260101' AND '20260331'
    AND p.prdt_name = '华昌化工'
),
cust_hold AS (
  SELECT DISTINCT h.pty_id
  FROM dwd_cust_hold_d AS h
  JOIN dim_product AS p ON h.prdt_id = p.prdt_id
  WHERE h.data_dt = '20260331'
    AND h.sys_source = 'nm'
    AND p.prdt_name = '海陆重工'
)
SELECT t.pty_id
FROM cust_tran AS t
INNER JOIN cust_hold AS h ON t.pty_id = h.pty_id
ORDER BY t.pty_id
""".strip(),
    },
    {
        "id": "H11",
        "theme": "paraphrase_1",
        "difficulty": "困难",
        "question": "一季度里卖出总额大于十万元的客户人数是多少？",
        "sql": _SQL_M03,
    },
    {
        "id": "H12",
        "theme": "paraphrase_2",
        "difficulty": "困难",
        "question": (
            "哪些产品大类与二级类型，对应一季度日均资产超三十万且股票成交额过十万的客户"
            "在三月末的持仓？请输出市值合计"
        ),
        "sql": _SQL_H02,
    },
]


def main() -> None:
    print("=== execute + non-empty check ===")
    for case in CASES:
        r = execute(case["sql"], max_rows=5000)
        preview = r.rows[0] if r.rows else None
        ok = r.row_count >= 1
        if case["id"] in {"H05", "H11"}:
            ok = r.row_count == 1 and preview is not None and float(preview[0]) > 0
        status = "OK" if ok else "FAIL"
        print(
            f"{status} {case['id']} rows={r.row_count} cols={len(r.columns)} preview={preview}"
        )
        if not ok:
            raise SystemExit(f"non-empty check failed: {case['id']}")
        if case["id"] == "H08" and len(r.columns) < 4:
            raise SystemExit("H08 must project >=4 columns")
        if case["id"] == "H01" and list(r.columns) != [
            "pty_id",
            "bgn_aset",
            "end_aset",
            "aset_in",
            "aset_out",
            "aset_pft",
        ]:
            raise SystemExit(f"H01 bad columns: {r.columns}")

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
    assert len(loaded) == 12, len(loaded)
    assert [c.id for c in loaded] == [c["id"] for c in CASES]
    assert all(c.difficulty == "困难" for c in loaded)
    assert all(c.extras.get("theme") for c in loaded)

    shots = {
        e["question"].strip()
        for e in yaml.safe_load(
            (ROOT / "metadata/few_shots/examples.yaml").read_text(encoding="utf-8")
        )["examples"]
    }
    # also avoid colliding with easy/medium questions
    for path in (
        ROOT / "data/extra/Q&A_easy.xlsx",
        ROOT / "data/extra/Q&A_medium.xlsx",
    ):
        if path.exists():
            for c in load_qa_cases(path):
                shots.add(c.question.strip())

    overlap = [c.id for c in loaded if c.question.strip() in shots]
    assert not overlap, overlap
    print("load_qa_cases OK:", [(c.id, c.extras.get("theme")) for c in loaded])
    print("question overlap with few-shot/extra:", overlap)


if __name__ == "__main__":
    main()
