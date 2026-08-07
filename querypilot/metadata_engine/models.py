"""Metadata data models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ColumnMeta:
    name: str
    type: str
    description: str
    aliases: list[str] = field(default_factory=list)
    code_type_id: str | None = None
    lookup: str | None = None
    enum_ref: str | None = None
    enum_values: dict[str, str] = field(default_factory=dict)
    format: str | None = None
    sql_name: str | None = None


@dataclass
class TableMeta:
    table: str
    alias: str
    layer: str
    description: str
    primary_key: list[str]
    columns: list[ColumnMeta]
    usage: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def column_names(self) -> set[str]:
        return {col.name for col in self.columns}

    def get_column(self, name: str) -> ColumnMeta | None:
        for col in self.columns:
            if col.name == name:
                return col
        return None
