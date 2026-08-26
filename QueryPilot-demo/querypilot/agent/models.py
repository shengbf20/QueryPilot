"""Agent data models for NL → SQL generation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from querypilot.metadata_engine.schema_pruner import PrunedSchema


@dataclass(frozen=True)
class FewShotExample:
    question: str
    sql: str
    rationale: str = ""


@dataclass
class PromptBundle:
    """Assembled prompts ready for the LLM."""

    system: str
    user: str
    question: str
    tables: list[str] = field(default_factory=list)
    few_shot_count: int = 0

    def as_messages(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.user},
        ]


@dataclass
class SqlGenerationResult:
    """Structured SQL generation outcome."""

    sql: str
    rationale: str = ""
    uses_cte: bool = False
    clarify: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    prompt: PromptBundle | None = None
    pruned: PrunedSchema | None = None


@dataclass
class StageTiming:
    """Per-stage latency for ask() (milliseconds)."""

    prune_ms: float = 0.0
    generate_ms: float = 0.0
    l1_ms: float = 0.0
    l2_ms: float = 0.0
    execute_ms: float = 0.0
    probe_ms: float = 0.0
    total_ms: float = 0.0
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineResult:
    """End-to-end ask() outcome: SQL + rows or a degraded explanation."""

    ok: bool
    question: str
    sql: str = ""
    rationale: str = ""
    tables: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    row_count: int = 0
    degraded: bool = False
    message: str = ""
    probe_message: str = ""
    probe_suggestions: list[str] = field(default_factory=list)
    corrected: bool = False
    stage: str = ""  # prune|generate|l1|l2|execute|probe|done
    pruned: PrunedSchema | None = None
    timing: StageTiming = field(default_factory=StageTiming)
    extras: dict[str, Any] = field(default_factory=dict)

    def to_api_dict(self, *, max_rows: int | None = None) -> dict[str, Any]:
        """JSON-safe dict for HTTP API / Chat UI (phase 5 API-1 contract)."""
        from querypilot.api.serialize import pipeline_result_to_api_dict

        return pipeline_result_to_api_dict(self, max_rows=max_rows)