"""HTTP API layer (FastAPI). Phase 5 API-1 serialize + API-2 routes."""

from __future__ import annotations

from querypilot.api.app import create_app
from querypilot.api.serialize import (
    json_safe,
    pipeline_result_to_api_dict,
    prune_summary_from,
)

__all__ = [
    "create_app",
    "json_safe",
    "pipeline_result_to_api_dict",
    "prune_summary_from",
]
