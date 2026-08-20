"""End-to-end NL2SQL pipeline: prune → generate → L1 → L2 → execute → probe."""

from __future__ import annotations

import time

import duckdb
from openai import OpenAI

from querypilot.agent.models import PipelineResult, StageTiming
from querypilot.agent.pnl_fix import fix_period_pnl_sql
from querypilot.agent.sql_generator import generate_sql
from querypilot.agent.topn_fix import fix_org_topn_sql
from querypilot.cache.metadata_cache import get_metadata, get_pruned_schema
from querypilot.cache.query_cache import (
    CachedQuery,
    get_cached_query,
    make_query_key,
    put_cached_query,
)
from querypilot.config import get_settings
from querypilot.db import execute
from querypilot.metadata_engine.bundle import MetadataBundle
from querypilot.safety.l1_ast import guard_sql
from querypilot.safety.l2_explain import validate_with_l2
from querypilot.safety.result_probe import probe_result


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _resolve_cache_rows(cache_rows: bool | None) -> bool:
    if cache_rows is not None:
        return bool(cache_rows)
    return bool(get_settings().cache_rows)


def ask(
    question: str,
    *,
    metadata: MetadataBundle | None = None,
    client: OpenAI | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
    max_rows: int = 1000,
    max_few_shots: int = 3,
    include_values: bool = True,
    allow_exact_few_shot: bool = True,
    use_cache: bool | None = None,
    cache_rows: bool | None = None,
    use_parallel: bool = False,
) -> PipelineResult:
    """为一个自然语言问题运行完整的QueryPilot Pipeline"""
    t_all = time.perf_counter()
    timing = StageTiming() # 建计时器
    want_rows = _resolve_cache_rows(cache_rows) # 解析是否缓存行

    q = question.strip() # 输入问题去掉首尾空白
    if not q: # 如果问题为空，则直接返回错误结果
        timing.total_ms = _elapsed_ms(t_all)
        return PipelineResult(
            ok=False,
            question=question,
            degraded=True,
            message="问题不能为空",
            stage="prune",
            timing=timing,
        )

    from querypilot.safety.intent_guard import check_malicious_intent, format_safety_message

    intent_reason = check_malicious_intent(q)
    if intent_reason:
        timing.total_ms = _elapsed_ms(t_all)
        return PipelineResult(
            ok=False,
            question=q,
            degraded=True,
            message=format_safety_message(intent_reason),
            stage="safety",
            timing=timing,
            extras={"safety_reason": intent_reason},
        )

    # 可选的并行度量模式，尝试将多指标问题拆成子查询并行执行
    if use_parallel:
        from querypilot.agent.parallel import try_parallel_pipeline # 导入并行管道

        md_par = metadata or get_metadata(load_db_codes=include_values, use_cache=use_cache)
        t_par = time.perf_counter()
        par = try_parallel_pipeline(q, metadata=md_par, max_rows=max_rows) # 尝试并行执行
        if par is not None and par.ok:
            timing.execute_ms = _elapsed_ms(t_par)
            timing.total_ms = _elapsed_ms(t_all)
            return PipelineResult(
                ok=True,
                question=q,
                sql=";\n".join(par.sqls),
                rationale="parallel metric queries merged on pty_id",
                tables=list(par.tables),
                columns=list(par.columns),
                rows=list(par.rows),
                row_count=len(par.rows),
                degraded=False,
                message="ok",
                stage="done",
                timing=timing,
                extras={
                    "parallel": True,
                    "fallback": False,
                    "parallel_ms": par.parallel_ms,
                },
            )
        # 如果并行执行成功，则返回结果；失败则fallback到正常管道

    cache_key = make_query_key( # 生成查询缓存键
        q,
        max_rows=max_rows,
        max_few_shots=max_few_shots,
        include_values=include_values,
        allow_exact_few_shot=allow_exact_few_shot,
        cache_rows=want_rows,
    )
    cached = get_cached_query(cache_key, use_cache=use_cache)
    if cached is not None and cached.sql:
        # 如果缓存命中，则从缓存中获取结果
        return _finish_from_cache(
            q,
            cached,
            timing=timing,
            t_all=t_all,
            con=con,
            max_rows=max_rows,
            want_rows=want_rows,
        )
        
    # 如果缓存未命中，则继续执行
    md = metadata or get_metadata(load_db_codes=include_values, use_cache=use_cache) # 获取元数据

    # 1) Schema prune 修剪掉不相关的表和列
    t0 = time.perf_counter()
    pruned = get_pruned_schema(q, md, use_cache=use_cache)
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
            allow_exact_few_shot=allow_exact_few_shot,
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

    sql = fix_org_topn_sql(fix_period_pnl_sql(gen.sql))

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
    sql = fix_org_topn_sql(fix_period_pnl_sql(l2.sql))

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
    result = PipelineResult(
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

    # Only cache successful, non-degraded fence-approved paths
    entry = CachedQuery(
        sql=sql,
        tables=list(allowed),
        rationale=gen.rationale,
        uses_cte=bool(gen.uses_cte),
        columns=list(data.columns) if want_rows else [],
        rows=list(data.rows) if want_rows else [],
        row_count=data.row_count if want_rows else 0,
        has_rows=want_rows,
    )
    put_cached_query(cache_key, entry, use_cache=use_cache)
    return result


def _finish_from_cache(
    question: str,
    cached: CachedQuery,
    *,
    timing: StageTiming,
    t_all: float,
    con: duckdb.DuckDBPyConnection | None,
    max_rows: int,
    want_rows: bool,
) -> PipelineResult:
    """Replay fence-approved SQL: optional cached rows, else re-execute + probe."""
    timing.cache_hit = True
    sql = cached.sql
    tables = list(cached.tables)

    if want_rows and cached.has_rows:
        timing.execute_ms = 0.0
        timing.probe_ms = 0.0
        timing.total_ms = _elapsed_ms(t_all)
        return PipelineResult(
            ok=True,
            question=question,
            sql=sql,
            rationale=cached.rationale,
            tables=tables,
            columns=list(cached.columns),
            rows=list(cached.rows),
            row_count=cached.row_count,
            degraded=False,
            message="ok (cache)",
            stage="done",
            timing=timing,
            extras={"uses_cte": cached.uses_cte, "cache": "rows"},
        )

    t0 = time.perf_counter()
    try:
        data = execute(sql, con=con, max_rows=max_rows)
    except Exception as exc:  # noqa: BLE001
        timing.execute_ms = _elapsed_ms(t0)
        timing.total_ms = _elapsed_ms(t_all)
        return PipelineResult(
            ok=False,
            question=question,
            sql=sql,
            rationale=cached.rationale,
            tables=tables,
            degraded=True,
            message=f"SQL 执行失败: {exc}",
            stage="execute",
            timing=timing,
            extras={"cache": "sql"},
        )
    timing.execute_ms = _elapsed_ms(t0)

    t0 = time.perf_counter()
    probe = probe_result(question, data, sql=sql)
    timing.probe_ms = _elapsed_ms(t0)
    message = "ok"
    if probe.triggered:
        message = probe.message
        if probe.suggestions:
            message = message + " " + " / ".join(probe.suggestions)

    timing.total_ms = _elapsed_ms(t_all)
    return PipelineResult(
        ok=True,
        question=question,
        sql=sql,
        rationale=cached.rationale,
        tables=tables,
        columns=list(data.columns),
        rows=list(data.rows),
        row_count=data.row_count,
        degraded=False,
        message=message,
        probe_message=probe.message if probe.triggered else "",
        probe_suggestions=list(probe.suggestions),
        stage="done",
        timing=timing,
        extras={
            "uses_cte": cached.uses_cte,
            "probe_code": probe.code,
            "cache": "sql",
        },
    )
