"""Unified metadata validation across tables, value descriptors, and join graph."""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from querypilot.metadata_engine.join_graph_loader import JoinGraph, load_join_graph
from querypilot.metadata_engine.join_graph_validator import validate_join_graph
from querypilot.metadata_engine.loader import EXPECTED_TABLES, load_all_tables
from querypilot.metadata_engine.models import TableMeta
from querypilot.metadata_engine.validator import ValidationResult, validate_table
from querypilot.metadata_engine.value_descriptors import (
    ValueDescriptorRegistry,
    load_value_descriptor_config,
    load_value_descriptors,
)
from querypilot.metadata_engine.value_validator import (
    ValueDescriptorValidationResult,
    validate_value_descriptor_config,
    validate_value_descriptors_against_db,
)


@dataclass
class MetadataValidationResult(ValidationResult):
    sections: dict[str, ValidationResult] = field(default_factory=dict)
    stats: dict[str, int | str] = field(default_factory=dict)


def _merge_result(
    target: MetadataValidationResult,
    source: ValidationResult,
    section: str,
    *,
    prefix: str = "",
) -> None:
    section_result = ValidationResult(
        ok=source.ok,
        errors=list(source.errors),
        warnings=list(source.warnings),
    )
    target.sections[section] = section_result

    for error in source.errors:
        target.add_error(f"{prefix}{error}" if prefix else error)
    for warning in source.warnings:
        target.add_warning(f"{prefix}{warning}" if prefix else warning)


def _validate_tables_step(tables: dict[str, TableMeta]) -> ValidationResult:
    result = ValidationResult()
    if len(tables) != len(EXPECTED_TABLES):
        result.add_error(f"expected {len(EXPECTED_TABLES)} tables, got {len(tables)}")
    for meta in tables.values():
        validate_table(meta, result)
    return result


def _cross_validate(
    tables: dict[str, TableMeta],
    registry: ValueDescriptorRegistry,
    graph: JoinGraph,
    result: MetadataValidationResult,
) -> None:
    """Cross-check consistency between Step 1 / 2 / 3 artifacts."""

    for meta in tables.values():
        for col in meta.columns:
            if col.enum_ref and col.enum_ref not in registry.static_enums:
                result.add_error(
                    f"[cross] {meta.table}.{col.name}: enum_ref '{col.enum_ref}' "
                    "not defined in value_descriptors.static_enums"
                )

    lookup_edges = {
        (edge.from_table, next(iter(edge.join))): edge
        for edge in graph.edges.values()
        if edge.edge_type == "lookup" and edge.to_table == "dim_public"
    }

    for meta in tables.values():
        for col in meta.columns:
            if not col.code_type_id:
                continue
            key = (meta.table, col.name)
            if key not in lookup_edges:
                result.add_error(
                    f"[cross] {meta.table}.{col.name}: coded column missing "
                    "dim_public lookup edge in join_graph.yaml"
                )
                continue
            edge = lookup_edges[key]
            if edge.filter.get("code_type_id") != col.code_type_id:
                result.add_error(
                    f"[cross] {meta.table}.{col.name}: join_graph code_type_id "
                    f"{edge.filter.get('code_type_id')} != table yaml {col.code_type_id}"
                )

    for (table, column), edge in lookup_edges.items():
        meta = tables.get(table)
        if meta is None:
            continue
        col = meta.get_column(column)
        if col is None:
            result.add_error(f"[cross] join_graph edge {edge.id} references unknown column {table}.{column}")
        elif not col.code_type_id:
            result.add_error(
                f"[cross] join_graph edge {edge.id} maps {table}.{column} "
                "but table yaml has no code_type_id"
            )


def validate_metadata_all(
    *,
    db_con: duckdb.DuckDBPyConnection | None = None,
    skip_db: bool = False,
) -> MetadataValidationResult:
    """Run Step 1 / 2 / 3 validation and cross-checks in one pass."""
    result = MetadataValidationResult()
    tables = load_all_tables()
    graph = load_join_graph()

    step1 = _validate_tables_step(tables)
    _merge_result(result, step1, "tables")

    if skip_db:
        registry = load_value_descriptor_config()
        step2: ValueDescriptorValidationResult = validate_value_descriptor_config(registry)
    else:
        if db_con is None:
            registry = load_value_descriptors()
            from querypilot.db import get_connection

            con = get_connection(read_only=True)
            try:
                step2 = validate_value_descriptors_against_db(registry, con)
            finally:
                con.close()
        else:
            registry = load_value_descriptor_config()
            from querypilot.metadata_engine.value_descriptors import load_codes_from_db

            load_codes_from_db(registry, db_con)
            step2 = validate_value_descriptors_against_db(registry, db_con)

    _merge_result(result, step2, "value_descriptors")
    result.stats.update(step2.stats)

    step3 = ValidationResult()
    validate_join_graph(step3)
    _merge_result(result, step3, "join_graph")

    _cross_validate(tables, registry, graph, result)

    result.stats["tables"] = len(tables)
    result.stats["edges"] = len(graph.edges)
    result.stats["paths"] = len(graph.paths)
    result.stats["db_checked"] = not skip_db
    return result
