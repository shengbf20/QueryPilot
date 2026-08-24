"""Load table metadata from YAML files.

表清单由 ``metadata/tables/`` 目录扫描动态发现（discover_table_names），
不再维护代码内副本；加新表 = 放一个 YAML 文件。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from querypilot.config import get_settings
from querypilot.metadata_engine.models import ColumnMeta, TableMeta


def _parse_column(raw: dict) -> ColumnMeta:
    return ColumnMeta(
        name=raw["name"],
        type=raw["type"],
        description=raw["description"],
        aliases=raw.get("aliases", []),
        code_type_id=raw.get("code_type_id"),
        lookup=raw.get("lookup"),
        enum_ref=raw.get("enum_ref"),
        enum_values=raw.get("enum_values", {}),
        format=raw.get("format"),
        sql_name=raw.get("sql_name"),
    )


def _parse_table(raw: dict) -> TableMeta:
    return TableMeta(
        table=raw["table"],
        alias=raw["alias"],
        layer=raw["layer"],
        description=raw["description"],
        primary_key=raw["primary_key"],
        columns=[_parse_column(c) for c in raw["columns"]],
        usage=raw.get("usage", []),
        notes=raw.get("notes", []),
    )


def load_table_meta(path: Path) -> TableMeta:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return _parse_table(raw)


def discover_table_names(tables_dir: Path | None = None) -> list[str]:
    """扫描 metadata/tables/*.yaml，返回排序后的表名清单。"""
    tables_dir = tables_dir or (get_settings().metadata_dir / "tables")
    return sorted(p.stem for p in tables_dir.glob("*.yaml"))


def load_all_tables(tables_dir: Path | None = None) -> dict[str, TableMeta]:
    tables_dir = tables_dir or (get_settings().metadata_dir / "tables")
    result: dict[str, TableMeta] = {}
    for table_name in discover_table_names(tables_dir):
        meta = load_table_meta(tables_dir / f"{table_name}.yaml")
        if meta.table != table_name:
            raise ValueError(f"{table_name}.yaml: table field '{meta.table}' != expected '{table_name}'")
        result[table_name] = meta
    return result
