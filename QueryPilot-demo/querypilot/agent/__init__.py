"""NL2SQL agent pipeline: intent → SQL → execute."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from querypilot.agent.models import (
    FewShotExample,
    PipelineResult,
    PromptBundle,
    SqlGenerationResult,
    StageTiming,
)
from querypilot.agent.prompt import (
    SYSTEM_PROMPT,
    build_prompt,
    compose_prune_text,
    find_exact_few_shot,
    load_few_shots,
    normalize_history,
    select_few_shots,
)
from querypilot.agent.sql_generator import (
    SqlGenerationError,
    generate_sql,
    generate_sql_from_prompt,
    parse_sql_payload,
)

if TYPE_CHECKING:
    from querypilot.agent.pipeline import ask as ask

__all__ = [
    "SYSTEM_PROMPT",
    "FewShotExample",
    "PipelineResult",
    "PromptBundle",
    "SqlGenerationError",
    "SqlGenerationResult",
    "StageTiming",
    "ask",
    "build_prompt",
    "compose_prune_text",
    "generate_sql",
    "normalize_history",
    "generate_sql_from_prompt",
    "find_exact_few_shot",
    "load_few_shots",
    "select_few_shots",
    "parse_sql_payload",
]


def __getattr__(name: str) -> Any:
    # Lazy import avoids circular import: safety.l2 → agent.prompt → agent.__init__ → pipeline → safety.l2
    if name == "ask":
        from querypilot.agent.pipeline import ask as _ask

        return _ask
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
