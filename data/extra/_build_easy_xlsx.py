"""Build and validate data/extra/Q&A_easy.xlsx (Step 2b)."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from querypilot.db import execute
from querypilot.eval.dataset import load_qa_cases

OUT = Path(__file__).with_name("Q&A_easy.xlsx")

# Questions must not equal metadata/few_shots/examples.yaml verbatim.
CASES: list[dict[str, str]] = [
    {
        "id": "E01",
        "theme": "status_filter",
        "difficulty": "简单",
        "question": "账户状态为正常的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM ads_cust_info_d AS a
JOIN dim_public AS p
  ON a.cust_status = p.code AND p.code_type_id = '200'
WHERE p."describe" = '正常'
""".strip(),
    },
    {
        "id": "E02",
        "theme": "occupation_filter",
        "difficulty": "简单",
        "question": "职业为非公职离退休的女性客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM ads_cust_info_d AS a
JOIN dim_public AS g
  ON a.gender_cd = g.code AND g.code_type_id = '500'
JOIN dim_public AS o
  ON a.prof_cd = o.code AND o.code_type_id = '700'
WHERE g."describe" = '女'
  AND o."describe" = '非公职 离/退休'
""".strip(),
    },
    {
        "id": "E03",
        "theme": "edu_filter",
        "difficulty": "简单",
        "question": "学历为高中、初中及其以下或中专的客户一共有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM ads_cust_info_d AS a
JOIN dim_public AS p
  ON a.edu_cd = p.code AND p.code_type_id = '600'
WHERE p."describe" IN ('高中', '初中及其以下', '中专')
""".strip(),
    },
    {
        "id": "E04",
        "theme": "total_aset_threshold",
        "difficulty": "简单",
        "question": "在2026年3月31日快照下，总资产超过100万的客户人数是多少？",
        "sql": """
WITH aset AS (
  SELECT
    pty_id,
    coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) AS total_aset
  FROM dws_cust_aset_d
  WHERE data_dt = '20260331'
)
SELECT COUNT(*) AS cnt
FROM aset
WHERE total_aset > 1000000
""".strip(),
    },
    {
        "id": "E05",
        "theme": "cash_bal_threshold",
        "difficulty": "简单",
        "question": "2026年3月31日普通账户现金余额超过1万元的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM dws_cust_aset_d
WHERE data_dt = '20260331'
  AND coalesce(nm_bal, 0) > 10000
""".strip(),
    },
    {
        "id": "E06",
        "theme": "hold_product_count",
        "difficulty": "简单",
        "question": "持有华泰紫金天天发货币市场基金且市值超过1000元的客户有多少人？",
        "sql": """
SELECT COUNT(DISTINCT h.pty_id) AS cnt
FROM dwd_cust_hold_d AS h
JOIN dim_product AS p ON h.prdt_id = p.prdt_id
WHERE h.data_dt = '20260331'
  AND p.prdt_name = '华泰紫金天天发货币市场基金'
  AND coalesce(h.mkt_val, 0) > 1000
""".strip(),
    },
    {
        "id": "E07",
        "theme": "hold_cnt_threshold",
        "difficulty": "简单",
        "question": "持有华泰紫金天天发货币市场基金且持仓份额大于100的客户有多少人？",
        "sql": """
SELECT COUNT(DISTINCT h.pty_id) AS cnt
FROM dwd_cust_hold_d AS h
JOIN dim_product AS p ON h.prdt_id = p.prdt_id
WHERE h.data_dt = '20260331'
  AND p.prdt_name = '华泰紫金天天发货币市场基金'
  AND coalesce(h.hold_cnt, 0) > 100
""".strip(),
    },
    {
        "id": "E08",
        "theme": "prov_cust_count",
        "difficulty": "简单",
        "question": "按省份统计客户人数分别是多少？",
        "sql": """
SELECT prov_name, COUNT(*) AS cnt
FROM ads_cust_info_d
GROUP BY prov_name
ORDER BY cnt DESC, prov_name
""".strip(),
    },
    {
        "id": "E09",
        "theme": "branch_cust_count",
        "difficulty": "简单",
        "question": "按营业部名称统计客户人数分别是多少？",
        "sql": """
SELECT b.org_name, COUNT(*) AS cnt
FROM ads_cust_info_d AS a
JOIN dim_branch AS b ON a.org_id = b.org_id
GROUP BY b.org_name
ORDER BY cnt DESC, b.org_name
""".strip(),
    },
    {
        "id": "E10",
        "theme": "level_gender_count",
        "difficulty": "简单",
        "question": "紫金理财银卡客户中的男性有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM ads_cust_info_d AS a
JOIN dim_public AS l
  ON a.cust_lvl_cd = l.code AND l.code_type_id = '100'
JOIN dim_public AS g
  ON a.gender_cd = g.code AND g.code_type_id = '500'
WHERE l."describe" = '紫金理财银卡客户'
  AND g."describe" = '男'
""".strip(),
    },
]


def main() -> None:
    print("=== execute + non-empty check ===")
    for case in CASES:
        r = execute(case["sql"], max_rows=500)
        nonempty = r.row_count > 0 and not (
            r.row_count == 1
            and len(r.columns) == 1
            and r.rows
            and (r.rows[0][0] is None or r.rows[0][0] == 0)
        )
        # COUNT queries: require cnt > 0; GROUP BY: require >=1 row
        if "GROUP BY" in case["sql"].upper():
            ok = r.row_count >= 1
        else:
            ok = r.row_count == 1 and int(r.rows[0][0]) > 0
        status = "OK" if ok else "FAIL"
        preview = r.rows[0] if r.rows else None
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
    assert len(loaded) == 10, len(loaded)
    assert [c.id for c in loaded] == [c["id"] for c in CASES]
    assert all(c.difficulty == "简单" for c in loaded)
    assert all(c.extras.get("theme") for c in loaded)
    print("load_qa_cases OK:", [(c.id, c.extras.get("theme")) for c in loaded])


if __name__ == "__main__":
    main()
