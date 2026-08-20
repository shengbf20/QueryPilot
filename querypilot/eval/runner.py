"""批量 Execution Match 评测与延迟基线（阶段三步骤 2）。

每条用例：ask(question) → execute(gold_sql) → compare_results → TimingInfo
再汇总为 EvalReport（EX%、failed_ids、p50/p95）。
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
from querypilot.eval.safety_match import is_safety_refuse_case, safety_refusal_match

AskFn = Callable[..., Any]
ExecuteFn = Callable[..., Any]


def percentile(values: Sequence[float], p: float) -> float | None:
    """最近秩百分位；``p`` 取值 [0, 100]。空序列返回 None。"""
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
    """将逐条结果汇总为 EX%、延迟分位数与失败用例 id。"""
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
    """评测一条金标用例：ask → execute(gold_sql) → EX 比对 → 计时。

    Extra3（``eval_mode=safety_refuse``）不执行金标 SQL，以「拒绝 + 安全警告」为做对。

    ``ask_fn`` / ``execute_fn`` 可覆盖默认实现（供测试）。单条失败时置 ``matched=False``
    并填写 ``error`` / ``stage``，不向外抛异常。
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

    # 执行ask操作
    t0 = time.perf_counter() # 开始计时
    try:
        if ask_fn is not None:
            pipe = ask_fn(case.question) # 使用自定义ask函数
        else: 
            # 使用默认ask函数，设置ask参数
            ask_kwargs = dict(kwargs)
            if client is not None:
                ask_kwargs["client"] = client
            if con is not None:
                ask_kwargs["con"] = con
            if max_rows is not None:
                ask_kwargs["max_rows"] = max_rows
            pipe = default_ask(case.question, **ask_kwargs) # 调用ask函数，获取管道结果
    except Exception as exc:  # 发生异常
        # noqa: BLE001 — per-case isolation 单条用例隔离，避免影响其他用例
        ask_ms = _elapsed_ms(t0)
        error = f"ask raised: {exc}" # 设置错误信息
        stage = "ask"
        pipe = None
    else:
        ask_ms = _elapsed_ms(t0) # 结束计时，计算ask耗时
        pred_sql = str(getattr(pipe, "sql", "") or "")
        if getattr(pipe, "ok", False):
            # 正常返回且pipe.ok为True
            ask_ok = True # 设置ask成功标志
            pred_columns = list(getattr(pipe, "columns", []) or []) # 获取预测列名
            pred_rows = [tuple(r) for r in (getattr(pipe, "rows", []) or [])] # 获取预测行数据
            stage = "gold_execute" # 设置stage为gold_execute
        else:
            # 正常返回且pipe.ok为False
            error = str(getattr(pipe, "message", "") or "ask failed") # 设置错误信息
            stage = str(getattr(pipe, "stage", "") or "ask") # 设置stage为ask

    if is_safety_refuse_case(case):
        matched, score, match_reason = safety_refusal_match(pipe)
        gold_ok = True
        if matched:
            error = ""
            stage = str(getattr(pipe, "stage", "") or "safety")
        elif not error:
            error = match_reason
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
                gold_execute_ms=0.0,
                match_ms=0.0,
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

    # 执行EX比对操作
    if ask_ok and gold_ok:
        t0 = time.perf_counter() # 开始计时
        mr = compare_results(pred_columns, pred_rows, gold_columns, gold_rows)
        match_ms = _elapsed_ms(t0) # 结束计时，计算EX比对耗时
        matched = mr.matched
        score = mr.score # 设置匹配得分
        match_reason = mr.reason # 设置匹配原因
        stage = "done"
        if not matched and not error:
            error = mr.reason # 设置错误信息

    total_ms = _elapsed_ms(t_all) # 结束计时，计算总耗时
    stage_timing = getattr(pipe, "timing", None) if pipe is not None else None
    return CaseEvalResult(
        case_id=case.id, # 设置用例ID
        question=case.question, # 设置问题
        matched=matched, # 设置匹配结果
        score=score, # 设置得分
        gold_sql=case.gold_sql, # 设置黄金SQL
        pred_sql=pred_sql, # 设置预测SQL
        ask_ok=ask_ok, # 设置ask成功标志
        gold_ok=gold_ok, # 设置gold成功标志
        error=error, # 设置错误信息
        match_reason=match_reason, # 设置匹配原因
        difficulty=case.difficulty, # 设置难度
        timing=TimingInfo(
            total_ms=total_ms, # 设置总耗时
            ask_ms=ask_ms,
            gold_execute_ms=gold_ms, # 设置gold执行耗时
            match_ms=match_ms, # 设置匹配耗时
            prune_ms=float(getattr(stage_timing, "prune_ms", 0.0) or 0.0), # 设置修剪耗时
            generate_ms=float(getattr(stage_timing, "generate_ms", 0.0) or 0.0), # 设置生成耗时
            l1_ms=float(getattr(stage_timing, "l1_ms", 0.0) or 0.0), # 设置L1耗时
            l2_ms=float(getattr(stage_timing, "l2_ms", 0.0) or 0.0), # 设置L2耗时
            execute_ms=float(getattr(stage_timing, "execute_ms", 0.0) or 0.0), # 设置执行耗时
            probe_ms=float(getattr(stage_timing, "probe_ms", 0.0) or 0.0), # 设置探测耗时
            cache_hit=bool(getattr(stage_timing, "cache_hit", False)), # 设置缓存命中标志
        ),
        stage=stage, # 设置stage
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
    max_workers: int | None = None,
    **kwargs: Any,
) -> EvalReport:
    """批量评测金标用例，返回汇总后的 EvalReport。

    ``save_path``：``True`` 写入 ``logs/eval_reports/`` 下带时间戳的文件；
    路径字符串/Path 则写到该位置；``None``/``False`` 不落盘。

    ``max_workers``：大于 1 时并发评测（每条用例自有 DuckDB 连接；此模式下忽略共享的 ``con``）。

    未传入 ``cases`` 时的加载顺序：有 ``paths`` 则用它，否则用单个 ``path``
    （默认 ``data/Q&A.xlsx``）。使用默认 ask 时，``max_few_shots`` /
    ``allow_exact_few_shot`` 等 kwargs 会转发给 ``ask``。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

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
        case_list = case_list[: max(0, limit)] # 限制评测用例数量

    workers = int(max_workers) if max_workers is not None else 1
    # 并发评测时不能共享一个DuckDB连接
    case_con = None if workers > 1 else con

    def _run_one(case: EvalCase) -> CaseEvalResult:
        """评测一条用例"""
        return run_case(
            case,
            ask_fn=ask_fn,
            execute_fn=execute_fn,
            client=client,
            con=case_con,
            max_rows=max_rows,
            **kwargs,
        )

    if workers <= 1 or len(case_list) <= 1:
        results = [_run_one(case) for case in case_list] # 单线程评测
    else:
        ordered: list[CaseEvalResult | None] = [None] * len(case_list) # 并发评测
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_run_one, case): i for i, case in enumerate(case_list)}
            for fut in as_completed(futs):
                ordered[futs[fut]] = fut.result()
        results = [r for r in ordered if r is not None]

    report = summarize(results) # 汇总结果
    if save_path:
        target = None if save_path is True else save_path # 保存路径
        save_eval_report(report, target)
    return report


def default_report_dir() -> Path:
    return get_settings().root_dir / "logs" / "eval_reports"


def save_eval_report(
    report: EvalReport,
    path: Path | str | None = None,
) -> Path:
    """将 EvalReport 写成 UTF-8 JSON。默认路径：logs/eval_reports/eval_YYYYMMDD_HHMMSS.json。"""
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
    """读取此前保存的评测报告 JSON。"""
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
