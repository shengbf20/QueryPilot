"""A1 结构自动发现：information_schema + 每列 DISTINCT 统计 → 表结构画像（logs/08 §三）。

纯机械输出，供 A2 骨架生成与问卷（Q1 用途 / Q3 粒度 / Q4 列含义）做底稿：
  - 列级：类型 / 空值数 / 基数 / 唯一性 / 常量列 / 日期列
  - 表级：行数 / 层次推断（前缀约定）/ 主键候选（单列唯一，组合键交 A3 + 人工）
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

import duckdb

from querypilot.table_ops.candidates import ColumnProfile, _profile_columns

# 数仓前缀约定：表名第一段 → layer
_LAYER_PREFIXES = {"dim", "dwd", "dws", "ads", "ods"}


def _infer_layer(table: str) -> str:
    """按表名前缀推断 layer（dim_/dwd_/dws_/ads_/ods_），未识别返回空串。"""
    head = table.split("_", 1)[0]
    return head if head in _LAYER_PREFIXES else ""


@dataclass
class ColumnStat:
    """单列结构画像（复用 A3 的 DISTINCT 探测）。"""

    name: str
    db_type: str
    profile: ColumnProfile

    @property
    def is_unique(self) -> bool:
        return self.profile.is_unique

    @property
    def is_constant(self) -> bool:
        return self.profile.distinct_count == 1

    @property
    def is_date(self) -> bool:
        return self.profile.is_date


@dataclass
class TableProfile:
    """表结构画像（A2 YAML 骨架的机械输入）。"""

    table: str
    row_count: int
    columns: list[ColumnStat]
    suggested_layer: str

    def get_column(self, name: str) -> ColumnStat | None:
        for col in self.columns:
            if col.name == name:
                return col
        return None

    @property
    def primary_key_candidates(self) -> list[str]:
        """单列唯一且无空值的列；组合键（如快照表 data_dt+pty_id）交 A3 键候选 + 人工确认。"""
        return [
            c.name
            for c in self.columns
            if c.is_unique and c.profile.null_count == 0
        ]

    @property
    def constant_columns(self) -> list[str]:
        return [c.name for c in self.columns if c.is_constant]

    @property
    def date_columns(self) -> list[str]:
        return [c.name for c in self.columns if c.is_date]

    def to_dict(self) -> dict[str, Any]:
        """A2 骨架生成所需的结构化视图。"""
        return {
            "table": self.table,
            "row_count": self.row_count,
            "suggested_layer": self.suggested_layer,
            "primary_key_candidates": self.primary_key_candidates,
            "constant_columns": self.constant_columns,
            "date_columns": self.date_columns,
            "columns": [
                {
                    "name": c.name,
                    "type": c.db_type,
                    "distinct_count": c.profile.distinct_count,
                    "null_count": c.profile.null_count,
                    "is_unique": c.is_unique,
                    "is_constant": c.is_constant,
                    "is_date": c.is_date,
                }
                for c in self.columns
            ],
        }


def discover_table(
    table: str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
) -> TableProfile:
    """对已入库的裸表做结构画像（纯机械，零 LLM，不读任何 YAML）。"""
    from querypilot.db import get_connection

    own_con = con is None
    con = con or get_connection(read_only=True)
    try:
        types = {
            row[0]: row[1]
            for row in con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = ?",
                [table],
            ).fetchall()
        }
        if not types:
            raise ValueError(f"table not found in database: {table}")
        row_count = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        profiles = _profile_columns(con, table)
    finally:
        if own_con:
            con.close()

    columns = [
        ColumnStat(name=name, db_type=types[name], profile=profiles[name])
        for name in types  # 保持 information_schema 的列顺序
    ]
    return TableProfile(
        table=table,
        row_count=row_count,
        columns=columns,
        suggested_layer=_infer_layer(table),
    )


def discover_report(table: str, *, con: duckdb.DuckDBPyConnection | None = None) -> str:
    """人类可读的结构画像报告（问卷 Q1/Q3/Q4 的机械底稿）。"""
    profile = discover_table(table, con=con)

    pk = profile.primary_key_candidates
    if pk:
        pk_text = ", ".join(pk) + "（单列唯一）"
    elif profile.date_columns and profile.row_count:
        pk_text = "无单列唯一键（快照/明细表，组合键见键候选报告）"
    else:
        pk_text = "无单列唯一键（组合键见键候选报告）"

    lines = [f"表 {table} 结构画像", "=" * 60]
    lines.append(f"行数: {profile.row_count}    推断层次: {profile.suggested_layer or '未知'}（前缀约定）")
    lines.append(f"主键候选: {pk_text}")
    if profile.constant_columns:
        consts = []
        for name in profile.constant_columns:
            col = profile.get_column(name)
            value = next(iter(col.profile.distinct_values)) if col and col.profile.distinct_values else ""
            consts.append(f"{name}='{value}'")
        lines.append(f"常量列（快照/分区特征）: {', '.join(consts)}")
    if profile.date_columns:
        lines.append(f"日期列: {', '.join(profile.date_columns)}")
    lines.append("")
    lines.append(f"{'列':20} {'类型':16} {'基数':>8} {'空值':>6} 特征")
    lines.append("-" * 70)
    for c in profile.columns:
        flags = []
        if c.is_unique:
            flags.append("唯一")
        if c.is_constant:
            flags.append("常量")
        if c.is_date:
            flags.append("日期")
        lines.append(
            f"{c.name:20} {c.db_type:16} {c.profile.distinct_count:>8} "
            f"{c.profile.null_count:>6} {','.join(flags)}"
        )
    return "\n".join(lines)


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m querypilot.table_ops.discover",
        description="新表结构画像（A1 结构自动发现）",
    )
    parser.add_argument("table", help="表名（需已导入 DuckDB）")
    parser.add_argument("--json", action="store_true", help="输出 JSON（供 A2 骨架生成）")
    args = parser.parse_args(argv)

    if args.json:
        import json

        print(json.dumps(discover_table(args.table).to_dict(), ensure_ascii=False, indent=2))
    else:
        print(discover_report(args.table))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
