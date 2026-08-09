"""Serialize PipelineResult into a JSON-safe API dict (phase 5 API-1)."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from querypilot.metadata_engine.schema_pruner import PrunedSchema

# Frozen response shape (API-1 contract):
# ok, question, sql, rationale, tables, columns, rows, row_count,
# degraded, message, probe_message, probe_suggestions, corrected, stage,
# timing: { prune_ms, generate_ms, l1_ms, l2_ms, execute_ms, probe_ms, total_ms, cache_hit },
# prune_summary: { tables, seed_tables, bridge_tables, metrics },
# extras


def json_safe(value: Any) -> Any:
    """Convert common Python / DB values into JSON-serializable forms."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    # numpy scalars etc.
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return json_safe(item())
        except Exception:
            pass
    return str(value)


def prune_summary_from(pruned: PrunedSchema | None) -> dict[str, Any]:
    """Short prune summary for UI; never includes full prompt schema text."""
    if pruned is None:
        return {
            "tables": [],
            "seed_tables": [],
            "bridge_tables": [],
            "metrics": [],
        }
    seeds = list(pruned.seed_tables)
    tables = list(pruned.tables)
    seed_set = set(seeds)
    bridge = [t for t in tables if t not in seed_set]
    return {
        "tables": tables,
        "seed_tables": seeds,
        "bridge_tables": bridge,
        "metrics": [],
    }


def pipeline_result_to_api_dict(
    result: Any,
    *,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Build the frozen API-1 response dict from a PipelineResult-like object."""
    rows = list(result.rows)
    if max_rows is not None and max_rows >= 0:
        rows = rows[:max_rows]
    return {
        "ok": bool(result.ok),
        "question": result.question,
        "sql": result.sql or "",
        "rationale": result.rationale or "",
        "tables": list(result.tables),
        "columns": list(result.columns),
        "rows": json_safe(rows),
        "row_count": int(result.row_count),
        "degraded": bool(result.degraded),
        "message": result.message or "",
        "probe_message": result.probe_message or "",
        "probe_suggestions": list(result.probe_suggestions),
        "corrected": bool(result.corrected),
        "stage": result.stage or "",
        "timing": result.timing.to_dict(),
        "prune_summary": prune_summary_from(getattr(result, "pruned", None)),
        "extras": json_safe(dict(result.extras or {})),
    }
