"""Validate value descriptor mappings against table metadata and database."""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from querypilot.metadata_engine.loader import load_all_tables
from querypilot.metadata_engine.validator import ValidationResult
from querypilot.metadata_engine.value_descriptors import (
    ValueDescriptorRegistry,
    load_value_descriptor_config,
    load_value_descriptors,
)


@dataclass
class ValueDescriptorValidationResult(ValidationResult):
    stats: dict[str, int] = field(default_factory=dict)


def validate_value_descriptor_config(registry: ValueDescriptorRegistry) -> ValueDescriptorValidationResult:
    result = ValueDescriptorValidationResult()
    tables = load_all_tables()

    yaml_coded_columns: dict[tuple[str, str], str] = {}
    for meta in tables.values():
        for col in meta.columns:
            if col.code_type_id:
                yaml_coded_columns[(meta.table, col.name)] = col.code_type_id

    for (table, column), code_type_id in yaml_coded_columns.items():
        mapped = registry.get_code_type_id(table, column)
        if mapped is None:
            result.add_error(
                f"table YAML has code_type_id={code_type_id} on {table}.{column}, "
                "but value_descriptors.yaml has no mapping"
            )
        elif mapped != code_type_id:
            result.add_error(
                f"code_type_id mismatch on {table}.{column}: "
                f"table YAML={code_type_id}, value_descriptors={mapped}"
            )

    for (table, column), code_type_id in registry.column_to_code_type.items():
        if (table, column) not in yaml_coded_columns:
            result.add_warning(
                f"value_descriptors maps {table}.{column} -> {code_type_id}, "
                "but table YAML has no code_type_id"
            )

    for enum_name, values in registry.static_enums.items():
        if not values:
            result.add_error(f"static_enums.{enum_name} is empty")

    result.stats["coded_columns"] = len(yaml_coded_columns)
    result.stats["code_types"] = len(registry.code_types)
    result.stats["unused_code_types"] = len(registry.unused_code_types)
    return result


def validate_value_descriptors_against_db(
    registry: ValueDescriptorRegistry,
    con: duckdb.DuckDBPyConnection,
) -> ValueDescriptorValidationResult:
    result = validate_value_descriptor_config(registry)

    db_types = {
        str(row[0])
        for row in con.execute("SELECT DISTINCT code_type_id FROM dim_public").fetchall()
    }

    for code_type_id in registry.code_types:
        if code_type_id not in db_types:
            result.add_error(f"code_type_id '{code_type_id}' not found in dim_public")
        elif not registry.get_codes_for_type(code_type_id):
            result.add_error(f"code_type_id '{code_type_id}' has no codes loaded from dim_public")

    for code_type_id in registry.unused_code_types:
        if code_type_id not in db_types:
            result.add_warning(f"unused_code_type '{code_type_id}' not in dim_public")

    coded_checks = [
        ("ads_cust_info_d", "gender_cd", "500"),
        ("ads_cust_info_d", "edu_cd", "600"),
        ("ads_cust_info_d", "prof_cd", "700"),
        ("ads_cust_info_d", "cust_lvl_cd", "100"),
        ("ads_cust_info_d", "cust_status", "200"),
    ]
    for table, column, code_type_id in coded_checks:
        orphan_count = con.execute(
            f"""
            SELECT COUNT(*)
            FROM {table} AS t
            LEFT JOIN dim_public AS p
                ON t.{column} = p.code
               AND p.code_type_id = ?
            WHERE t.{column} IS NOT NULL
              AND p.code IS NULL
            """,
            [code_type_id],
        ).fetchone()[0]
        if orphan_count:
            result.add_error(
                f"{table}.{column} has {orphan_count} values not found in dim_public "
                f"(code_type_id={code_type_id})"
            )

    result.stats["dim_public_code_types"] = len(db_types)
    result.stats["dim_public_codes"] = con.execute("SELECT COUNT(*) FROM dim_public").fetchone()[0]
    return result


def validate_value_descriptors(
    *,
    db_con: duckdb.DuckDBPyConnection | None = None,
) -> ValueDescriptorValidationResult:
    if db_con is None:
        registry = load_value_descriptors()
        from querypilot.db import get_connection

        con = get_connection(read_only=True)
        try:
            return validate_value_descriptors_against_db(registry, con)
        finally:
            con.close()

    registry = load_value_descriptor_config()
    from querypilot.metadata_engine.value_descriptors import load_codes_from_db

    load_codes_from_db(registry, db_con)
    return validate_value_descriptors_against_db(registry, db_con)
