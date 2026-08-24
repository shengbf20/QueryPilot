"""将新表 CSV 登记进 scripts/import_data.py 的 TABLES（ONBOARDING.md 步骤 ② 自动化）。

对给定的 CSV：
  1. 从文件名推表名（去 _YYYYMMDD 日期后缀）与 pattern；
  2. 全量扫描值域推 DDL 列类型（日期/编码保持 VARCHAR，整数 INTEGER/BIGINT，
     小数 DECIMAL(20,4)，其余 VARCHAR——与既有登记约定一致）；
  3. 生成 TABLES 条目文本，插入 import_data.py 的 TABLES 字典末尾（保注释）；
  4. 语法校验 + 临时内存库试导入（行数回报，不动真实库）；
  5. --import 时对 db/competition.duckdb 做单表轻量导入（DROP+CREATE+INSERT）。

用法:
  python scripts/add_table.py data_sim/dwd_cust_risk_assess_d.csv
  python scripts/add_table.py <csv> --dry-run     # 只看不写
  python scripts/add_table.py <csv> --import      # 登记并立即单表导入
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "import_data.py"
DEFAULT_DB_PATH = ROOT / "db" / "competition.duckdb"

_INT_RE = re.compile(r"^-?\d+$")
_DEC_RE = re.compile(r"^-?\d+\.\d+$")
_DATE_RE = re.compile(r"^\d{8}$")


def table_name_from_csv(path: Path) -> str:
    """文件名 → 表名：去 _YYYYMMDD 后缀（ads_cust_info_d_20260430 → ads_cust_info_d）。"""
    stem = path.stem
    return re.sub(r"_\d{8}$", "", stem)


def infer_column_type(values: list[str], name: str = "") -> str:
    """值域 + 列名约定 → DuckDB DDL 类型（与既有 TABLES 登记约定一致）。

    - 列名约定：``_cd`` / ``_id`` 后缀是编码/键列 → VARCHAR（防前导零丢失，
      且与 dim_public 字符串码直接可比，与既有 *_cd 列全部 VARCHAR 一致）；
    - 日期样式（全 8 位数字）→ VARCHAR（保字符串，A1 的 is_date 按字符串判断）；
    - 纯整数 → INTEGER（超 32 位 → BIGINT）；
    - 小数 → DECIMAL(20, 4)；
    - 其余 / 混合 / 含空值 → VARCHAR。
    """
    if name.endswith(("_cd", "_id")):
        return "VARCHAR"
    non_empty = [v for v in values if v != ""]
    if not non_empty:
        return "VARCHAR"
    if all(_DATE_RE.match(v) for v in non_empty):
        return "VARCHAR"
    if all(_INT_RE.match(v) for v in non_empty):
        return "BIGINT" if any(abs(int(v)) > 2**31 - 1 for v in non_empty) else "INTEGER"
    if all(_DEC_RE.match(v) for v in non_empty):
        return "DECIMAL(20, 4)"
    return "VARCHAR"


def infer_columns(csv_path: Path) -> list[tuple[str, str]]:
    """CSV 表头 + 值域 → [(列名, DDL 类型)]（保持表头顺序）。"""
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    columns = []
    for idx, name in enumerate(header):
        values = [row[idx] if idx < len(row) else "" for row in rows]
        columns.append((name, infer_column_type(values, name)))
    return columns


def build_entry_text(
    table: str,
    columns: list[tuple[str, str]],
    *,
    csv_dir: Path | None,
) -> str:
    """生成 TABLES 条目文本（缩进风格与既有条目一致）。"""
    col_lines = ",\n".join(f"                {name} {dtype}" for name, dtype in columns)
    dir_line = f'        "csv_dir": SIM_DATA_DIR,\n' if csv_dir else ""
    return (
        f'    # --- {table}（scripts/add_table.py 自动登记）---\n'
        f'    "{table}": {{\n'
        f'        "pattern": "{table}*.csv",\n'
        f'{dir_line}'
        f'        "ddl": """\n'
        f'            CREATE TABLE {table} (\n'
        f'{col_lines}\n'
        f'            )\n'
        f'        """,\n'
        f'    }},\n'
    )


def table_already_registered(script_text: str, table: str) -> bool:
    return re.search(rf'^    "{re.escape(table)}": \{{', script_text, re.M) is not None


def insert_entry(script_path: Path, entry_text: str) -> None:
    """在 TABLES 字典收口 ``}`` 前插入条目（保注释，纯文本手术）。"""
    lines = script_path.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(
        i for i, line in enumerate(lines) if line.startswith("TABLES: dict[str, dict] = {")
    )
    for i in range(start + 1, len(lines)):
        if lines[i].rstrip() == "}":
            lines[i:i] = [entry_text]
            script_path.write_text("".join(lines), encoding="utf-8")
            return
    raise ValueError(f"TABLES dict closing brace not found in {script_path}")


def verify_entry(table: str, columns: list[tuple[str, str]], csv_path: Path) -> int:
    """临时内存库试导入：按推断 DDL 建表 + 导入 CSV，返回行数（不动真实库）。"""
    import duckdb

    col_defs = ",\n".join(f"    {name} {dtype}" for name, dtype in columns)
    con = duckdb.connect()
    try:
        con.execute(f"CREATE TABLE {table} (\n{col_defs}\n)")
        con.execute(
            f"INSERT INTO {table} SELECT * FROM read_csv(?, header = true, sample_size = -1)",
            [str(csv_path)],
        )
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


def single_table_import(table: str, columns: list[tuple[str, str]], csv_path: Path) -> int:
    """单表轻量导入真实库（等价 import_data.import_table，不动其他表）。"""
    import duckdb

    col_defs = ",\n".join(f"    {name} {dtype}" for name, dtype in columns)
    con = duckdb.connect(str(DEFAULT_DB_PATH))
    try:
        con.execute(f"DROP TABLE IF EXISTS {table}")
        con.execute(f"CREATE TABLE {table} (\n{col_defs}\n)")
        con.execute(
            f"INSERT INTO {table} SELECT * FROM read_csv(?, header = true, sample_size = -1)",
            [str(csv_path)],
        )
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


def _syntax_check(script_path: Path) -> None:
    """插入后的 import_data.py 必须仍是合法 Python。"""
    import ast

    ast.parse(script_path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="将新表 CSV 自动登记进 scripts/import_data.py（类型自动推断）"
    )
    parser.add_argument("csv", type=Path, help="CSV 文件路径（如 data_sim/xxx.csv）")
    parser.add_argument("--table", default=None, help="覆盖表名（默认从文件名推断）")
    parser.add_argument("--dry-run", action="store_true", help="只打印条目，不写 import_data.py")
    parser.add_argument("--import", dest="do_import", action="store_true",
                        help="登记后立即对 db/competition.duckdb 做单表轻量导入")
    parser.add_argument("--force", action="store_true", help="表已登记时允许重复插入（慎用）")
    args = parser.parse_args(argv)

    csv_path = args.csv.resolve()
    if not csv_path.exists():
        print(f"错误: CSV 不存在: {csv_path}")
        return 1

    table = args.table or table_name_from_csv(csv_path)
    if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", table):
        print(f"错误: 非法表名: {table}")
        return 1

    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    if table_already_registered(script_text, table) and not args.force:
        print(f"错误: 表 {table} 已登记在 import_data.py（--force 可强制再插入）")
        return 1

    columns = infer_columns(csv_path)
    csv_dir = csv_path.parent.resolve()
    needs_dir = csv_dir != (ROOT / "data").resolve()
    entry_text = build_entry_text(table, columns, csv_dir=csv_dir if needs_dir else None)

    print(f"表名: {table}    CSV: {csv_path.name}    列: {len(columns)}")
    for name, dtype in columns:
        print(f"  {name:24} {dtype}")

    # 试导入验证（内存库）
    try:
        rows = verify_entry(table, columns, csv_path)
        print(f"试导入验证: {rows:,} 行，DDL 与 CSV 兼容 ✓")
    except Exception as exc:
        print(f"试导入验证失败: {exc}")
        return 1

    if args.dry_run:
        print("\n--- TABLES 条目（dry-run，未写盘）---")
        print(entry_text)
        return 0

    insert_entry(SCRIPT_PATH, entry_text)
    _syntax_check(SCRIPT_PATH)
    print(f"已登记: {SCRIPT_PATH}（TABLES += {table}）")

    if args.do_import:
        try:
            rows = single_table_import(table, columns, csv_path)
            print(f"单表导入: {table} {rows:,} 行 -> {DEFAULT_DB_PATH}")
        except Exception as exc:
            print(f"单表导入失败: {exc}")
            return 1

    print("\n下一步:")
    print("  PYTHONIOENCODING=utf-8 python -m querypilot.table_ops.discover " + table)
    print("  （或全量重建）PYTHONIOENCODING=utf-8 python scripts/import_data.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
