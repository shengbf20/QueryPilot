"""Single-shot LLM SQL generator."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from querypilot.agent.models import FewShotExample, PromptBundle, SqlGenerationResult
from querypilot.agent.prompt import build_prompt, load_few_shots
from querypilot.llm.chat import generate_json
from querypilot.metadata_engine.bundle import MetadataBundle, load_metadata
from querypilot.metadata_engine.schema_pruner import PrunedSchema, SchemaPruner


class SqlGenerationError(ValueError):
    """Raised when the model response cannot yield a usable SQL string."""


def parse_sql_payload(data: dict[str, Any]) -> tuple[str, str, bool]:
    """Extract (sql, rationale, uses_cte) from a model JSON object."""
    if "sql" not in data:
        raise SqlGenerationError(f"Missing 'sql' field in model response: {sorted(data.keys())}")
    sql = str(data["sql"]).strip()
    if not sql:
        raise SqlGenerationError("Empty 'sql' field in model response")

    # Tolerate accidental markdown fences around SQL.
    if sql.startswith("```"):
        lines = sql.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        sql = "\n".join(lines).strip()

    rationale = str(data.get("rationale", "")).strip()
    uses_cte = bool(data.get("uses_cte", False))
    if not uses_cte and sql.lstrip().upper().startswith("WITH"):
        uses_cte = True
    return sql, rationale, uses_cte


def generate_sql(
    question: str,
    *,
    metadata: MetadataBundle | None = None,
    pruned: PrunedSchema | None = None,
    few_shots: list[FewShotExample] | None = None,
    include_values: bool = True,
    max_few_shots: int = 3,
    client: OpenAI | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = 1200,
) -> SqlGenerationResult:
    """Prune schema (unless provided), build prompt, call LLM, return structured SQL."""
    md = metadata or load_metadata(load_db_codes=include_values)
    pruned_schema = pruned or SchemaPruner(md).prune(question)
    prompt = build_prompt(
        question,
        pruned_schema,
        md,
        few_shots=few_shots if few_shots is not None else load_few_shots(),
        include_values=include_values,
        max_few_shots=max_few_shots,
    )
    raw = generate_json(
        prompt.user,
        system=prompt.system,
        temperature=temperature,
        max_tokens=max_tokens,
        client=client,
    )
    sql, rationale, uses_cte = parse_sql_payload(raw)
    return SqlGenerationResult(
        sql=sql,
        rationale=rationale,
        uses_cte=uses_cte,
        raw=raw,
        prompt=prompt,
        pruned=pruned_schema,
    )


def generate_sql_from_prompt(
    prompt: PromptBundle,
    *,
    client: OpenAI | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = 1200,
) -> SqlGenerationResult:
    """Call LLM with an already-built PromptBundle (useful for tests / correction loops)."""
    raw = generate_json(
        prompt.user,
        system=prompt.system,
        temperature=temperature,
        max_tokens=max_tokens,
        client=client,
    )
    sql, rationale, uses_cte = parse_sql_payload(raw)
    return SqlGenerationResult(
        sql=sql,
        rationale=rationale,
        uses_cte=uses_cte,
        raw=raw,
        prompt=prompt,
    )
