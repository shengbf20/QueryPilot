"""End-to-end NL2SQL pipeline: prune → generate → L1 → L2 → execute → probe."""

from __future__ import annotations

import duckdb
from openai import OpenAI

from querypilot.agent.models import PipelineResult
from querypilot.agent.sql_generator import generate_sql
from querypilot.db import execute
from querypilot.metadata_engine.bundle import MetadataBundle, load_metadata
from querypilot.metadata_engine.schema_pruner import SchemaPruner
from querypilot.safety.l1_ast import guard_sql
from querypilot.safety.l2_explain import validate_with_l2
from querypilot.safety.result_probe import probe_result


def ask(
    question: str,
    *,
    metadata: MetadataBundle | None = None,
    client: OpenAI | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
    max_rows: int = 1000,
    max_few_shots: int = 3,
    include_values: bool = True,
) -> PipelineResult:
    """Run the full QueryPilot retrieval pipeline for one natural-language question."""
    q = question.strip()
    if not q:
        return PipelineResult(
            ok=False,
            question=question,
            degraded=True,
            message="问题不能为空",
            stage="prune",
        )

    md = metadata or load_metadata(load_db_codes=include_values)

    # 1) Schema prune
    pruned = SchemaPruner(md).prune(q)
    schema_context = pruned.format_for_prompt(md, include_values=include_values)
    allowed = list(pruned.tables)

    # 2) Single-shot SQL generation
    try:
        gen = generate_sql(
            q,
            metadata=md,
            pruned=pruned,
            include_values=include_values,
            max_few_shots=max_few_shots,
            client=client,
        )
    except Exception as exc:  # noqa: BLE001
        return PipelineResult(
            ok=False,
            question=q,
            tables=allowed,
            degraded=True,
            message=f"SQL 生成失败: {exc}",
            stage="generate",
            pruned=pruned,
        )

    sql = gen.sql

    # 3) L1 AST fence
    l1 = guard_sql(sql, metadata=md, allowed_tables=allowed)
    if not l1.ok:
        detail = "; ".join(v.message for v in l1.violations) or "L1 rejected"
        return PipelineResult(
            ok=False,
            question=q,
            sql=sql,
            rationale=gen.rationale,
            tables=allowed,
            degraded=True,
            message=f"L1 安全围栏拦截: {detail}",
            stage="l1",
            pruned=pruned,
            extras={"l1_violations": [v.message for v in l1.violations]},
        )
    sql = l1.sql

    # 4) L2 EXPLAIN + optional 1-Shot correction
    l2 = validate_with_l2(
        sql,
        question=q,
        schema_context=schema_context,
        metadata=md,
        allowed_tables=allowed,
        client=client,
        con=con,
    )
    if not l2.ok:
        return PipelineResult(
            ok=False,
            question=q,
            sql=l2.sql or sql,
            rationale=gen.rationale,
            tables=allowed,
            degraded=True,
            corrected=l2.corrected,
            message=l2.message or "L2 校验失败",
            stage="l2",
            pruned=pruned,
            extras={"explain_error": l2.explain_error, "correction_rationale": l2.correction_rationale},
        )
    sql = l2.sql

    # 5) Execute
    try:
        data = execute(sql, con=con, max_rows=max_rows)
    except Exception as exc:  # noqa: BLE001
        return PipelineResult(
            ok=False,
            question=q,
            sql=sql,
            rationale=gen.rationale,
            tables=allowed,
            degraded=True,
            corrected=l2.corrected,
            message=f"SQL 执行失败: {exc}",
            stage="execute",
            pruned=pruned,
        )

    # 6) Result probe
    probe = probe_result(q, data, sql=sql)
    message = "ok"
    if probe.triggered:
        message = probe.message
        if probe.suggestions:
            message = message + " " + " / ".join(probe.suggestions)

    return PipelineResult(
        ok=True,
        question=q,
        sql=sql,
        rationale=gen.rationale,
        tables=allowed,
        columns=list(data.columns),
        rows=list(data.rows),
        row_count=data.row_count,
        degraded=False,
        corrected=l2.corrected,
        message=message,
        probe_message=probe.message if probe.triggered else "",
        probe_suggestions=list(probe.suggestions),
        stage="done",
        pruned=pruned,
        extras={
            "uses_cte": gen.uses_cte,
            "l1_fixes": [f"{f.original}->{f.fixed}" for f in l1.fixes],
            "probe_code": probe.code,
        },
    )
