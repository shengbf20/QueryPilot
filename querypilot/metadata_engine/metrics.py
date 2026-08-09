"""Load metric-tree YAML for prompt口径 injection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from querypilot.config import get_settings


@dataclass(frozen=True)
class MetricDef:
    id: str
    name: str
    kind: str
    tables: tuple[str, ...]
    formula: str
    description: str

    def format_for_prompt(self) -> str:
        return f"指标[{self.name}]: {self.formula} — {self.description}"


def load_metrics(path: Path | None = None) -> list[MetricDef]:
    """Load ``metadata/metrics/metrics.yaml`` (empty list if missing)."""
    path = path or (get_settings().metadata_dir / "metrics" / "metrics.yaml")
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    metrics: list[MetricDef] = []
    for item in raw.get("metrics") or []:
        tables = tuple(str(t) for t in (item.get("tables") or []))
        metrics.append(
            MetricDef(
                id=str(item["id"]),
                name=str(item["name"]),
                kind=str(item.get("kind", "derived")),
                tables=tables,
                formula=str(item.get("formula", "")).strip(),
                description=str(item.get("description", "")).strip(),
            )
        )
    return metrics


def metrics_for_tables(metrics: list[MetricDef], tables: list[str]) -> list[MetricDef]:
    """Return metrics whose declared tables intersect the pruned set."""
    selected = set(tables)
    return [m for m in metrics if not m.tables or selected.intersection(m.tables)]
