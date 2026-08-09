"""Batch EX evaluation runner + latency baseline (phase-3 step 2).

Per case: ask(question) → execute(gold_sql) → compare_results → TimingInfo
Then aggregate into EvalReport (EX%, failed_ids, p50/p95).
"""

from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
from openai import OpenAI

from querypilot.config import get_settings
from querypilot.eval.dataset import load_qa_cases, load_qa_cases_many
from querypilot.eval.execution_match import compare_results
from querypilot.eval.models import CaseEvalResult, EvalCase, EvalReport, TimingInfo

AskFn = Callable[..., Any]
ExecuteFn = Callable[..., Any]


def percentile(values: Sequence[float], p: float) -> float | None:
    """Nearest-rank percentile; ``p`` in [0, 100]. Empty → None."""
    if not values:
        return None
    if p < 0 or p > 100:
        raise ValueError(f"percentile p must be in [0, 100], got {p}")
    ordered = sorted(float(v) for v in values)
    if p == 0:
        return ordered[0]
    rank = max(1, min(len(ordered), math.ceil(p / 100.0 * len(ordered))))
    return ordered[rank - 1]


def summarize(results: Sequence[CaseEvalResult]) -> EvalReport:
    """Aggregate per-case results into EX% / latency percentiles / failed ids."""
    total = len(results)
    matched_count = sum(1 for r in results if r.matched)
    accuracy = (matched_count / total) if total else 0.0
    failed_ids = [r.case_id for r in results if not r.matched]

    by_diff_hits: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        key = r.difficulty or "unknown"
        by_diff_hits[key].append(r.matched)
    by_difficulty = {
        k: (sum(v) / len(v) if v else 0.0) for k, v in sorted(by_diff_hits.items())
    }

    totals = [r.timing.total_ms for r in results if r.timing.total_ms > 0]
    mean_ms = (sum(totals) / len(totals)) if totals else None

    return EvalReport(
        total=total,
        matched_count=matched_count,
        accuracy=accuracy,
        results=list(results),
        failed_ids=failed_ids,
        by_difficulty=by_difficulty,
        p50_ms=percentile(totals, 50) if totals else None,
        p95_ms=percentile(totals, 95) if totals else None,
        mean_ms=mean_ms,
    )


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def run_case(
    case: EvalCase,
    *,
    ask_fn: AskFn | None = None,
    execute_fn: ExecuteFn | None = None,
    client: OpenAI | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
    max_rows: int | None = None,
    **kwargs: Any,
) -> CaseEvalResult:
    """Evaluate one gold case: ask → execute(gold_sql) → EX match → timing.

    ``ask_fn`` / ``execute_fn`` override defaults for tests. Single-case failures
    set ``matched=False`` and fill ``error`` / ``stage`` (do not raise).
    """
    from querypilot.agent.pipeline import ask as default_ask
    from querypilot.db import execute as default_execute

    t_all = time.perf_counter()
    ask_ms = 0.0
    gold_ms = 0.0
    match_ms = 0.0

    pred_sql = ""
    pred_columns: list[str] = []
    pred_rows: list[tuple[Any, ...]] = []
    ask_ok = False
    gold_ok = False
    error = ""
    stage = "ask"
    matched = False
    score = 0.0
    match_reason = ""

    # --- ask ---
    t0 = time.perf_counter()
    try:
        if ask_fn is not None:
            pipe = ask_fn(case.question)
        else:
            ask_kwargs = dict(kwargs)
            if client is not None:
                ask_kwargs["client"] = client
            if con is not None:
                ask_kwargs["con"] = con
            if max_rows is not None:
                ask_kwargs["max_rows"] = max_rows
            pipe = default_ask(case.question, **ask_kwargs)
    except Exception as exc:  # noqa: BLE001 — per-case isolation
        ask_ms = _elapsed_ms(t0)
        error = f"ask raised: {exc}"
        stage = "ask"
        pipe = None
    else:
        ask_ms = _elapsed_ms(t0)
        pred_sql = str(getattr(pipe, "sql", "") or "")
        if getattr(pipe, "ok", False):
            ask_ok = True
            pred_columns = list(getattr(pipe, "columns", []) or [])
            pred_rows = [tuple(r) for r in (getattr(pipe, "rows", []) or [])]
            stage = "gold_execute"
        else:
            error = str(getattr(pipe, "message", "") or "ask failed")
            stage = str(getattr(pipe, "stage", "") or "ask")

    # --- gold SQL ---
    t0 = time.perf_counter()
    gold_columns: list[str] = []
    gold_rows: list[tuple[Any, ...]] = []
    try:
        if execute_fn is not None:
            gold = execute_fn(case.gold_sql)
        else:
            gold = default_execute(case.gold_sql, con=con, max_rows=max_rows)
        gold_ms = _elapsed_ms(t0)
        gold_ok = True
        gold_columns = list(gold.columns)
        gold_rows = [tuple(r) for r in gold.rows]
    except Exception as exc:  # noqa: BLE001 — per-case isolation
        gold_ms = _elapsed_ms(t0)
        gold_ok = False
        msg = f"gold execute failed: {exc}"
        error = f"{error}; {msg}" if error else msg
        if ask_ok:
            stage = "gold_execute"

    # --- EX match ---
    if ask_ok and gold_ok:
        t0 = time.perf_counter()
        mr = compare_results(pred_columns, pred_rows, gold_columns, gold_rows)
        match_ms = _elapsed_ms(t0)
        matched = mr.matched
        score = mr.score
        match_reason = mr.reason
        stage = "done"
        if not matched and not error:
            error = mr.reason

    total_ms = _elapsed_ms(t_all)
    stage_timing = getattr(pipe, "timing", None) if pipe is not None else None
    return CaseEvalResult(
        case_id=case.id,
        question=case.question,
        matched=matched,
        score=score,
        gold_sql=case.gold_sql,
        pred_sql=pred_sql,
        ask_ok=ask_ok,
        gold_ok=gold_ok,
        error=error,
        match_reason=match_reason,
        difficulty=case.difficulty,
        timing=TimingInfo(
            total_ms=total_ms,
            ask_ms=ask_ms,
            gold_execute_ms=gold_ms,
            match_ms=match_ms,
            prune_ms=float(getattr(stage_timing, "prune_ms", 0.0) or 0.0),
            generate_ms=float(getattr(stage_timing, "generate_ms", 0.0) or 0.0),
            l1_ms=float(getattr(stage_timing, "l1_ms", 0.0) or 0.0),
            l2_ms=float(getattr(stage_timing, "l2_ms", 0.0) or 0.0),
            execute_ms=float(getattr(stage_timing, "execute_ms", 0.0) or 0.0),
            probe_ms=float(getattr(stage_timing, "probe_ms", 0.0) or 0.0),
            cache_hit=bool(getattr(stage_timing, "cache_hit", False)),
        ),
        stage=stage,
    )


def run_eval(
    cases: Sequence[EvalCase] | None = None,
    *,
    path: Path | str | None = None,
    paths: Sequence[Path | str] | None = None,
    limit: int | None = None,
    ask_fn: AskFn | None = None,
    execute_fn: ExecuteFn | None = None,
    client: OpenAI | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
    max_rows: int | None = None,
    save_path: Path | str | bool | None = None,
    **kwargs: Any,
) -> EvalReport:
    """Batch-evaluate gold cases and return an aggregated EvalReport.

    ``save_path``: ``True`` → timestamped file under ``logs/eval_reports/``;
    a path string/Path → write there; ``None``/``False`` → do not save.

    Load order when ``cases`` is omitted: ``paths`` (if set) else single ``path``
    (default ``data/Q&A.xlsx``). Kwargs such as ``max_few_shots`` /
    ``allow_exact_few_shot`` are forwarded to ``ask`` when using the default ask.
    """
    if cases is None:
        if paths:
            path_list = list(paths)
            if path is not None:
                path_list = [path, *path_list]
            cases = load_qa_cases_many(path_list)
        else:
            cases = load_qa_cases(path)
    case_list = list(cases)
    if limit is not None:
        case_list = case_list[: max(0, limit)]

    results = [
        run_case(
            case,
            ask_fn=ask_fn,
            execute_fn=execute_fn,
            client=client,
            con=con,
            max_rows=max_rows,
            **kwargs,
        )
        for case in case_list
    ]
    report = summarize(results)
    if save_path:
        target = None if save_path is True else save_path
        save_eval_report(report, target)
    return report


def default_report_dir() -> Path:
    return get_settings().root_dir / "logs" / "eval_reports"


def save_eval_report(
    report: EvalReport,
    path: Path | str | None = None,
) -> Path:
    """Write EvalReport JSON (UTF-8). Default: logs/eval_reports/eval_YYYYMMDD_HHMMSS.json."""
    if path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = default_report_dir() / f"eval_{stamp}.json"
    else:
        out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict()
    payload["saved_at"] = datetime.now(timezone.utc).isoformat()
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def load_eval_report(path: Path | str) -> dict[str, Any]:
    """Read a previously saved eval report JSON."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "AskFn",
    "ExecuteFn",
    "TimingInfo",
    "default_report_dir",
    "load_eval_report",
    "percentile",
    "run_case",
    "run_eval",
    "save_eval_report",
    "summarize",
]
