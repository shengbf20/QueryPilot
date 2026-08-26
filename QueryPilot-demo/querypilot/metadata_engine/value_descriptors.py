"""Value descriptor loading and resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import yaml

from querypilot.config import get_settings


@dataclass(frozen=True)
class ColumnRef:
    table: str
    column: str


@dataclass(frozen=True)
class CodeTypeMapping:
    code_type_id: str
    label: str
    column_refs: tuple[ColumnRef, ...]


@dataclass
class ValueDescriptorRegistry:
    """Merged view of YAML mappings and dim_public code dictionary."""

    code_types: dict[str, CodeTypeMapping]
    column_to_code_type: dict[tuple[str, str], str]
    static_enums: dict[str, dict[str, str]]
    unused_code_types: dict[str, str]
    codes_by_type: dict[str, dict[str, str]] = field(default_factory=dict)
    priority_codes: dict[str, list[str]] = field(default_factory=dict)

    def get_code_type_id(self, table: str, column: str) -> str | None:
        return self.column_to_code_type.get((table, column))

    def resolve(self, table: str, column: str, code: str) -> str | None:
        code_type_id = self.get_code_type_id(table, column)
        if code_type_id is None:
            return None
        return self.codes_by_type.get(code_type_id, {}).get(code)

    def resolve_static(self, enum_ref: str, value: str) -> str | None:
        return self.static_enums.get(enum_ref, {}).get(value)

    def get_codes_for_column(self, table: str, column: str) -> dict[str, str]:
        code_type_id = self.get_code_type_id(table, column)
        if code_type_id is None:
            return {}
        return dict(self.codes_by_type.get(code_type_id, {}))

    def get_codes_for_type(self, code_type_id: str) -> dict[str, str]:
        return dict(self.codes_by_type.get(code_type_id, {}))

    def _ordered_code_items(self, code_type_id: str, pairs: dict[str, str]) -> list[tuple[str, str]]:
        """Return (code, describe) pairs with priority codes first."""
        priority = [str(c) for c in self.priority_codes.get(code_type_id, [])]
        seen: set[str] = set()
        ordered: list[tuple[str, str]] = []
        for code in priority:
            if code in pairs and code not in seen:
                ordered.append((code, pairs[code]))
                seen.add(code)
        for code, desc in pairs.items():
            if code not in seen:
                ordered.append((code, desc))
                seen.add(code)
        return ordered

    def format_for_prompt(
        self,
        table: str,
        column: str,
        *,
        max_items: int | None = None,
    ) -> str:
        code_type_id = self.get_code_type_id(table, column)
        if code_type_id is None:
            return ""

        mapping = self.code_types.get(code_type_id)
        label = mapping.label if mapping else code_type_id
        pairs = self.get_codes_for_column(table, column)
        if not pairs:
            return f"{label}({column}): 字典数据未加载"

        items = self._ordered_code_items(code_type_id, pairs)
        if max_items is not None and len(items) > max_items:
            shown = items[:max_items]
            suffix = f" ...共{len(items)}项"
        else:
            shown = items
            suffix = ""

        body = ", ".join(f"{desc}({code})" for code, desc in shown)
        return f"{label}({column}): {body}{suffix}"

    def format_static_for_prompt(self, enum_ref: str) -> str:
        pairs = self.static_enums.get(enum_ref, {})
        if not pairs:
            return ""
        body = ", ".join(f"{desc}({code})" for code, desc in pairs.items())
        return f"{enum_ref}: {body}"


def load_value_descriptor_config(path: Path | None = None) -> ValueDescriptorRegistry:
    path = path or (get_settings().metadata_dir / "value_descriptors.yaml")
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    code_types: dict[str, CodeTypeMapping] = {}
    column_to_code_type: dict[tuple[str, str], str] = {}

    for code_type_id, info in raw.get("code_types", {}).items():
        refs = tuple(
            ColumnRef(table=ref["table"], column=ref["column"])
            for ref in info.get("column_refs", [])
        )
        code_types[code_type_id] = CodeTypeMapping(
            code_type_id=code_type_id,
            label=info["label"],
            column_refs=refs,
        )
        for ref in refs:
            column_to_code_type[(ref.table, ref.column)] = code_type_id

    raw_priority = raw.get("priority_codes") or {}
    priority_codes: dict[str, list[str]] = {
        str(code_type_id): [str(c) for c in (codes or [])]
        for code_type_id, codes in raw_priority.items()
    }

    return ValueDescriptorRegistry(
        code_types=code_types,
        column_to_code_type=column_to_code_type,
        static_enums=raw.get("static_enums", {}),
        unused_code_types=raw.get("unused_code_types", {}),
        priority_codes=priority_codes,
    )


def load_codes_from_db(
    registry: ValueDescriptorRegistry,
    con: duckdb.DuckDBPyConnection,
) -> None:
    rows = con.execute(
        """
        SELECT code_type_id, code, "describe"
        FROM dim_public
        ORDER BY code_type_id, code
        """
    ).fetchall()

    codes_by_type: dict[str, dict[str, str]] = {}
    for code_type_id, code, describe in rows:
        codes_by_type.setdefault(str(code_type_id), {})[str(code)] = str(describe)

    registry.codes_by_type = codes_by_type


def load_value_descriptors(
    *,
    db_con: duckdb.DuckDBPyConnection | None = None,
    config_path: Path | None = None,
) -> ValueDescriptorRegistry:
    registry = load_value_descriptor_config(config_path)
    if db_con is not None:
        load_codes_from_db(registry, db_con)
    else:
        from querypilot.db import get_connection

        con = get_connection(read_only=True)
        try:
            load_codes_from_db(registry, con)
        finally:
            con.close()
    return registry
