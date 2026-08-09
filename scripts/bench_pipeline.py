"""Cold/warm pipeline latency bench with per-stage timing (phase-4 step 1).

Examples:
  python scripts/bench_pipeline.py --limit 2 --cold
  python scripts/bench_pipeline.py --limit 2 --warm --output logs/perf_reports/step1.json
  python scripts/bench_pipeline.py --from-qa --limit 2 --cold
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from querypilot.agent import ask
from querypilot.config import get_settings
from querypilot.eval.runner import percentile
from querypilot.metadata_engine import load_metadata

SAMPLES = [
    "有多少年龄大于30岁的女性客户？",
    "总资产超过100万的客户有多少人？",
    "买入交易额合计是多少？",
    "各营业部的客户数量",
    "200岁以上的女性客户有多少",
]

STAGE_KEYS = (
    "prune_ms",
    "generate_ms",
    "l1_ms",
    "l2_ms",
    "execute_ms",
    "probe_ms",
    "total_ms",
)


def _load_questions(*, from_qa: bool, limit: int | None, question: str | None) -> list[str]:
    if question:
        return [question.strip()]
    if from_qa:
        from querypilot.eval.dataset import load_qa_cases

        cases = load_qa_cases()
        qs = [c.question for c in cases]
    else:
        qs = list(SAMPLES)
    if limit is not None:
        qs = qs[: max(0, limit)]
    return qs


def _timing_dict(result: Any) -> dict[str, Any]:
    t = getattr(result, "timing", None)
    if t is None:
        return {k: 0.0 for k in STAGE_KEYS} | {"cache_hit": False}
    return {
        "prune_ms": float(t.prune_ms),
        "generate_ms": float(t.generate_ms),
        "l1_ms": float(t.l1_ms),
        "l2_ms": float(t.l2_ms),
        "execute_ms": float(t.execute_ms),
        "probe_ms": float(t.probe_ms),
        "total_ms": float(t.total_ms),
        "cache_hit": bool(t.cache_hit),
    }


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def run_bench(
    questions: Sequence[str],
    *,
    warm: bool = False,
    rounds: int = 1,
    max_rows: int = 20,
    max_few_shots: int = 2,
    include_values: bool = True,
    client: Any | None = None,
    metadata: Any | None = None,
    use_cache: bool | None = None,
    cache_rows: bool | None = None,
) -> dict[str, Any]:
    """Run ask() over questions; optionally warm (repeat each question)."""
    from querypilot.cache import clear_caches

    if use_cache is False:
        clear_caches()

    md = metadata or load_metadata(load_db_codes=include_values, use_cache=use_cache)
    mode = "warm" if warm else "cold"
    items: list[dict[str, Any]] = []

    for qi, q in enumerate(questions):
        # cold: ``rounds`` runs; warm: 1 cold + ``rounds`` warm (same question)
        if warm:
            run_specs = [("cold", 1), ("warm", max(1, rounds))]
        else:
            run_specs = [("cold", max(1, rounds))]

        for label, n in run_specs:
            for r in range(n):
                t_wall = time.perf_counter()
                result = ask(
                    q,
                    metadata=md,
                    client=client,
                    max_rows=max_rows,
                    max_few_shots=max_few_shots,
                    include_values=include_values,
                    use_cache=use_cache,
                    cache_rows=cache_rows,
                )
                wall_ms = (time.perf_counter() - t_wall) * 1000.0
                timing = _timing_dict(result)
                items.append(
                    {
                        "question_index": qi,
                        "question": q,
                        "mode": label,
                        "round": r,
                        "ok": bool(result.ok),
                        "stage": result.stage,
                        "wall_ms": wall_ms,
                        "timing": timing,
                        "message": (result.message or "")[:200],
                    }
                )

    totals = [it["timing"]["total_ms"] for it in items if it["timing"]["total_ms"] > 0]
    stage_means: dict[str, float | None] = {}
    for key in STAGE_KEYS:
        vals = [float(it["timing"][key]) for it in items]
        stage_means[key] = _mean(vals)

    by_mode: dict[str, dict[str, Any]] = {}
    for mode_name in ("cold", "warm"):
        subset = [it for it in items if it["mode"] == mode_name]
        mode_totals = [it["timing"]["total_ms"] for it in subset if it["timing"]["total_ms"] > 0]
        mode_stages: dict[str, float | None] = {}
        for key in STAGE_KEYS:
            mode_stages[key] = _mean([float(it["timing"][key]) for it in subset]) if subset else None
        by_mode[mode_name] = {
            "count": len(subset),
            "p50_ms": percentile(mode_totals, 50) if mode_totals else None,
            "p95_ms": percentile(mode_totals, 95) if mode_totals else None,
            "mean_ms": _mean(mode_totals),
            "stage_mean_ms": mode_stages,
        }

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode_requested": mode,
        "rounds": rounds,
        "question_count": len(questions),
        "run_count": len(items),
        "ok_count": sum(1 for it in items if it["ok"]),
        "p50_ms": percentile(totals, 50) if totals else None,
        "p95_ms": percentile(totals, 95) if totals else None,
        "mean_ms": _mean(totals),
        "stage_mean_ms": stage_means,
        "by_mode": by_mode,
        "items": items,
    }
    return report


def format_bench_report(report: dict[str, Any]) -> str:
    lines = [
        f"bench: questions={report['question_count']} runs={report['run_count']} "
        f"ok={report['ok_count']} mode={report['mode_requested']}",
        f"overall: p50_ms={report['p50_ms']} p95_ms={report['p95_ms']} mean_ms={report['mean_ms']}",
        "stage_mean_ms: "
        + " ".join(
            f"{k.replace('_ms', '')}={v:.1f}" if v is not None else f"{k.replace('_ms', '')}=-"
            for k, v in (report.get("stage_mean_ms") or {}).items()
        ),
    ]
    for mode_name in ("cold", "warm"):
        block = (report.get("by_mode") or {}).get(mode_name) or {}
        if not block.get("count"):
            continue
        lines.append(
            f"  [{mode_name}] n={block['count']} p50={block['p50_ms']} "
            f"p95={block['p95_ms']} mean={block['mean_ms']}"
        )
        sm = block.get("stage_mean_ms") or {}
        lines.append(
            "    stages: "
            + " ".join(
                f"{k.replace('_ms', '')}={v:.1f}" if v is not None else f"{k.replace('_ms', '')}=-"
                for k, v in sm.items()
            )
        )
    for it in report.get("items") or []:
        t = it["timing"]
        flag = "OK" if it["ok"] else "FAIL"
        hit = "yes" if t.get("cache_hit") else "no"
        lines.append(
            f"  [{flag}] {it['mode']} q{it['question_index']} stage={it['stage']} "
            f"total={t['total_ms']:.1f} gen={t['generate_ms']:.1f} "
            f"l1={t['l1_ms']:.1f} l2={t['l2_ms']:.1f} exec={t['execute_ms']:.1f} "
            f"cache_hit={hit}"
        )
        q_short = it["question"].replace("\n", " ")[:60]
        lines.append(f"       Q: {q_short}")
    return "\n".join(lines)


def save_bench_report(report: dict[str, Any], path: Path | str | None = None) -> Path:
    settings = get_settings()
    out_dir = settings.root_dir / "logs" / "perf_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    if path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"bench_{stamp}.json"
    else:
        path = Path(path)
        if not path.is_absolute():
            path = settings.root_dir / path
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="QueryPilot pipeline latency bench (phase-4 step 1)")
    p.add_argument("--limit", type=int, default=None, help="Max questions (default: all samples)")
    p.add_argument("--from-qa", action="store_true", help="Load questions from data/Q&A.xlsx")
    p.add_argument("--question", type=str, default=None, help="Single question to bench")
    p.add_argument("--cold", action="store_true", help="Cold runs only (default if neither flag)")
    p.add_argument("--warm", action="store_true", help="Run cold once then warm rounds per question")
    p.add_argument("--rounds", type=int, default=1, help="Rounds per mode (default: 1)")
    p.add_argument("--max-rows", type=int, default=20)
    p.add_argument("--max-few-shots", type=int, default=2)
    p.add_argument("--no-values", action="store_true", help="Skip value descriptors in prune/prompt")
    p.add_argument("--no-cache", action="store_true", help="Disable all caches (cold-path control)")
    p.add_argument(
        "--cache-rows",
        action="store_true",
        help="Cache result rows on hit (skip re-execute; demo/bench)",
    )
    p.add_argument(
        "--parallel",
        action="store_true",
        help="Benchmark mode-B metric parallel plan (serial vs parallel execute)",
    )
    p.add_argument("--output", type=str, default=None, help="JSON report path")
    p.add_argument("--no-save", action="store_true", help="Do not write JSON report")
    return p


def run_parallel_bench(
    question: str,
    *,
    max_rows: int = 1000,
    metadata: Any | None = None,
) -> dict[str, Any]:
    """Compare serial vs parallel execute for a multi-metric rule plan."""
    from querypilot.agent.parallel import benchmark_plan, build_parallel_plan

    md = metadata or load_metadata(load_db_codes=False)
    plan = build_parallel_plan(question)
    if plan is None:
        return {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "mode_requested": "parallel",
            "ok": False,
            "error": "question not eligible for parallel plan (need 客群 + ≥2 metric domains)",
            "question": question,
        }
    cmp = benchmark_plan(plan, metadata=md, max_rows=max_rows)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode_requested": "parallel",
        "question": question,
        "domains": [q.name for q in plan.queries],
        **cmp,
    }


def format_parallel_bench(report: dict[str, Any]) -> str:
    if not report.get("ok"):
        return (
            f"parallel_bench: FAIL q={report.get('question')!r} "
            f"err={report.get('error') or report.get('serial_error') or report.get('parallel_error')}"
        )
    return (
        f"parallel_bench: OK domains={report.get('domains')} "
        f"serial_ms={report.get('serial_ms'):.1f} parallel_ms={report.get('parallel_ms'):.1f} "
        f"rows={report.get('parallel_rows')} rows_match={report.get('rows_match')}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.no_save and args.output is not None:
        print("error: --output and --no-save are mutually exclusive", file=sys.stderr)
        return 2

    if args.parallel:
        q = args.question or "统计客户的资产和持仓市值"
        report = run_parallel_bench(q, max_rows=args.max_rows)
        print(format_parallel_bench(report))
        if not args.no_save:
            path = save_bench_report(report, args.output)
            print(f"saved: {path}")
        return 0 if report.get("ok") else 1

    questions = _load_questions(
        from_qa=args.from_qa,
        limit=args.limit,
        question=args.question,
    )
    if not questions:
        print("error: no questions to bench", file=sys.stderr)
        return 2

    warm = bool(args.warm)
    # --cold is explicit but default when --warm not set
    _ = args.cold

    report = run_bench(
        questions,
        warm=warm,
        rounds=max(1, args.rounds),
        max_rows=args.max_rows,
        max_few_shots=args.max_few_shots,
        include_values=not args.no_values,
        use_cache=False if args.no_cache else None,
        cache_rows=True if args.cache_rows else None,
    )
    print(format_bench_report(report))

    if not args.no_save:
        path = save_bench_report(report, args.output)
        print(f"saved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
