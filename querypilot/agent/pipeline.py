"""End-to-end NL2SQL pipeline: prune → generate → L1 → L2 → execute → probe."""

from __future__ import annotations

import time

import duckdb
from openai import OpenAI

from querypilot.agent.models import PipelineResult, StageTiming
from querypilot.agent.sql_generator import generate_sql
from querypilot.db import execute
from querypilot.metadata_engine.bundle import MetadataBundle, load_metadata
from querypilot.metadata_engine.schema_pruner import SchemaPruner
from querypilot.safety.l1_ast import guard_sql
from querypilot.safety.l2_explain import validate_with_l2
from querypilot.safety.result_probe import probe_result


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


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
    t_all = time.perf_counter()
    timing = StageTiming()

    q = question.strip()
    if not q:
        timing.total_ms = _elapsed_ms(t_all)
        return PipelineResult(
            ok=False,
            question=question,
            degraded=True,
            message="问题不能为空",
            stage="prune",
            timing=timing,
        )

    md = metadata or load_metadata(load_db_codes=include_values)

    # 1) Schema prune
    t0 = time.perf_counter()
    pruned = SchemaPruner(md).prune(q)
    timing.prune_ms = _elapsed_ms(t0)
    schema_context = pruned.format_for_prompt(md, include_values=include_values)
    allowed = list(pruned.tables)

    # 2) Single-shot SQL generation
    t0 = time.perf_counter()
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
        timing.generate_ms = _elapsed_ms(t0)
        timing.total_ms = _elapsed_ms(t_all)
        return PipelineResult(
            ok=False,
            question=q,
            tables=allowed,
            degraded=True,
            message=f"SQL 生成失败: {exc}",
            stage="generate",
            pruned=pruned,
            timing=timing,
        )
    timing.generate_ms = _elapsed_ms(t0)

    sql = gen.sql

    # 3) L1 AST fence
    t0 = time.perf_counter()
    l1 = guard_sql(sql, metadata=md, allowed_tables=allowed)
    timing.l1_ms = _elapsed_ms(t0)
    if not l1.ok:
        detail = "; ".join(v.message for v in l1.violations) or "L1 rejected"
        timing.total_ms = _elapsed_ms(t_all)
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
            timing=timing,
            extras={"l1_violations": [v.message for v in l1.violations]},
        )
    sql = l1.sql

    # 4) L2 EXPLAIN + optional 1-Shot correction
    t0 = time.perf_counter()
    l2 = validate_with_l2(
        sql,
        question=q,
        schema_context=schema_context,
        metadata=md,
        allowed_tables=allowed,
        client=client,
        con=con,
    )
    timing.l2_ms = _elapsed_ms(t0)
    if not l2.ok:
        timing.total_ms = _elapsed_ms(t_all)
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
            timing=timing,
            extras={"explain_error": l2.explain_error, "correction_rationale": l2.correction_rationale},
        )
    sql = l2.sql

    # 5) Execute
    t0 = time.perf_counter()
    try:
        data = execute(sql, con=con, max_rows=max_rows)
    except Exception as exc:  # noqa: BLE001
        timing.execute_ms = _elapsed_ms(t0)
        timing.total_ms = _elapsed_ms(t_all)
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
            timing=timing,
        )
    timing.execute_ms = _elapsed_ms(t0)

    # 6) Result probe
    t0 = time.perf_counter()
    probe = probe_result(q, data, sql=sql)
    timing.probe_ms = _elapsed_ms(t0)
    message = "ok"
    if probe.triggered:
        message = probe.message
        if probe.suggestions:
            message = message + " " + " / ".join(probe.suggestions)

    timing.total_ms = _elapsed_ms(t_all)
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
        timing=timing,
        extras={
            "uses_cte": gen.uses_cte,
            "l1_fixes": [f"{f.original}->{f.fixed}" for f in l1.fixes],
            "probe_code": probe.code,
        },
    )
