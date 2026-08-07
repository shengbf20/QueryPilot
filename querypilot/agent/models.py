"""Agent data models for NL → SQL generation."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    raw: dict[str, Any] = field(default_factory=dict)
    prompt: PromptBundle | None = None
    pruned: PrunedSchema | None = None
