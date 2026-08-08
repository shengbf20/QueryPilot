"""NL2SQL agent pipeline: intent → SQL → execute."""

from querypilot.agent.models import FewShotExample, PipelineResult, PromptBundle, SqlGenerationResult
from querypilot.agent.pipeline import ask
from querypilot.agent.prompt import SYSTEM_PROMPT, build_prompt, load_few_shots
from querypilot.agent.sql_generator import (
    SqlGenerationError,
    generate_sql,
    generate_sql_from_prompt,
    parse_sql_payload,
)

__all__ = [
    "SYSTEM_PROMPT",
    "FewShotExample",
    "PipelineResult",
    "PromptBundle",
    "SqlGenerationError",
    "SqlGenerationResult",
    "ask",
    "build_prompt",
    "generate_sql",
    "generate_sql_from_prompt",
    "load_few_shots",
    "parse_sql_payload",
]
