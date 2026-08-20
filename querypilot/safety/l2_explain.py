"""L2 EXPLAIN fence + single 1-Shot LLM correction (no retry loops)."""

from __future__ import annotations

import duckdb
from openai import OpenAI

from querypilot.agent.prompt import SYSTEM_PROMPT
from querypilot.agent.sql_generator import SqlGenerationError, parse_sql_payload
from querypilot.db import ExplainResult, explain
from querypilot.llm.chat import generate_json
from querypilot.metadata_engine.bundle import MetadataBundle
from querypilot.safety.l1_ast import guard_sql
from querypilot.safety.models import L1GuardResult, L2GuardResult

_MAX_CORRECTION_ATTEMPTS = 1

CORRECTION_SYSTEM = (
    SYSTEM_PROMPT
    + "\n10. 下面提供的是一次失败 SQL 与 DuckDB 报错；请只修正错误，保持用户意图不变，仍输出 JSON。"
)


def run_explain(
    sql: str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
) -> ExplainResult:
    """Thin wrapper over DuckDB EXPLAIN for the L2 fence."""
    return explain(sql, con=con)


def build_correction_prompt(
    *,
    question: str,
    failed_sql: str,
    error: str,
    schema_context: str = "",
) -> str:
    """User prompt for a single directed SQL correction."""
    parts = [
        "请根据数据库报错修正 SQL，只尝试一次。",
        "",
        f"用户问题:\n{question.strip() or '(未提供)'}",
        "",
        f"失败 SQL:\n{failed_sql.strip()}",
        "",
        f"DuckDB 报错:\n{error.strip()}",
    ]
    if schema_context.strip():
        parts.extend(["", "相关 Schema / 约定:", schema_context.strip()])
    parts.extend(
        [
            "",
            "请输出 JSON，例如:",
            '{"sql":"SELECT ...","rationale":"修正说明","uses_cte":false}',
        ]
    )
    return "\n".join(parts)


def correct_sql_once(
    *,
    question: str,
    failed_sql: str,
    error: str,
    schema_context: str = "",
    client: OpenAI | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = 1200,
) -> tuple[str, str, dict]:
    """Call LLM once to fix SQL. Returns (sql, rationale, raw_json)."""
    user = build_correction_prompt(
        question=question,
        failed_sql=failed_sql,
        error=error,
        schema_context=schema_context,
    )
    raw = generate_json(
        user,
        system=CORRECTION_SYSTEM,
        temperature=temperature,
        max_tokens=max_tokens,
        client=client,
    )
    sql, rationale, _uses_cte, clarify = parse_sql_payload(raw)
    if not sql:
        raise SqlGenerationError(clarify or "correction returned no SQL")
    return sql, rationale, raw


def validate_with_l2(
    sql: str,
    *,
    question: str = "",
    schema_context: str = "",
    metadata: MetadataBundle | None = None,
    allowed_tables: set[str] | list[str] | None = None,
    client: OpenAI | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
    enable_correction: bool = True,
    run_l1_on_correction: bool = True,
) -> L2GuardResult:
    """EXPLAIN ``sql``; on failure, attempt exactly one LLM correction then re-check.

    Success criteria:
    - EXPLAIN passes on original or corrected SQL → ``ok=True``
    - After one failed correction / L1 reject / second EXPLAIN fail → ``ok=False``, ``degraded=True``
    """
    original = sql
    first = run_explain(original, con=con)
    if first.ok:
        return L2GuardResult(
            ok=True,
            sql=original,
            original_sql=original,
            attempts=1,
            message="EXPLAIN passed",
        )

    first_error = first.error or "Unknown EXPLAIN error"
    if not enable_correction:
        return L2GuardResult(
            ok=False,
            sql=original,
            original_sql=original,
            explain_error=first_error,
            degraded=True,
            attempts=1,
            message=f"EXPLAIN failed (correction disabled): {first_error}",
        )

    try:
        fixed_sql, rationale, _raw = correct_sql_once(
            question=question,
            failed_sql=original,
            error=first_error,
            schema_context=schema_context,
            client=client,
        )
    except Exception as exc:  # noqa: BLE001 — degrade on any correction failure
        return L2GuardResult(
            ok=False,
            sql=original,
            original_sql=original,
            explain_error=first_error,
            degraded=True,
            attempts=1 + _MAX_CORRECTION_ATTEMPTS,
            message=f"1-Shot correction failed: {exc}",
        )

    l1_result: L1GuardResult | None = None
    candidate = fixed_sql
    if run_l1_on_correction:
        l1_result = guard_sql(
            fixed_sql,
            metadata=metadata,
            allowed_tables=allowed_tables,
        )
        if not l1_result.ok:
            detail = "; ".join(v.message for v in l1_result.violations) or "L1 rejected"
            return L2GuardResult(
                ok=False,
                sql=original,
                original_sql=original,
                explain_error=first_error,
                corrected=True,
                correction_rationale=rationale,
                degraded=True,
                attempts=1 + _MAX_CORRECTION_ATTEMPTS,
                l1_after_correction=l1_result,
                message=f"Corrected SQL failed L1: {detail}",
            )
        candidate = l1_result.sql

    second = run_explain(candidate, con=con)
    if second.ok:
        return L2GuardResult(
            ok=True,
            sql=candidate,
            original_sql=original,
            explain_error=first_error,
            corrected=True,
            correction_rationale=rationale,
            attempts=1 + _MAX_CORRECTION_ATTEMPTS,
            l1_after_correction=l1_result,
            message="EXPLAIN passed after 1-Shot correction",
        )

    second_error = second.error or "Unknown EXPLAIN error"
    return L2GuardResult(
        ok=False,
        sql=candidate,
        original_sql=original,
        explain_error=second_error,
        corrected=True,
        correction_rationale=rationale,
        degraded=True,
        attempts=1 + _MAX_CORRECTION_ATTEMPTS,
        l1_after_correction=l1_result,
        message=(
            "无法在一次纠错内得到可执行 SQL。"
            f" 首次错误: {first_error}; 纠错后错误: {second_error}"
        ),
    )
