"""Validate join graph metadata."""

from __future__ import annotations

from querypilot.metadata_engine.join_graph_loader import JoinGraph, load_join_graph
from querypilot.metadata_engine.loader import EXPECTED_TABLES, load_all_tables
from querypilot.metadata_engine.validator import ValidationResult
from querypilot.metadata_engine.value_descriptors import load_value_descriptor_config


def validate_join_graph(result: ValidationResult | None = None) -> ValidationResult:
    result = result or ValidationResult()
    graph = load_join_graph()
    tables = load_all_tables()
    value_config = load_value_descriptor_config()

    _validate_tables(graph, tables, result)
    _validate_edges(graph, tables, value_config, result)
    _validate_paths(graph, result)
    return result


def _validate_tables(
    graph: JoinGraph,
    tables: dict,
    result: ValidationResult,
) -> None:
    for name in EXPECTED_TABLES:
        if name not in graph.tables:
            result.add_error(f"join_graph missing table: {name}")
        if name not in tables:
            result.add_error(f"metadata missing table: {name}")

    for name, graph_table in graph.tables.items():
        if name not in tables:
            continue
        meta = tables[name]
        if graph_table.alias != meta.alias:
            result.add_warning(
                f"join_graph alias for {name} ({graph_table.alias}) "
                f"!= table yaml alias ({meta.alias})"
            )


def _validate_edges(
    graph: JoinGraph,
    tables: dict,
    value_config,
    result: ValidationResult,
) -> None:
    seen_ids: set[str] = set()
    for edge in graph.edges.values():
        if edge.id in seen_ids:
            result.add_error(f"duplicate edge id: {edge.id}")
        seen_ids.add(edge.id)

        for table_name in (edge.from_table, edge.to_table):
            if table_name not in graph.tables:
                result.add_error(f"edge {edge.id} references unknown table: {table_name}")

        if edge.from_table not in tables or edge.to_table not in tables:
            continue

        from_cols = tables[edge.from_table].column_names
        to_cols = tables[edge.to_table].column_names

        for left, right in edge.join.items():
            if left not in from_cols:
                result.add_error(f"edge {edge.id}: join key '{left}' not in {edge.from_table}")
            if right not in to_cols:
                result.add_error(f"edge {edge.id}: join key '{right}' not in {edge.to_table}")

        for rule_id in edge.rules:
            if rule_id not in graph.rules:
                result.add_error(f"edge {edge.id} references unknown rule: {rule_id}")

        if edge.edge_type == "lookup" and edge.to_table == "dim_public":
            code_type_id = edge.filter.get("code_type_id")
            if not code_type_id:
                result.add_error(f"edge {edge.id}: dim_public lookup missing filter.code_type_id")
                continue

            left_col = next(iter(edge.join))
            mapped = value_config.get_code_type_id(edge.from_table, left_col)
            if mapped != code_type_id:
                result.add_error(
                    f"edge {edge.id}: filter code_type_id={code_type_id} "
                    f"!= value_descriptors mapping ({mapped}) for {edge.from_table}.{left_col}"
                )


def _validate_paths(graph: JoinGraph, result: ValidationResult) -> None:
    for path in graph.paths.values():
        for table_name in path.tables:
            if table_name not in graph.tables:
                result.add_error(f"path {path.id} references unknown table: {table_name}")

        for edge_id in path.edges:
            if edge_id not in graph.edges:
                result.add_error(f"path {path.id} references unknown edge: {edge_id}")

        if len(path.tables) < 2:
            result.add_error(f"path {path.id} must include at least 2 tables")

        if not path.edges:
            result.add_warning(f"path {path.id} has no edges defined")
