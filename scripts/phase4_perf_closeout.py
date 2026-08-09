"""Phase-4 step-5 closeout: fixed question sets, cold/warm × cache, parallel bench.

Writes logs/perf_reports/phase4_perf.json + phase4_perf.md
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from querypilot.cache import clear_caches
from querypilot.config import get_settings
from querypilot.metadata_engine import load_metadata

# Set-S: simple demo-style questions
SET_S = [
    "有多少年龄大于30岁的女性客户？",
    "总资产超过100万的客户有多少人？",
    "买入交易额合计是多少？",
]

# Set-C: multi-table / multi-metric style (complex; parallel-eligible last)
SET_C = [
    "各营业部的客户数量",
    "统计客户的资产和持仓市值",
]


def _load_bench():
    path = ROOT / "scripts" / "bench_pipeline.py"
    spec = importlib.util.spec_from_file_location("bench_pipeline", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _api_key_ready() -> bool:
    key = get_settings().deepseek_api_key
    return bool(key) and not key.startswith("sk-your")


def _mode_stats(items: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    from querypilot.eval.runner import percentile

    subset = [it for it in items if it.get("mode") == mode]
    totals = [float(it["timing"]["total_ms"]) for it in subset if it["timing"]["total_ms"] > 0]
    hits = sum(1 for it in subset if it["timing"].get("cache_hit"))
    return {
        "count": len(subset),
        "ok": sum(1 for it in subset if it.get("ok")),
        "p50_ms": percentile(totals, 50) if totals else None,
        "p95_ms": percentile(totals, 95) if totals else None,
        "mean_ms": (sum(totals) / len(totals)) if totals else None,
        "cache_hit_count": hits,
        "cache_hit_rate": (hits / len(subset)) if subset else None,
    }


def _run_ask_matrix(bench, questions: list[str], *, live: bool) -> dict[str, Any]:
    md = load_metadata(load_db_codes=False)
    client = None
    if not live:
        # Reuse fake client pattern from tests (no LLM cost)
        from types import SimpleNamespace
        from typing import Any as AnyT

        class _FC:
            def __init__(self) -> None:
                self.calls = 0

            def create(self, **kwargs: AnyT) -> SimpleNamespace:
                self.calls += 1
                # Simple count query works for most demo questions under L1
                content = (
                    '{"sql":"SELECT COUNT(*) AS cnt FROM ads_cust_info_d",'
                    '"rationale":"bench","uses_cte":false}'
                )
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                    model="fake",
                    usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                )

        client = SimpleNamespace(chat=SimpleNamespace(completions=_FC()))

    clear_caches()
    t0 = time.perf_counter()
    warm_cache_on = bench.run_bench(
        questions,
        warm=True,
        rounds=1,
        max_rows=20,
        max_few_shots=2 if live else 0,
        include_values=False,
        client=client,
        metadata=md,
        use_cache=True,
        cache_rows=False,
    )
    wall_warm = (time.perf_counter() - t0) * 1000.0

    clear_caches()
    t0 = time.perf_counter()
    cold_no_cache = bench.run_bench(
        questions,
        warm=False,
        rounds=1,
        max_rows=20,
        max_few_shots=2 if live else 0,
        include_values=False,
        client=client,
        metadata=md,
        use_cache=False,
        cache_rows=False,
    )
    wall_cold = (time.perf_counter() - t0) * 1000.0

    return {
        "live_llm": live,
        "questions": questions,
        "cache_on_warm": {
            "wall_ms": wall_warm,
            "report": warm_cache_on,
            "by_mode": {
                "cold": _mode_stats(warm_cache_on["items"], "cold"),
                "warm": _mode_stats(warm_cache_on["items"], "warm"),
            },
        },
        "cache_off_cold": {
            "wall_ms": wall_cold,
            "report": cold_no_cache,
            "by_mode": {"cold": _mode_stats(cold_no_cache["items"], "cold")},
        },
    }


def _md_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    def fmt(row: list[str]) -> str:
        return "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(row)) + " |"
    lines = [fmt(rows[0]), "| " + " | ".join("-" * w for w in widths) + " |"]
    lines.extend(fmt(r) for r in rows[1:])
    return "\n".join(lines)


def _fmt_ms(v: Any) -> str:
    if v is None:
        return "-"
    return f"{float(v):.1f}"


def build_markdown(payload: dict[str, Any]) -> str:
    ask = payload["ask_matrix"]
    par = payload["parallel"]
    cold = ask["cache_on_warm"]["by_mode"]["cold"]
    warm = ask["cache_on_warm"]["by_mode"]["warm"]
    off = ask["cache_off_cold"]["by_mode"]["cold"]

    lines = [
        "# Phase-4 performance closeout",
        "",
        f"- created_at: {payload['created_at']}",
        f"- live_llm: {ask['live_llm']}",
        f"- questions: {len(ask['questions'])} (Set-S={len(SET_S)}, Set-C={len(SET_C)})",
        "",
        "## Latency vs phase-3 baseline",
        "",
        _md_table(
            [
                ["指标", "阶段三基线", "阶段四冷路径(cache on)", "阶段四热路径(cache hit)", "cache off cold"],
                [
                    "p50 total_ms",
                    "≈3580",
                    _fmt_ms(cold.get("p50_ms")),
                    _fmt_ms(warm.get("p50_ms")),
                    _fmt_ms(off.get("p50_ms")),
                ],
                [
                    "p95 total_ms",
                    "≈4220 / ≈5021",
                    _fmt_ms(cold.get("p95_ms")),
                    _fmt_ms(warm.get("p95_ms")),
                    _fmt_ms(off.get("p95_ms")),
                ],
                [
                    "mean total_ms",
                    "≈3873",
                    _fmt_ms(cold.get("mean_ms")),
                    _fmt_ms(warm.get("mean_ms")),
                    _fmt_ms(off.get("mean_ms")),
                ],
                [
                    "cache hit 率",
                    "—",
                    _fmt_ms((cold.get("cache_hit_rate") or 0) * 100) + "%",
                    _fmt_ms((warm.get("cache_hit_rate") or 0) * 100) + "%",
                    "0%",
                ],
            ]
        ),
        "",
        "## Parallel plan (mode B)",
        "",
    ]
    if par.get("ok"):
        speedup = None
        if par.get("serial_ms") and par.get("parallel_ms"):
            speedup = par["serial_ms"] / par["parallel_ms"] if par["parallel_ms"] else None
        lines.extend(
            [
                f"- question: {par.get('question')}",
                f"- domains: {par.get('domains')}",
                f"- serial_ms: {_fmt_ms(par.get('serial_ms'))}",
                f"- parallel_ms: {_fmt_ms(par.get('parallel_ms'))}",
                f"- speedup: {_fmt_ms(speedup)}x" if speedup else "- speedup: -",
                f"- rows_match: {par.get('rows_match')}",
                "",
            ]
        )
    else:
        lines.append(f"- FAIL: {par.get('error') or par}")
        lines.append("")

    lines.extend(
        [
            "## Notes",
            "",
            "- Cold path still LLM-dominated when live_llm=true; warm path skips generate (cache_hit).",
            "- Parallel path is opt-in rule metrics (ask --parallel); does not change default EX.",
            "- phase3_baseline p50≈3.6s / p95≈5.0s (official 7-case eval, 2026-08-08).",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase-4 perf closeout")
    p.add_argument("--fake", action="store_true", help="Force fake LLM client")
    p.add_argument("--live", action="store_true", help="Force live DeepSeek")
    p.add_argument(
        "--output-json",
        default="logs/perf_reports/phase4_perf.json",
    )
    p.add_argument(
        "--output-md",
        default="logs/perf_reports/phase4_perf.md",
    )
    args = p.parse_args(argv)

    live = False
    if args.live:
        live = True
    elif args.fake:
        live = False
    else:
        live = _api_key_ready()

    if live and not _api_key_ready():
        print("error: --live but DEEPSEEK_API_KEY missing", file=sys.stderr)
        return 2

    bench = _load_bench()
    questions = SET_S + SET_C
    ask_matrix = _run_ask_matrix(bench, questions, live=live)
    parallel = bench.run_parallel_bench(
        "统计客户的资产和持仓市值",
        max_rows=500,
        metadata=load_metadata(load_db_codes=False),
    )

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "phase": 4,
        "step": 5,
        "sets": {"S": SET_S, "C": SET_C},
        "ask_matrix": ask_matrix,
        "parallel": parallel,
        "phase3_baseline": {
            "p50_ms": 3580,
            "p95_ms": 5021,
            "mean_ms": 3873,
            "source": "logs/eval_reports/phase3_baseline (approx)",
        },
    }

    out_json = Path(args.output_json)
    if not out_json.is_absolute():
        out_json = ROOT / out_json
    out_md = Path(args.output_md)
    if not out_md.is_absolute():
        out_md = ROOT / out_md
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)

    # Slim JSON for disk (drop full nested items duplication if huge — keep reports)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md = build_markdown(payload)
    out_md.write_text(md, encoding="utf-8")

    # Also keep a tracked copy under logs/ for答辩 (perf_reports is gitignored)
    tracked = ROOT / "logs" / "04-phase4_perf.md"
    tracked.write_text(md, encoding="utf-8")

    cold = ask_matrix["cache_on_warm"]["by_mode"]["cold"]
    warm = ask_matrix["cache_on_warm"]["by_mode"]["warm"]
    print(md)
    print(f"saved: {out_json}")
    print(f"saved: {out_md}")
    print(f"saved: {tracked}")
    print(
        f"summary: live={live} cold_p50={_fmt_ms(cold.get('p50_ms'))} "
        f"warm_p50={_fmt_ms(warm.get('p50_ms'))} "
        f"warm_hit_rate={warm.get('cache_hit_rate')}"
    )
    return 0 if parallel.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
