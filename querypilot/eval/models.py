"""Evaluation data models (gold cases + Execution Match results)."""

from __future__ import annotations

from dataclasses import dataclass, field
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
