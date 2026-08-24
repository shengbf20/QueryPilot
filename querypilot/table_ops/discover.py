"""A1 结构自动发现 + A2 YAML 骨架生成（logs/08 §三）。

A1 纯机械输出表结构画像，供问卷（Q1 用途 / Q3 粒度 / Q4 列含义）做底稿：
  - 列级：类型 / 空值数 / 基数 / 唯一性 / 常量列 / 日期列
  - 表级：行数 / 层次推断（前缀约定）/ 主键候选（单列唯一，组合键交 A3 + 人工）

A2 在 A1 之上合并 A3 键候选、A4 枚举候选，产出表 YAML 骨架：
物理字段（table/layer/type/format/code_type_id/enum_ref/…）机器填好，
语义字段（alias/description/usage/aliases/enum 含义）留空待问卷回填。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

import duckdb
import yaml

from querypilot.table_ops.candidates import (
    ColumnProfile,
    EnumCandidate,
    _profile_columns,
    build_key_registry,
    enum_candidates,
    key_candidates,
)

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


# ---------- A2 YAML 骨架生成（logs/08 §三 A2：物理部分机器填，描述留空） ----------


def _best_enum_candidate(cands: list[EnumCandidate]) -> EnumCandidate | None:
    """每列取最优枚举候选：dict > static > new，同 kind 取包含率高者。"""
    if not cands:
        return None
    rank = {"dict": 0, "static": 1, "new": 2}
    return min(cands, key=lambda c: (rank[c.kind], -c.containment))


def _suggest_primary_key(
    profile: TableProfile,
    known_key_columns: set[str],
) -> list[str]:
    """主键建议：单列唯一候选中优先已知业务键（registry 列），否则取首个。

    注意：常量快照日是否入主键属业务口径（dim_branch 入、ads 不入），
    机械不可判定——核心唯一键之外的部分交人工（问卷 Q3，notes 有提示）。
    无任何唯一候选的明细表（如 tran）返回空列表交人工。
    """
    candidates = profile.primary_key_candidates
    if not candidates:
        return []
    for name in candidates:
        if name in known_key_columns:
            return [name]
    return candidates[:1]


def build_skeleton(
    table: str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    metadata: Any = None,
) -> dict[str, Any]:
    """生成表 YAML 骨架（A1 结构 + A3 键 + A4 枚举，纯机械）。

    返回可直接 ``yaml.safe_dump`` 的 dict，字段顺序与 loader 读取顺序一致。
    语义字段（alias/description/usage/aliases/枚举含义）留空，由问卷回填。
    """
    from querypilot.db import get_connection

    if metadata is None:
        from querypilot.metadata_engine import load_metadata

        metadata = load_metadata(load_db_codes=False)

    own_con = con is None
    con = con or get_connection(read_only=True)
    try:
        profile = discover_table(table, con=con)
        # 键候选列（A3）不产 "new" 枚举骨架——键列值域是标识符，不是待解释枚举
        key_cols = {c.column for c in key_candidates(table, con=con, metadata=metadata)}
        enums = enum_candidates(table, con=con, metadata=metadata, key_columns=key_cols)
    finally:
        if own_con:
            con.close()

    enum_by_col: dict[str, list[EnumCandidate]] = {}
    for c in enums:
        enum_by_col.setdefault(c.column, []).append(c)

    known_keys = {t.column for t in build_key_registry(metadata)}
    pk = _suggest_primary_key(profile, known_keys)

    columns: list[dict[str, Any]] = []
    for cs in profile.columns:
        col: dict[str, Any] = {
            "name": cs.name,
            "type": cs.db_type,
            "description": "",
            "aliases": [],
        }
        if cs.is_date:
            col["format"] = "YYYYMMDD"
        best = _best_enum_candidate(enum_by_col.get(cs.name, []))
        if best is not None:
            if best.kind == "dict":
                col["code_type_id"] = best.match_key
                col["lookup"] = "dim_public"
            elif best.kind == "static":
                col["enum_ref"] = best.match_key
            else:  # new：值域骨架已列出，含义待问卷 Q6 填空
                col["enum_values"] = {v: "" for v in best.value_meanings}
        columns.append(col)

    notes: list[str] = []
    for name in profile.constant_columns:
        cs = profile.get_column(name)
        if cs is not None and cs.is_date:
            value = next(iter(cs.profile.distinct_values))
            notes.append(f"{name} 固定为 {value}（快照日）")
            if pk:
                notes.append(f"主键是否含快照日 {name} 需人工确认（问卷 Q3）")
    if not pk:
        notes.append("无单列唯一键：组合主键需人工确认（问卷 Q3）")

    return {
        "table": table,
        "alias": "",
        "layer": profile.suggested_layer,
        "description": "",
        "primary_key": pk,
        "usage": [],
        "notes": notes,
        "columns": columns,
    }


def render_skeleton_yaml(
    table: str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    metadata: Any = None,
) -> str:
    """渲染 YAML 骨架文本（不落盘；落盘由问卷确认后的 A5/A6 register 负责）。"""
    skeleton = build_skeleton(table, con=con, metadata=metadata)
    return yaml.safe_dump(
        skeleton,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m querypilot.table_ops.discover",
        description="新表结构画像与 YAML 骨架（A1 结构发现 + A2 骨架生成）",
    )
    parser.add_argument("table", help="表名（需已导入 DuckDB）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 画像（A1）")
    parser.add_argument(
        "--skeleton",
        action="store_true",
        help="输出表 YAML 骨架（A2，语义字段留空待问卷）",
    )
    args = parser.parse_args(argv)

    if args.skeleton:
        print(render_skeleton_yaml(args.table))
    elif args.json:
        import json

        print(json.dumps(discover_table(args.table).to_dict(), ensure_ascii=False, indent=2))
    else:
        print(discover_report(args.table))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
