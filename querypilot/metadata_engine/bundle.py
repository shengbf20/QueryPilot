"""Unified metadata bundle and loader (Step 4)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

from querypilot.metadata_engine.join_graph import JoinGraphEngine, JoinPlan, create_join_graph_engine
from querypilot.metadata_engine.join_graph_loader import JoinGraph, load_join_graph
from querypilot.metadata_engine.loader import load_all_tables
from querypilot.metadata_engine.metadata_validator import MetadataValidationResult, validate_metadata_all
from querypilot.metadata_engine.metrics import MetricDef, load_metrics
from querypilot.metadata_engine.models import TableMeta
from querypilot.metadata_engine.value_descriptors import (
    ValueDescriptorRegistry,
    load_codes_from_db,
    load_value_descriptor_config,
)


@dataclass
class MetadataBundle:
    """All metadata layers loaded and ready for Agent / Schema Pruner."""

    tables: dict[str, TableMeta]
    values: ValueDescriptorRegistry
    join_graph: JoinGraph
    engine: JoinGraphEngine
    metrics: list[MetricDef]

    def get_table(self, name: str) -> TableMeta:
        if name not in self.tables:
            raise KeyError(f"Unknown table: {name}")
        return self.tables[name]

    def validate(self, *, skip_db: bool = False) -> MetadataValidationResult:
        return validate_metadata_all(skip_db=skip_db)

    def expand_tables(self, seeds: list[str]) -> JoinPlan:
        return self.engine.expand_tables(seeds)

    def format_table_schema(self, table_name: str, *, include_values: bool = True) -> str:
        """Render a single table schema snippet for LLM prompts."""
        meta = self.get_table(table_name)
        lines = [
            f"表: {meta.table} ({meta.alias})",
            f"说明: {meta.description}",
            "字段:",
        ]
        for col in meta.columns:
            alias_text = f"，别名: {', '.join(col.aliases)}" if col.aliases else ""
            lines.append(f"  - {col.name} ({col.type}): {col.description}{alias_text}")
            if include_values and col.code_type_id:
                value_text = self.values.format_for_prompt(meta.table, col.name, max_items=8)
                if value_text:
                    lines.append(f"    枚举: {value_text}")
            elif include_values and col.enum_ref:
                value_text = self.values.format_static_for_prompt(col.enum_ref)
                if value_text:
                    lines.append(f"    枚举: {value_text}")
        return "\n".join(lines)

    def format_schema_for_tables(self, table_names: list[str], *, include_values: bool = True) -> str:
        parts = [self.format_table_schema(name, include_values=include_values) for name in table_names]
        return "\n\n".join(parts)

    def prune_schema(self, question: str, **kwargs: object):
        """Shortcut to cached prune for this bundle (``use_cache=False`` to bypass)."""
        from querypilot.cache.metadata_cache import get_pruned_schema

        return get_pruned_schema(question, self, **kwargs)  # type: ignore[arg-type]


def load_metadata_uncached(
    *,
    tables_dir: Path | None = None,
    join_graph_path: Path | None = None,
    value_config_path: Path | None = None,
    metrics_path: Path | None = None,
    load_db_codes: bool = True,
    db_con: duckdb.DuckDBPyConnection | None = None,
) -> MetadataBundle:
    """Load metadata from disk/DB without process-local caching."""
    tables = load_all_tables(tables_dir)
    join_graph = load_join_graph(join_graph_path)
    values = load_value_descriptor_config(value_config_path)
    metrics = load_metrics(metrics_path)

    if load_db_codes:
        if db_con is not None:
            load_codes_from_db(values, db_con)
        else:
            from querypilot.db import get_connection

            con = get_connection(read_only=True)
            try:
                load_codes_from_db(values, con)
            finally:
                con.close()

    engine = JoinGraphEngine(join_graph)
    return MetadataBundle(
        tables=tables,
        values=values,
        join_graph=join_graph,
        engine=engine,
        metrics=metrics,
    )


def load_metadata(
    *,
    tables_dir: Path | None = None,
    join_graph_path: Path | None = None,
    value_config_path: Path | None = None,
    metrics_path: Path | None = None,
    load_db_codes: bool = True,
    db_con: duckdb.DuckDBPyConnection | None = None,
    use_cache: bool | None = None,
) -> MetadataBundle:
    """Load Step 1/2/3 metadata into a single bundle (cached by default)."""
    from querypilot.cache.metadata_cache import get_metadata

    return get_metadata(
        tables_dir=tables_dir,
        join_graph_path=join_graph_path,
        value_config_path=value_config_path,
        metrics_path=metrics_path,
        load_db_codes=load_db_codes,
        db_con=db_con,
        use_cache=use_cache,
    )
