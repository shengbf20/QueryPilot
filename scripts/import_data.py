"""将 data/ 下 CSV 导入 DuckDB。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DEFAULT_DB_PATH = ROOT / "db" / "competition.duckdb"

TABLES: dict[str, dict] = {
    "dim_product": {
        "pattern": "dim_product_*.csv",
        "ddl": """
            CREATE TABLE dim_product (
                prdt_id VARCHAR,
                prdt_name VARCHAR,
                sor_prdt_id VARCHAR,
                market_id VARCHAR,
                prdt_type_id VARCHAR,
                prdt_type_name VARCHAR,
                up_prdt_type_id VARCHAR,
                up_prdt_type_name VARCHAR
            )
        """,
    },
    "ads_cust_info_d": {
        "pattern": "ads_cust_info_d_*.csv",
        "ddl": """
            CREATE TABLE ads_cust_info_d (
                data_dt VARCHAR,
                pty_id VARCHAR,
                sor_pty_id VARCHAR,
                cust_lvl_cd VARCHAR,
                cust_status VARCHAR,
                cust_type VARCHAR,
                prov_name VARCHAR,
                city_name VARCHAR,
                birth_dt VARCHAR,
                cust_age BIGINT,
                name VARCHAR,
                gender_cd VARCHAR,
                edu_cd VARCHAR,
                prof_cd VARCHAR,
                org_id VARCHAR
            )
        """,
    },
    "dws_cust_fin_d": {
        "pattern": "dws_cust_fin_d_*.csv",
        "ddl": """
            CREATE TABLE dws_cust_fin_d (
                data_dt VARCHAR NOT NULL,
                pty_id VARCHAR NOT NULL,
                sys_source VARCHAR NOT NULL,
                cash_in DECIMAL(20, 4),
                cash_out DECIMAL(20, 4),
                tran_in DECIMAL(20, 4),
                tran_out DECIMAL(20, 4),
                assign_in DECIMAL(20, 4),
                assign_out DECIMAL(20, 4)
            )
        """,
    },
    "dwd_cust_hold_d": {
        "pattern": "dwd_cust_hold_d_*.csv",
        "ddl": """
            CREATE TABLE dwd_cust_hold_d (
                data_dt VARCHAR NOT NULL,
                pty_id VARCHAR NOT NULL,
                prdt_id VARCHAR NOT NULL,
                sys_source VARCHAR NOT NULL,
                ccy VARCHAR NOT NULL,
                hold_cnt DECIMAL(20, 4),
                mkt_val DECIMAL(20, 4)
            )
        """,
    },
    "dwd_cust_tran_d": {
        "pattern": "dwd_cust_tran_d_*.csv",
        "ddl": """
            CREATE TABLE dwd_cust_tran_d (
                data_dt VARCHAR NOT NULL,
                pty_id VARCHAR NOT NULL,
                prdt_id VARCHAR NOT NULL,
                sys_source VARCHAR NOT NULL,
                ccy VARCHAR NOT NULL,
                buy_cnt INTEGER,
                buy_mnt DECIMAL(20, 4),
                buy_rake DECIMAL(20, 4),
                buy_amt DECIMAL(20, 4),
                buy_fare DECIMAL(20, 4),
                sell_cnt INTEGER,
                sell_mnt DECIMAL(20, 4),
                sell_rake DECIMAL(20, 4),
                sell_amt DECIMAL(20, 4),
                sell_fare DECIMAL(20, 4)
            )
        """,
    },
    "dws_cust_aset_d": {
        "pattern": "dws_cust_aset_d_*.csv",
        "ddl": """
            CREATE TABLE dws_cust_aset_d (
                data_dt VARCHAR NOT NULL,
                pty_id VARCHAR NOT NULL,
                nm_tot_aset DECIMAL(20, 4),
                nm_bal DECIMAL(20, 4),
                fc_pur_aset DECIMAL(20, 4),
                fc_bal DECIMAL(20, 4)
            )
        """,
    },
    "dim_public": {
        "pattern": "dim_public_*.csv",
        "ddl": """
            CREATE TABLE dim_public (
                code VARCHAR NOT NULL,
                code_type_id VARCHAR NOT NULL,
                "describe" VARCHAR NOT NULL
            )
        """,
    },
    "dim_branch": {
        "pattern": "dim_branch_*.csv",
        "ddl": """
            CREATE TABLE dim_branch (
                data_dt VARCHAR NOT NULL,
                org_id VARCHAR NOT NULL,
                org_name VARCHAR NOT NULL,
                up_org_id VARCHAR NOT NULL,
                up_org_name VARCHAR NOT NULL
            )
        """,
    },
}


def find_csv(data_dir: Path, pattern: str) -> Path:
    matches = sorted(data_dir.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"未找到 CSV: {data_dir / pattern}")
    if len(matches) > 1:
        print(f"警告: 匹配到多个文件，使用最新: {matches[-1].name}")
    return matches[-1]


def import_table(con: duckdb.DuckDBPyConnection, table: str, config: dict) -> int:
    csv_path = find_csv(DATA_DIR, config["pattern"])
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(config["ddl"].strip())
    con.execute(
        f"""
        INSERT INTO {table}
        SELECT * FROM read_csv(?, header = true, sample_size = -1)
        """,
        [str(csv_path)],
    )
    count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"  {table}: {count:,} 行  <- {csv_path.name}")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="导入 CSV 到 DuckDB")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"数据库文件路径（默认: {DEFAULT_DB_PATH}）",
    )
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    if args.db.exists():
        args.db.unlink()

    print(f"数据库: {args.db}")
    print(f"数据源: {DATA_DIR}\n")

    con = duckdb.connect(str(args.db))
    try:
        total = 0
        for table, config in TABLES.items():
            total += import_table(con, table, config)
        print(f"\n导入完成，共 {len(TABLES)} 张表，{total:,} 行。")
    finally:
        con.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
