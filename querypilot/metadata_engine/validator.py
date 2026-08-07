"""Validate table metadata against schema and join graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from querypilot.metadata_engine.loader import DB_COLUMNS, EXPECTED_TABLES, load_all_tables
from querypilot.metadata_engine.models import TableMeta

VALID_LAYERS = {"dim", "dwd", "dws", "ads"}
VALID_CODE_TYPE_IDS = {"100", "200", "500", "600", "700"}


@dataclass
class ValidationResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


def validate_table(meta: TableMeta, result: ValidationResult) -> None:
    if meta.layer not in VALID_LAYERS:
        result.add_error(f"{meta.table}: invalid layer '{meta.layer}'")

    yaml_cols = meta.column_names
    db_cols = set(DB_COLUMNS.get(meta.table, []))
    if not db_cols:
        result.add_error(f"{meta.table}: not in DB_COLUMNS registry")
        return

    missing = db_cols - yaml_cols
    extra = yaml_cols - db_cols
    if missing:
        result.add_error(f"{meta.table}: missing columns in YAML: {sorted(missing)}")
    if extra:
        result.add_error(f"{meta.table}: extra columns in YAML: {sorted(extra)}")

    for pk in meta.primary_key:
        if pk not in yaml_cols:
            result.add_error(f"{meta.table}: primary_key '{pk}' not in columns")

    if not meta.alias or not meta.description:
        result.add_error(f"{meta.table}: alias/description must not be empty")

    for col in meta.columns:
        if not col.description:
            result.add_error(f"{meta.table}.{col.name}: missing description")
        if col.code_type_id and col.code_type_id not in VALID_CODE_TYPE_IDS:
            result.add_warning(
                f"{meta.table}.{col.name}: code_type_id '{col.code_type_id}' not in known set"
            )
        if col.lookup and col.lookup not in EXPECTED_TABLES:
            result.add_error(f"{meta.table}.{col.name}: unknown lookup table '{col.lookup}'")


def validate_join_graph(tables: dict[str, TableMeta], result: ValidationResult) -> None:
    from querypilot.metadata_engine.join_graph_validator import validate_join_graph as _validate

    _validate(result)


def validate_all(tables_dir: Path | None = None) -> ValidationResult:
    result = ValidationResult()
    tables = load_all_tables(tables_dir)

    if len(tables) != len(EXPECTED_TABLES):
        result.add_error(f"expected {len(EXPECTED_TABLES)} tables, got {len(tables)}")

    for meta in tables.values():
        validate_table(meta, result)

    validate_join_graph(tables, result)
    return result
