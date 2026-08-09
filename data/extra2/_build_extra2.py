"""Build and validate Extra2 Q&A xlsx (S3 造题 + 金标校验①；顺带落盘供 S4)."""

from __future__ import annotations

from pathlib import Path

import yaml
from openpyxl import Workbook

from querypilot.db import execute
from querypilot.eval.dataset import load_qa_cases

DIR = Path(__file__).resolve().parent
ROOT = DIR.parents[1]

_SQL_FM03 = """
SELECT COUNT(*) AS cnt
FROM (
  SELECT pty_id
  FROM dwd_cust_tran_d
  WHERE data_dt BETWEEN '20260101' AND '20260331'
  GROUP BY pty_id
  HAVING SUM(coalesce(sell_amt, 0)) > 200000
) AS t
""".strip()

_SQL_FM12 = """
WITH days AS (
  SELECT (DATE '2026-02-28' - DATE '2026-02-01')::INTEGER + 1 AS d
),
avg_a AS (
  SELECT
    pty_id,
    SUM(coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0)) / (SELECT d FROM days) AS avg_aset
  FROM dws_cust_aset_d
  WHERE data_dt BETWEEN '20260201' AND '20260228'
  GROUP BY pty_id
  HAVING SUM(coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0)) / (SELECT d FROM days) > 200000
)
SELECT COUNT(*) AS cnt FROM avg_a
""".strip()

EASY: list[dict[str, str]] = [
    {
        "id": "FE01",
        "theme": "cust_type_filter",
        "difficulty": "简单",
        "question": "个人客户一共有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM ads_cust_info_d
WHERE data_dt = '20260531' AND cust_type = 'P'
""".strip(),
    },
    {
        "id": "FE02",
        "theme": "status_alt",
        "difficulty": "简单",
        "question": "账户状态为销户的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM ads_cust_info_d AS a
JOIN dim_public AS p
  ON a.cust_status = p.code AND p.code_type_id = '200'
WHERE a.data_dt = '20260531' AND p."describe" = '销户'
""".strip(),
    },
    {
        "id": "FE03",
        "theme": "age_band_count",
        "difficulty": "简单",
        "question": "年龄大于等于40岁且小于50岁的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM ads_cust_info_d
WHERE data_dt = '20260531' AND cust_age >= 40 AND cust_age < 50
""".strip(),
    },
    {
        "id": "FE04",
        "theme": "city_cust_count",
        "difficulty": "简单",
        "question": "所在城市为南京市的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM ads_cust_info_d
WHERE data_dt = '20260531' AND city_name = '南京市'
""".strip(),
    },
    {
        "id": "FE05",
        "theme": "nm_bal_threshold",
        "difficulty": "简单",
        "question": "在2026年3月31日快照下，普通账户现金余额超过5万元的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM dws_cust_aset_d
WHERE data_dt = '20260331' AND coalesce(nm_bal, 0) > 50000
""".strip(),
    },
    {
        "id": "FE06",
        "theme": "fc_bal_threshold",
        "difficulty": "简单",
        "question": "在2026年3月31日快照下，外币购买力余额（fc_bal）超过1万元的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM dws_cust_aset_d
WHERE data_dt = '20260331' AND coalesce(fc_bal, 0) > 10000
""".strip(),
    },
    {
        "id": "FE07",
        "theme": "hold_mkt_val",
        "difficulty": "简单",
        "question": "在2026年3月31日，持仓市值合计超过10万元的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM (
  SELECT pty_id
  FROM dwd_cust_hold_d
  WHERE data_dt = '20260331'
  GROUP BY pty_id
  HAVING SUM(coalesce(mkt_val, 0)) > 100000
) AS t
""".strip(),
    },
    {
        "id": "FE08",
        "theme": "branch_name_count",
        "difficulty": "简单",
        "question": "挂靠在苏州******营业部的客户有多少人？",
        "sql": """
SELECT COUNT(DISTINCT a.pty_id) AS cnt
FROM ads_cust_info_d AS a
JOIN dim_branch AS b ON a.org_id = b.org_id
WHERE a.data_dt = '20260531' AND b.org_name = '苏州******营业部'
""".strip(),
    },
    {
        "id": "FE09",
        "theme": "up_org_count",
        "difficulty": "简单",
        "question": "所属分公司为南京分公司的客户有多少人？",
        "sql": """
SELECT COUNT(DISTINCT a.pty_id) AS cnt
FROM ads_cust_info_d AS a
JOIN dim_branch AS b ON a.org_id = b.org_id
WHERE a.data_dt = '20260531' AND b.up_org_name = '南京分公司'
""".strip(),
    },
    {
        "id": "FE10",
        "theme": "gender_level",
        "difficulty": "简单",
        "question": "紫金理财金卡的女性客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM ads_cust_info_d AS a
JOIN dim_public AS l
  ON a.cust_lvl_cd = l.code AND l.code_type_id = '100'
JOIN dim_public AS g
  ON a.gender_cd = g.code AND g.code_type_id = '500'
WHERE a.data_dt = '20260531'
  AND l."describe" = '紫金理财金卡客户'
  AND g."describe" = '女'
""".strip(),
    },
    {
        "id": "FE11",
        "theme": "product_name_hold",
        "difficulty": "简单",
        "question": "在2026年3月31日持有南方天天利货币市场基金的客户有多少人？",
        "sql": """
SELECT COUNT(DISTINCT h.pty_id) AS cnt
FROM dwd_cust_hold_d AS h
JOIN dim_product AS p ON h.prdt_id = p.prdt_id
WHERE h.data_dt = '20260331' AND p.prdt_name = '南方天天利货币市场基金'
""".strip(),
    },
    {
        "id": "FE12",
        "theme": "edu_alt_set",
        "difficulty": "简单",
        "question": "学历为大专、高中、初中及其以下或中专的客户一共有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM ads_cust_info_d AS a
JOIN dim_public AS p
  ON a.edu_cd = p.code AND p.code_type_id = '600'
WHERE a.data_dt = '20260531'
  AND p."describe" IN ('大专', '高中', '初中及其以下', '中专')
""".strip(),
    },
]

MEDIUM: list[dict[str, str]] = [
    {
        "id": "FM01",
        "theme": "fc_hold_alt",
        "difficulty": "中等",
        "question": "信用账户持有江特电机的客户有多少人？",
        "sql": """
SELECT COUNT(DISTINCT h.pty_id) AS cnt
FROM dwd_cust_hold_d AS h
JOIN dim_product AS p ON h.prdt_id = p.prdt_id
WHERE h.data_dt = '20260331'
  AND h.sys_source = 'fc'
  AND p.prdt_name = '江特电机'
""".strip(),
    },
    {
        "id": "FM02",
        "theme": "fc_tran_window",
        "difficulty": "中等",
        "question": "在2026年1月15日至2月15日期间，信用账户买卖金额合计超过5万元的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM (
  SELECT pty_id
  FROM dwd_cust_tran_d
  WHERE data_dt BETWEEN '20260115' AND '20260215'
    AND sys_source = 'fc'
  GROUP BY pty_id
  HAVING SUM(coalesce(buy_amt, 0) + coalesce(sell_amt, 0)) > 50000
) AS t
""".strip(),
    },
    {
        "id": "FM03",
        "theme": "sell_hav_count",
        "difficulty": "中等",
        "question": "2026年一季度卖出金额合计超过20万元的客户有多少人？",
        "sql": _SQL_FM03,
    },
    {
        "id": "FM04",
        "theme": "buy_amt_window",
        "difficulty": "中等",
        "question": "列出2026年1月15日至2月15日买入金额合计超过5万元的客户号，按客户号排序。",
        "sql": """
SELECT pty_id
FROM dwd_cust_tran_d
WHERE data_dt BETWEEN '20260115' AND '20260215'
GROUP BY pty_id
HAVING SUM(coalesce(buy_amt, 0)) > 50000
ORDER BY pty_id
""".strip(),
    },
    {
        "id": "FM05",
        "theme": "fare_sum",
        "difficulty": "中等",
        "question": "2026年一季度买卖手续费合计超过100元的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM (
  SELECT pty_id
  FROM dwd_cust_tran_d
  WHERE data_dt BETWEEN '20260101' AND '20260331'
  GROUP BY pty_id
  HAVING SUM(coalesce(buy_fare, 0) + coalesce(sell_fare, 0)) > 100
) AS t
""".strip(),
    },
    {
        "id": "FM06",
        "theme": "ccy_group",
        "difficulty": "中等",
        "question": "在2026年3月31日，按持仓币种汇总市值合计，并按市值从高到低、币种排序。",
        "sql": """
SELECT
  ccy,
  SUM(coalesce(mkt_val, 0)) AS mkt_val
FROM dwd_cust_hold_d
WHERE data_dt = '20260331'
GROUP BY ccy
ORDER BY mkt_val DESC, ccy
""".strip(),
    },
    {
        "id": "FM07",
        "theme": "cash_net_in",
        "difficulty": "中等",
        "question": "列出2026年一季度现金净流入（现金流入减现金流出）超过10万元的客户号，按客户号排序。",
        "sql": """
SELECT pty_id
FROM dws_cust_fin_d
WHERE data_dt BETWEEN '20260101' AND '20260331'
GROUP BY pty_id
HAVING SUM(coalesce(cash_in, 0) - coalesce(cash_out, 0)) > 100000
ORDER BY pty_id
""".strip(),
    },
    {
        "id": "FM08",
        "theme": "assign_flow",
        "difficulty": "中等",
        "question": "2026年一季度证券转入金额合计大于0的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM (
  SELECT pty_id
  FROM dws_cust_fin_d
  WHERE data_dt BETWEEN '20260101' AND '20260331'
  GROUP BY pty_id
  HAVING SUM(coalesce(assign_in, 0)) > 0
) AS t
""".strip(),
    },
    {
        "id": "FM09",
        "theme": "bond_or_fund",
        "difficulty": "中等",
        "question": "在2026年3月31日，债券类产品持仓市值合计是多少？",
        "sql": """
SELECT SUM(coalesce(h.mkt_val, 0)) AS mkt_val
FROM dwd_cust_hold_d AS h
JOIN dim_product AS p ON h.prdt_id = p.prdt_id
WHERE h.data_dt = '20260331' AND p.up_prdt_type_id = 'PT030000'
""".strip(),
    },
    {
        "id": "FM10",
        "theme": "same_prdt_trade_hold",
        "difficulty": "中等",
        "question": "2026年一季度交易过特变电工、且在3月31日仍持有特变电工的客户有多少人？",
        "sql": """
WITH tr AS (
  SELECT DISTINCT t.pty_id
  FROM dwd_cust_tran_d AS t
  JOIN dim_product AS p ON t.prdt_id = p.prdt_id
  WHERE t.data_dt BETWEEN '20260101' AND '20260331'
    AND p.prdt_name = '特变电工'
),
ho AS (
  SELECT DISTINCT h.pty_id
  FROM dwd_cust_hold_d AS h
  JOIN dim_product AS p ON h.prdt_id = p.prdt_id
  WHERE h.data_dt = '20260331' AND p.prdt_name = '特变电工'
)
SELECT COUNT(*) AS cnt
FROM tr
INNER JOIN ho USING (pty_id)
""".strip(),
    },
    {
        "id": "FM11",
        "theme": "nm_tot_only",
        "difficulty": "中等",
        "question": "在2026年3月31日，本币总资产（仅 nm_tot_aset，不含外币购买力）超过50万元的客户有多少人？",
        "sql": """
SELECT COUNT(*) AS cnt
FROM dws_cust_aset_d
WHERE data_dt = '20260331' AND coalesce(nm_tot_aset, 0) > 500000
""".strip(),
    },
    {
        "id": "FM12",
        "theme": "custom_avg_window",
        "difficulty": "中等",
        "question": "2026年2月1日至2月28日期间日均总资产超过20万元的客户有多少人？",
        "sql": _SQL_FM12,
    },
    {
        "id": "FM13",
        "theme": "up_org_trade",
        "difficulty": "中等",
        "question": "按分公司汇总2026年一季度客户买卖金额合计，按金额降序、分公司名称排序。",
        "sql": """
SELECT
  b.up_org_name,
  SUM(coalesce(t.buy_amt, 0) + coalesce(t.sell_amt, 0)) AS trade_amt
FROM dwd_cust_tran_d AS t
JOIN ads_cust_info_d AS a
  ON t.pty_id = a.pty_id AND a.data_dt = '20260531'
JOIN dim_branch AS b ON a.org_id = b.org_id
WHERE t.data_dt BETWEEN '20260101' AND '20260331'
GROUP BY b.up_org_name
ORDER BY trade_amt DESC, b.up_org_name
""".strip(),
    },
    {
        "id": "FM14",
        "theme": "latest_aset_alt",
        "difficulty": "中等",
        "question": "在最新资产快照日，总资产超过50万元的客户号及总资产、快照日是哪些？按客户号排序。",
        "sql": """
WITH latest AS (
  SELECT MAX(data_dt) AS data_dt FROM dws_cust_aset_d
),
aset AS (
  SELECT
    a.pty_id,
    coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0) AS total_aset,
    a.data_dt
  FROM dws_cust_aset_d AS a
  JOIN latest AS l ON a.data_dt = l.data_dt
)
SELECT pty_id, total_aset, data_dt
FROM aset
WHERE total_aset > 500000
ORDER BY pty_id
""".strip(),
    },
    {
        "id": "FM15",
        "theme": "prov_aset_dist",
        "difficulty": "中等",
        "question": "在2026年3月31日总资产超过50万元的客户，按省份统计人数，按人数降序、省名排序。",
        "sql": """
WITH aset AS (
  SELECT
    pty_id,
    coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) AS total_aset
  FROM dws_cust_aset_d
  WHERE data_dt = '20260331'
)
SELECT
  a.prov_name,
  COUNT(*) AS cnt
FROM ads_cust_info_d AS a
JOIN aset AS s ON a.pty_id = s.pty_id
WHERE a.data_dt = '20260531' AND s.total_aset > 500000
GROUP BY a.prov_name
ORDER BY cnt DESC, a.prov_name
""".strip(),
    },
    {
        "id": "FM16",
        "theme": "sor_prdt_tran",
        "difficulty": "中等",
        "question": "2026年一季度交易过产品代码为002131的客户有多少人？",
        "sql": """
SELECT COUNT(DISTINCT t.pty_id) AS cnt
FROM dwd_cust_tran_d AS t
JOIN dim_product AS p ON t.prdt_id = p.prdt_id
WHERE t.data_dt BETWEEN '20260101' AND '20260331'
  AND p.sor_prdt_id = '002131'
""".strip(),
    },
]

HARD: list[dict[str, str]] = [
    {
        "id": "FH01",
        "theme": "period_pnl_fresh",
        "difficulty": "困难",
        "question": (
            "紫金理财白金卡客户，在2026年3月31日持有创业板市值合计超过1000元，"
            "请给出其2026年一季度期间盈亏六列："
            "客户号、期初资产、期末资产、期间流入、期间流出、期间盈亏。"
        ),
        "sql": """
WITH custinfo AS (
  SELECT a.pty_id
  FROM ads_cust_info_d AS a
  JOIN dim_public AS l
    ON a.cust_lvl_cd = l.code AND l.code_type_id = '100'
  WHERE a.data_dt = '20260531'
    AND l."describe" = '紫金理财白金卡客户'
),
prdtinfo AS (
  SELECT h.pty_id
  FROM dwd_cust_hold_d AS h
  INNER JOIN dim_product AS p ON h.prdt_id = p.prdt_id
  INNER JOIN custinfo AS z ON h.pty_id = z.pty_id
  WHERE h.data_dt = '20260331'
    AND p.prdt_type_name = '创业板'
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
    - coalesce(aset_bgn.nm_tot_aset, 0) + coalesce(aset_bgn.fc_pur_aset, 0)
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
""".strip(),
    },
    {
        "id": "FH02",
        "theme": "avg_hold_taxonomy",
        "difficulty": "困难",
        "question": (
            "2026年2月日均总资产超过20万元、且在3月31日持有开放式基金的客户，"
            "其持仓按产品大类汇总市值，按市值降序、大类名排序。"
        ),
        "sql": """
WITH days AS (
  SELECT (DATE '2026-02-28' - DATE '2026-02-01')::INTEGER + 1 AS d
),
cust_avg AS (
  SELECT pty_id
  FROM dws_cust_aset_d
  WHERE data_dt BETWEEN '20260201' AND '20260228'
  GROUP BY pty_id
  HAVING SUM(coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0)) / (SELECT d FROM days) > 200000
),
fund_hold AS (
  SELECT DISTINCT h.pty_id
  FROM dwd_cust_hold_d AS h
  JOIN dim_product AS p ON h.prdt_id = p.prdt_id
  WHERE h.data_dt = '20260331' AND p.up_prdt_type_id = 'PT050000'
),
cohort AS (
  SELECT a.pty_id
  FROM cust_avg AS a
  INNER JOIN fund_hold AS f ON a.pty_id = f.pty_id
)
SELECT
  p.up_prdt_type_name,
  SUM(coalesce(h.mkt_val, 0)) AS mkt_val
FROM cohort AS c
INNER JOIN dwd_cust_hold_d AS h
  ON c.pty_id = h.pty_id AND h.data_dt = '20260331'
INNER JOIN dim_product AS p ON h.prdt_id = p.prdt_id
GROUP BY p.up_prdt_type_name
ORDER BY mkt_val DESC, p.up_prdt_type_name
""".strip(),
    },
    {
        "id": "FH03",
        "theme": "age_aset_city",
        "difficulty": "困难",
        "question": (
            "年龄在40到50岁之间（含40不含50）、且2026年3月31日总资产超过10万元的客户，"
            "按城市统计人数，按人数降序、城市名排序。"
        ),
        "sql": """
WITH aset AS (
  SELECT
    pty_id,
    coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) AS total_aset
  FROM dws_cust_aset_d
  WHERE data_dt = '20260331'
)
SELECT
  a.city_name,
  COUNT(*) AS cnt
FROM ads_cust_info_d AS a
JOIN aset AS s ON a.pty_id = s.pty_id
WHERE a.data_dt = '20260531'
  AND a.cust_age >= 40 AND a.cust_age < 50
  AND s.total_aset > 100000
GROUP BY a.city_name
ORDER BY cnt DESC, a.city_name
""".strip(),
    },
    {
        "id": "FH04",
        "theme": "fin_and_tran",
        "difficulty": "困难",
        "question": (
            "2026年一季度现金净流入超过5万元、且同期有过股票类产品交易的客户有多少人？"
        ),
        "sql": """
WITH fin AS (
  SELECT pty_id
  FROM dws_cust_fin_d
  WHERE data_dt BETWEEN '20260101' AND '20260331'
  GROUP BY pty_id
  HAVING SUM(coalesce(cash_in, 0) - coalesce(cash_out, 0)) > 50000
),
tr AS (
  SELECT DISTINCT t.pty_id
  FROM dwd_cust_tran_d AS t
  JOIN dim_product AS p ON t.prdt_id = p.prdt_id
  WHERE t.data_dt BETWEEN '20260101' AND '20260331'
    AND p.up_prdt_type_id = 'PT040000'
)
SELECT COUNT(*) AS cnt
FROM fin
INNER JOIN tr USING (pty_id)
""".strip(),
    },
    {
        "id": "FH05",
        "theme": "fc_type_window",
        "difficulty": "困难",
        "question": (
            "在2026年1月15日至2月15日，信用账户交易A股且买卖金额合计超过1万元的客户有多少人？"
        ),
        "sql": """
SELECT COUNT(*) AS cnt
FROM (
  SELECT t.pty_id
  FROM dwd_cust_tran_d AS t
  JOIN dim_product AS p ON t.prdt_id = p.prdt_id
  WHERE t.data_dt BETWEEN '20260115' AND '20260215'
    AND t.sys_source = 'fc'
    AND p.prdt_type_name = 'A股'
  GROUP BY t.pty_id
  HAVING SUM(coalesce(t.buy_amt, 0) + coalesce(t.sell_amt, 0)) > 10000
) AS t
""".strip(),
    },
    {
        "id": "FH06",
        "theme": "rake_level_org",
        "difficulty": "困难",
        "question": (
            "紫金理财金卡客户中，2026年一季度佣金合计超过100元且买卖笔数合计超过5笔的，"
            "按营业部统计人数，按人数降序、营业部名称排序。"
        ),
        "sql": """
WITH rake AS (
  SELECT
    pty_id,
    SUM(coalesce(buy_rake, 0) + coalesce(sell_rake, 0)) AS rk,
    SUM(coalesce(buy_cnt, 0) + coalesce(sell_cnt, 0)) AS cnt
  FROM dwd_cust_tran_d
  WHERE data_dt BETWEEN '20260101' AND '20260331'
  GROUP BY pty_id
  HAVING SUM(coalesce(buy_rake, 0) + coalesce(sell_rake, 0)) > 100
     AND SUM(coalesce(buy_cnt, 0) + coalesce(sell_cnt, 0)) > 5
)
SELECT
  b.org_name,
  COUNT(*) AS cust_cnt
FROM rake AS r
JOIN ads_cust_info_d AS a
  ON r.pty_id = a.pty_id AND a.data_dt = '20260531'
JOIN dim_public AS l
  ON a.cust_lvl_cd = l.code AND l.code_type_id = '100'
JOIN dim_branch AS b ON a.org_id = b.org_id
WHERE l."describe" = '紫金理财金卡客户'
GROUP BY b.org_name
ORDER BY cust_cnt DESC, b.org_name
""".strip(),
    },
    {
        "id": "FH07",
        "theme": "topn_cust",
        "difficulty": "困难",
        "question": (
            "2026年一季度买卖金额合计最高的前5名客户是谁？输出客户号与交易总额，"
            "按总额降序、客户号排序。"
        ),
        "sql": """
SELECT
  a.pty_id,
  SUM(coalesce(t.buy_amt, 0) + coalesce(t.sell_amt, 0)) AS trade_amt
FROM dwd_cust_tran_d AS t
JOIN ads_cust_info_d AS a
  ON t.pty_id = a.pty_id AND a.data_dt = '20260531'
WHERE t.data_dt BETWEEN '20260101' AND '20260331'
GROUP BY a.pty_id
ORDER BY trade_amt DESC, a.pty_id
LIMIT 5
""".strip(),
    },
    {
        "id": "FH08",
        "theme": "wide_proj_fresh",
        "difficulty": "困难",
        "question": (
            "列出紫金理财金卡女性客户的客户号、年龄、省份、城市四列明细，按客户号排序；不要附加人数统计。"
        ),
        "sql": """
SELECT
  a.pty_id,
  a.cust_age,
  a.prov_name,
  a.city_name
FROM ads_cust_info_d AS a
JOIN dim_public AS l
  ON a.cust_lvl_cd = l.code AND l.code_type_id = '100'
JOIN dim_public AS g
  ON a.gender_cd = g.code AND g.code_type_id = '500'
WHERE a.data_dt = '20260531'
  AND l."describe" = '紫金理财金卡客户'
  AND g."describe" = '女'
ORDER BY a.pty_id
""".strip(),
    },
    {
        "id": "FH09",
        "theme": "two_window_cmp",
        "difficulty": "困难",
        "question": (
            "哪些客户在2026年3月的买卖金额合计高于其1月买卖金额合计，且3月合计超过10万元？"
            "输出客户号、1月金额、3月金额，按3月金额降序、客户号排序。"
        ),
        "sql": """
WITH w1 AS (
  SELECT
    pty_id,
    SUM(coalesce(buy_amt, 0) + coalesce(sell_amt, 0)) AS amt
  FROM dwd_cust_tran_d
  WHERE data_dt BETWEEN '20260101' AND '20260131'
  GROUP BY pty_id
),
w2 AS (
  SELECT
    pty_id,
    SUM(coalesce(buy_amt, 0) + coalesce(sell_amt, 0)) AS amt
  FROM dwd_cust_tran_d
  WHERE data_dt BETWEEN '20260301' AND '20260331'
  GROUP BY pty_id
)
SELECT
  w1.pty_id,
  w1.amt AS jan_amt,
  w2.amt AS mar_amt
FROM w1
INNER JOIN w2 USING (pty_id)
WHERE w2.amt > w1.amt AND w2.amt > 100000
ORDER BY mar_amt DESC, w1.pty_id
""".strip(),
    },
    {
        "id": "FH10",
        "theme": "same_prdt_attr",
        "difficulty": "困难",
        "question": (
            "2026年一季度交易过特变电工、3月31日仍持有特变电工、且为男性的客户有多少人？"
        ),
        "sql": """
WITH tr AS (
  SELECT DISTINCT t.pty_id
  FROM dwd_cust_tran_d AS t
  JOIN dim_product AS p ON t.prdt_id = p.prdt_id
  WHERE t.data_dt BETWEEN '20260101' AND '20260331'
    AND p.prdt_name = '特变电工'
),
ho AS (
  SELECT DISTINCT h.pty_id
  FROM dwd_cust_hold_d AS h
  JOIN dim_product AS p ON h.prdt_id = p.prdt_id
  WHERE h.data_dt = '20260331' AND p.prdt_name = '特变电工'
)
SELECT COUNT(*) AS cnt
FROM tr
INNER JOIN ho USING (pty_id)
JOIN ads_cust_info_d AS a
  ON tr.pty_id = a.pty_id AND a.data_dt = '20260531'
JOIN dim_public AS g
  ON a.gender_cd = g.code AND g.code_type_id = '500'
WHERE g."describe" = '男'
""".strip(),
    },
    {
        "id": "FH11",
        "theme": "paraphrase_fresh_1",
        "difficulty": "困难",
        "question": "一季度里把卖出金额加总后还多于二十万的客户，人数是多少？",
        "sql": _SQL_FM03,
    },
    {
        "id": "FH12",
        "theme": "paraphrase_fresh_2",
        "difficulty": "困难",
        "question": "二月整月按日历日均摊后总资产均值还高于二十万的客户有几位？",
        "sql": _SQL_FM12,
    },
]

ALL_CASES = EASY + MEDIUM + HARD


def _occupied_questions() -> set[str]:
    occupied: set[str] = set()
    for p in (ROOT / "data" / "Q&A.xlsx", ROOT / "data" / "extra" / "Q&A_all.xlsx"):
        for c in load_qa_cases(p):
            occupied.add(" ".join(c.question.split()))
    raw = yaml.safe_load((ROOT / "metadata" / "few_shots" / "examples.yaml").read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("examples", [])
    for s in items:
        if isinstance(s, dict) and s.get("question"):
            occupied.add(" ".join(s["question"].split()))
    return occupied


def _write_xlsx(path: Path, cases: list[dict[str, str]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Q&A"
    ws.append(["序号", "问题", "SQL", "难度", "theme"])
    for c in cases:
        ws.append([c["id"], c["question"], c["sql"], c["difficulty"], c["theme"]])
    wb.save(path)


def main() -> None:
    assert len(EASY) == 12 and len(MEDIUM) == 16 and len(HARD) == 12
    assert len(ALL_CASES) == 40
    ids = [c["id"] for c in ALL_CASES]
    assert len(ids) == len(set(ids)), "duplicate ids"

    occupied = _occupied_questions()
    for c in ALL_CASES:
        qn = " ".join(c["question"].split())
        if qn in occupied:
            raise SystemExit(f"DEDUP FAIL {c['id']}: {qn}")

    print("=== gold execute check ===")
    for c in ALL_CASES:
        r = execute(c["sql"], max_rows=5000)
        # FM08 intentionally cnt=0 (assign column coverage); others non-empty
        if c["id"] == "FM08":
            if not (r.row_count == 1 and r.rows and int(r.rows[0][0]) == 0):
                raise SystemExit(f"FM08 expected cnt=0, got {r.rows}")
        elif r.row_count == 0:
            raise SystemExit(f"{c['id']} empty result")
        elif (
            r.row_count == 1
            and len(r.columns) == 1
            and r.rows
            and (r.rows[0][0] is None or r.rows[0][0] == 0)
            and "GROUP BY" not in c["sql"].upper()
        ):
            raise SystemExit(f"{c['id']} zero count: {r.rows}")
        if c["id"] == "FH01" and list(r.columns) != [
            "pty_id",
            "bgn_aset",
            "end_aset",
            "aset_in",
            "aset_out",
            "aset_pft",
        ]:
            raise SystemExit(f"FH01 bad columns: {r.columns}")
        print(f"  {c['id']} ok rows={r.row_count} preview={r.rows[0] if r.rows else None}")

    _write_xlsx(DIR / "Q&A_easy.xlsx", EASY)
    _write_xlsx(DIR / "Q&A_medium.xlsx", MEDIUM)
    _write_xlsx(DIR / "Q&A_hard.xlsx", HARD)
    _write_xlsx(DIR / "Q&A_all.xlsx", ALL_CASES)

    loaded = load_qa_cases(DIR / "Q&A_all.xlsx")
    assert len(loaded) == 40
    assert all(c.extras.get("theme") for c in loaded)
    print("load_qa_cases OK:", len(loaded), "themes ok")

    # refresh dedupe checklist footer
    checklist = DIR / "dedupe_checklist.md"
    text = checklist.read_text(encoding="utf-8")
    marker = "\n## Extra2 问句（本批）\n"
    block = ["\n## Extra2 问句（本批）\n"]
    for c in ALL_CASES:
        block.append(f"- `{c['id']}`: {' '.join(c['question'].split())}")
    block.append("\n## 合入结果\n")
    block.append("- [x] 40 条问句与占用集合全文不冲突（`_build_extra2.py` 已校验）\n")
    block.append("- [x] 金标 DuckDB 可执行；除 FM08（assign 全库为 0）外结果非空\n")
    if marker in text:
        text = text.split(marker)[0].rstrip() + "\n"
    checklist.write_text(text + "".join(block), encoding="utf-8")
    print("updated dedupe_checklist.md")


if __name__ == "__main__":
    main()
