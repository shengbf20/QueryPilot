"""验证 DuckDB 数据导入是否正确。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "db" / "competition.duckdb"

EXPECTED_TABLES = [
    "ads_cust_info_d",
    "dim_branch",
    "dim_product",
    "dim_public",
    "dwd_cust_hold_d",
    "dwd_cust_tran_d",
    "dws_cust_aset_d",
    "dws_cust_fin_d",
]


def run_checks(con: duckdb.DuckDBPyConnection) -> bool:
    ok = True

    print("=== 1. 表清单 ===")
    tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
    for name in EXPECTED_TABLES:
        status = "OK" if name in tables else "缺失"
        print(f"  [{status}] {name}")
        if name not in tables:
            ok = False

    print("\n=== 2. 行数统计 ===")
    for name in EXPECTED_TABLES:
        if name not in tables:
            continue
        count = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name}: {count:,}")

    print("\n=== 3. 关联查询（客户 + 资产，Top 5）===")
    cust_dt, asset_min, asset_max = con.execute(
        """
        SELECT
            (SELECT DISTINCT data_dt FROM ads_cust_info_d),
            (SELECT MIN(data_dt) FROM dws_cust_aset_d),
            (SELECT MAX(data_dt) FROM dws_cust_aset_d)
        """
    ).fetchone()
    print(f"  客户表日期: {cust_dt} | 资产表日期范围: {asset_min} ~ {asset_max}")

    same_day_cnt = con.execute(
        """
        SELECT COUNT(*)
        FROM ads_cust_info_d AS c
        JOIN dws_cust_aset_d AS a
            ON c.pty_id = a.pty_id
           AND c.data_dt = a.data_dt
        """
    ).fetchone()[0]
    pty_only_cnt = con.execute(
        """
        SELECT COUNT(DISTINCT c.pty_id)
        FROM ads_cust_info_d AS c
        JOIN dws_cust_aset_d AS a ON c.pty_id = a.pty_id
        """
    ).fetchone()[0]
    print(f"  同日期关联命中: {same_day_cnt} 行 | 仅 pty_id 关联命中: {pty_only_cnt} 客户")

    if same_day_cnt == 0:
        print("  提示: 两表 data_dt 无交集，跨表查询应仅按 pty_id 关联，或取资产表最新快照。")

    rows = con.execute(
        """
        WITH latest_asset AS (
            SELECT *
            FROM dws_cust_aset_d
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY pty_id ORDER BY data_dt DESC
            ) = 1
        )
        SELECT
            c.pty_id,
            c.name,
            c.cust_age,
            a.data_dt AS asset_dt,
            a.nm_tot_aset
        FROM ads_cust_info_d AS c
        JOIN latest_asset AS a ON c.pty_id = a.pty_id
        ORDER BY a.nm_tot_aset DESC
        LIMIT 5
        """
    ).fetchall()
    if not rows:
        print("  失败: 按 pty_id 关联仍无结果")
        ok = False
    else:
        for row in rows:
            print(f"  {row}")

    print("\n=== 4. 编码字典关联（性别）===")
    sample = con.execute(
        """
        SELECT c.gender_cd, p."describe", COUNT(*) AS cnt
        FROM ads_cust_info_d AS c
        LEFT JOIN dim_public AS p
            ON c.gender_cd = p.code
           AND p.code_type_id = '500'
        GROUP BY 1, 2
        ORDER BY cnt DESC
        """
    ).fetchall()
    for row in sample:
        print(f"  {row}")

    print("\n=== 5. EXPLAIN 语法校验 ===")
    try:
        con.execute(
            """
            EXPLAIN
            SELECT p.prdt_name, SUM(t.buy_amt) AS total_buy
            FROM dwd_cust_tran_d AS t
            JOIN dim_product AS p ON t.prdt_id = p.prdt_id
            GROUP BY p.prdt_name
            """
        )
        print("  EXPLAIN 执行成功")
    except duckdb.Error as exc:
        print(f"  EXPLAIN 失败: {exc}")
        ok = False

    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 DuckDB 数据库")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"数据库文件路径（默认: {DEFAULT_DB_PATH}）",
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"错误: 数据库不存在，请先运行 python scripts/import_data.py")
        print(f"  路径: {args.db}")
        return 1

    con = duckdb.connect(str(args.db), read_only=True)
    try:
        passed = run_checks(con)
    finally:
        con.close()

    print("\n" + ("全部检查通过。" if passed else "存在检查失败项。"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
