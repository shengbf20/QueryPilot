"""Evaluation data models (gold cases + Execution Match + batch report)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvalCase:
    """One gold Q&A item used for Execution Match."""

    id: str
    question: str
    gold_sql: str
    difficulty: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MatchResult:
    """Outcome of comparing predicted vs gold execution result sets."""

    matched: bool
    score: float
    reason: str = ""
    pred_rows: int = 0
    gold_rows: int = 0
    aligned_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class TimingInfo:
    """Per-case latency breakdown (milliseconds)."""

    total_ms: float = 0.0
    ask_ms: float = 0.0
    gold_execute_ms: float = 0.0
    match_ms: float = 0.0


@dataclass
class CaseEvalResult:
    """Full evaluation outcome for a single gold case."""

    case_id: str
    question: str
    matched: bool
    score: float
    gold_sql: str = ""
    pred_sql: str = ""
    ask_ok: bool = False
    gold_ok: bool = False
    error: str = ""
    match_reason: str = ""
    difficulty: str | None = None
    timing: TimingInfo = field(default_factory=TimingInfo)
    stage: str = ""  # ask|gold_execute|match|done
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalReport:
    """Aggregated batch evaluation report (EX% + latency percentiles)."""

    total: int
    matched_count: int
    accuracy: float
    results: list[CaseEvalResult] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)
    by_difficulty: dict[str, float] = field(default_factory=dict)
    p50_ms: float | None = None
    p95_ms: float | None = None
    mean_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Diagnosis:
    """Eval-Agent attribution for one case (EX fail or agent/gold failure)."""

    case_id: str
    matched: bool
    error_types: list[str] = field(default_factory=list)
    summary: str = ""
    evidence: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    confidence: float = 0.0
    markdown: str = ""
    source: str = "heuristic"  # heuristic | llm | heuristic+llm
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
