"""Minimal parallel helpers for phase-4 step 4 (mode B + support for mode C).

Mode B: rule-built per-domain metric SQLs → parallel execute → merge on pty_id.
Fails closed: callers should fall back to the normal ask() pipeline.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Sequence

from querypilot.db import execute, get_connection
from querypilot.metadata_engine.bundle import MetadataBundle
from querypilot.safety.l1_ast import guard_sql

# Customer-filter cues (客群)
_FILTER_CUES = ("客户", "年龄", "岁", "性别", "男", "女", "银卡", "金卡", "营业部")

# Metric domains: (keywords, label, builder name)
_DOMAIN_SPECS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("资产", "总资产", "日均资产"), "asset", "asset"),
    (("持仓", "市值", "持有"), "hold", "hold"),
    (("交易", "买入", "卖出", "成交"), "tran", "tran"),
)


@dataclass(frozen=True)
class MetricQuery:
    name: str
    sql: str
    tables: tuple[str, ...]


@dataclass
class ParallelPlan:
    question: str
    queries: list[MetricQuery]
    rationale: str = ""


@dataclass
class ParallelExecResult:
    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    sqls: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    message: str = ""
    parallel_ms: float = 0.0
    serial_ms: float = 0.0
    used_parallel: bool = True


def detect_multi_metric_question(question: str) -> list[str]:
    """Return matched metric domain labels if question looks multi-metric + 客群."""
    q = (question or "").strip()
    if not q:
        return []
    has_filter = any(c in q for c in _FILTER_CUES)
    if not has_filter:
        return []
    domains: list[str] = []
    for cues, label, _ in _DOMAIN_SPECS:
        if any(c in q for c in cues):
            domains.append(label)
    return domains if len(domains) >= 2 else []


def _sql_asset() -> MetricQuery:
    return MetricQuery(
        name="asset",
        sql=(
            "SELECT pty_id, "
            "SUM(COALESCE(nm_tot_aset, 0) + COALESCE(fc_pur_aset, 0)) AS total_aset "
            "FROM dws_cust_aset_d GROUP BY pty_id"
        ),
        tables=("dws_cust_aset_d",),
    )


def _sql_hold() -> MetricQuery:
    return MetricQuery(
        name="hold",
        sql=(
            "SELECT pty_id, SUM(COALESCE(mkt_val, 0)) AS mkt_val "
            "FROM dwd_cust_hold_d GROUP BY pty_id"
        ),
        tables=("dwd_cust_hold_d",),
    )


def _sql_tran() -> MetricQuery:
    return MetricQuery(
        name="tran",
        sql=(
            "SELECT pty_id, "
            "SUM(COALESCE(buy_amt, 0) + COALESCE(sell_amt, 0)) AS trade_amt "
            "FROM dwd_cust_tran_d GROUP BY pty_id"
        ),
        tables=("dwd_cust_tran_d",),
    )


_BUILDERS = {
    "asset": _sql_asset,
    "hold": _sql_hold,
    "tran": _sql_tran,
}


def build_parallel_plan(question: str) -> ParallelPlan | None:
    """Rule-only plan: ≥2 metric domains + 客群线索 → per-domain GROUP BY pty_id SQLs."""
    domains = detect_multi_metric_question(question)
    if len(domains) < 2:
        return None
    queries = [_BUILDERS[d]() for d in domains if d in _BUILDERS]
    if len(queries) < 2:
        return None
    return ParallelPlan(
        question=question.strip(),
        queries=queries,
        rationale=f"parallel metrics: {', '.join(domains)}",
    )


def merge_on_pty_id(
    left_columns: Sequence[str],
    left_rows: Sequence[tuple[Any, ...]],
    right_columns: Sequence[str],
    right_rows: Sequence[tuple[Any, ...]],
    *,
    how: str = "outer",
) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Outer/inner merge two result sets on ``pty_id`` (first matching column)."""
    if "pty_id" not in left_columns or "pty_id" not in right_columns:
        raise ValueError("both sides must contain pty_id")
    li = list(left_columns).index("pty_id")
    ri = list(right_columns).index("pty_id")
    left_extra = [c for i, c in enumerate(left_columns) if i != li]
    right_extra = [c for i, c in enumerate(right_columns) if i != ri and c not in left_extra]
    out_cols = ["pty_id", *left_extra, *right_extra]

    left_map: dict[Any, tuple[Any, ...]] = {}
    for row in left_rows:
        key = row[li]
        extras = tuple(row[i] for i in range(len(row)) if i != li)
        left_map[key] = extras

    right_map: dict[Any, tuple[Any, ...]] = {}
    for row in right_rows:
        key = row[ri]
        extras = tuple(
            row[i]
            for i, c in enumerate(right_columns)
            if i != ri and c not in left_extra
        )
        right_map[key] = extras

    if how == "inner":
        keys = sorted(set(left_map) & set(right_map), key=lambda x: (x is None, str(x)))
    else:
        keys = sorted(set(left_map) | set(right_map), key=lambda x: (x is None, str(x)))

    left_n = len(left_extra)
    right_n = len(right_extra)
    out_rows: list[tuple[Any, ...]] = []
    for key in keys:
        lvals = left_map.get(key, tuple(None for _ in range(left_n)))
        rvals = right_map.get(key, tuple(None for _ in range(right_n)))
        out_rows.append((key, *lvals, *rvals))
    return out_cols, out_rows


def _guard_and_execute(
    sql: str,
    *,
    metadata: MetadataBundle,
    allowed_tables: Sequence[str],
    max_rows: int,
) -> tuple[list[str], list[tuple[Any, ...]]]:
    l1 = guard_sql(sql, metadata=metadata, allowed_tables=list(allowed_tables))
    if not l1.ok:
        detail = "; ".join(v.message for v in l1.violations) or "L1 rejected"
        raise RuntimeError(f"L1: {detail}")
    con = get_connection(read_only=True)
    try:
        data = execute(l1.sql, con=con, max_rows=max_rows)
    finally:
        con.close()
    return list(data.columns), list(data.rows)


def execute_plan(
    plan: ParallelPlan,
    *,
    metadata: MetadataBundle,
    max_rows: int = 1000,
    parallel: bool = True,
) -> ParallelExecResult:
    """Execute plan queries serially or in parallel, then fold-merge on pty_id."""
    if len(plan.queries) < 2:
        return ParallelExecResult(ok=False, message="need ≥2 metric queries")

    allowed = sorted({t for q in plan.queries for t in q.tables})
    sqls = [q.sql for q in plan.queries]

    def _one(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        return _guard_and_execute(
            sql, metadata=metadata, allowed_tables=allowed, max_rows=max_rows
        )

    t0 = time.perf_counter()
    parts: list[tuple[list[str], list[tuple[Any, ...]]]] = []
    try:
        if parallel:
            with ThreadPoolExecutor(max_workers=len(plan.queries)) as pool:
                futs = {pool.submit(_one, q.sql): i for i, q in enumerate(plan.queries)}
                ordered: list[tuple[list[str], list[tuple[Any, ...]]] | None] = [
                    None
                ] * len(plan.queries)
                for fut in as_completed(futs):
                    idx = futs[fut]
                    ordered[idx] = fut.result()
                parts = [p for p in ordered if p is not None]
        else:
            parts = [_one(q.sql) for q in plan.queries]
    except Exception as exc:  # noqa: BLE001
        elapsed = (time.perf_counter() - t0) * 1000.0
        return ParallelExecResult(
            ok=False,
            sqls=sqls,
            tables=allowed,
            message=str(exc),
            parallel_ms=elapsed if parallel else 0.0,
            serial_ms=elapsed if not parallel else 0.0,
            used_parallel=parallel,
        )
    elapsed = (time.perf_counter() - t0) * 1000.0

    cols, rows = parts[0]
    for nxt_cols, nxt_rows in parts[1:]:
        cols, rows = merge_on_pty_id(cols, rows, nxt_cols, nxt_rows, how="outer")

    return ParallelExecResult(
        ok=True,
        columns=cols,
        rows=rows,
        sqls=sqls,
        tables=allowed,
        message="ok",
        parallel_ms=elapsed if parallel else 0.0,
        serial_ms=elapsed if not parallel else 0.0,
        used_parallel=parallel,
    )


def benchmark_plan(
    plan: ParallelPlan,
    *,
    metadata: MetadataBundle,
    max_rows: int = 1000,
) -> dict[str, Any]:
    """Run the same plan serial then parallel; return timing + row-count check."""
    serial = execute_plan(plan, metadata=metadata, max_rows=max_rows, parallel=False)
    parallel = execute_plan(plan, metadata=metadata, max_rows=max_rows, parallel=True)
    return {
        "ok": serial.ok and parallel.ok,
        "serial_ms": serial.serial_ms,
        "parallel_ms": parallel.parallel_ms,
        "serial_rows": len(serial.rows),
        "parallel_rows": len(parallel.rows),
        "columns_match": serial.columns == parallel.columns,
        "rows_match": serial.rows == parallel.rows,
        "sqls": plan.queries and [q.sql for q in plan.queries],
        "serial_error": serial.message if not serial.ok else "",
        "parallel_error": parallel.message if not parallel.ok else "",
    }


def try_parallel_pipeline(
    question: str,
    *,
    metadata: MetadataBundle,
    max_rows: int = 1000,
) -> ParallelExecResult | None:
    """Build+execute parallel plan, or return None if question not eligible."""
    plan = build_parallel_plan(question)
    if plan is None:
        return None
    return execute_plan(plan, metadata=metadata, max_rows=max_rows, parallel=True)
