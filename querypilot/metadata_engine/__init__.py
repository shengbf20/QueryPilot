from querypilot.metadata_engine.bundle import MetadataBundle, load_metadata
from querypilot.metadata_engine.join_graph import (
    JoinGraphEngine,
    JoinPlan,
    ResolvedPath,
    create_join_graph_engine,
    format_join_clause,
)
from querypilot.metadata_engine.join_graph_loader import JoinGraph, JoinEdge, JoinPath, load_join_graph
from querypilot.metadata_engine.join_graph_validator import validate_join_graph as validate_join_graph_only
from querypilot.metadata_engine.loader import (
    DB_COLUMNS,
    EXPECTED_TABLES,
    load_all_tables,
    load_table_meta,
)
from querypilot.metadata_engine.metrics import MetricDef, load_metrics, metrics_for_tables
from querypilot.metadata_engine.metadata_validator import (
    MetadataValidationResult,
    validate_metadata_all,
)
from querypilot.metadata_engine.models import ColumnMeta, TableMeta
from querypilot.metadata_engine.schema_pruner import (
    ColumnHit,
    PrunedSchema,
    SchemaPruner,
    TableHit,
    prune_schema,
)
from querypilot.metadata_engine.validator import ValidationResult, validate_all
from querypilot.metadata_engine.value_descriptors import (
    ValueDescriptorRegistry,
    load_value_descriptor_config,
    load_value_descriptors,
)
from querypilot.metadata_engine.value_validator import (
    ValueDescriptorValidationResult,
    validate_value_descriptors,
    validate_value_descriptor_config,
)

__all__ = [
    "ColumnMeta",
    "TableMeta",
    "ColumnHit",
    "TableHit",
    "PrunedSchema",
    "SchemaPruner",
    "MetadataBundle",
    "MetadataValidationResult",
    "ValidationResult",
    "ValueDescriptorRegistry",
    "ValueDescriptorValidationResult",
    "DB_COLUMNS",
    "EXPECTED_TABLES",
    "load_metadata",
    "load_all_tables",
    "load_table_meta",
    "load_value_descriptor_config",
    "load_value_descriptors",
    "load_join_graph",
    "MetricDef",
    "load_metrics",
    "metrics_for_tables",
    "JoinGraphEngine",
    "JoinPlan",
    "ResolvedPath",
    "create_join_graph_engine",
    "format_join_clause",
    "prune_schema",
    "validate_all",
    "validate_metadata_all",
    "validate_join_graph_only",
    "validate_value_descriptors",
    "validate_value_descriptor_config",
]

# Backward-compatible alias
validate_join_graph = validate_join_graph_only
