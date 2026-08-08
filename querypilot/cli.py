"""QueryPilot CLI entry point."""

from __future__ import annotations

import argparse
from typing import Sequence

from querypilot import __version__
from querypilot.agent.models import PipelineResult
from querypilot.eval.models import EvalReport


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="querypilot",
        description="QueryPilot — Agentic NL2SQL for customer marketing analytics",
    )
    parser.add_argument("--version", action="version", version=f"QueryPilot {__version__}")

    sub = parser.add_subparsers(dest="command")

    ask_parser = sub.add_parser("ask", help="Ask a natural-language analytics question")
    ask_parser.add_argument("question", nargs="+", help="Natural language question")
    ask_parser.add_argument(
        "--max-rows",
        type=int,
        default=20,
        help="Max rows to fetch/print (default: 20)",
    )
    ask_parser.add_argument(
        "--max-few-shots",
        type=int,
        default=3,
        help="Max few-shot examples in the prompt (default: 3)",
    )

    eval_parser = sub.add_parser("eval", help="Run Execution Match eval on gold Q&A cases")
    eval_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max gold cases to evaluate (default: all)",
    )
    eval_parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="Gold Q&A xlsx path (default: data/Q&A.xlsx)",
    )
    eval_parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Max rows for ask/execute (keep both ends consistent)",
    )
    eval_parser.add_argument(
        "--max-few-shots",
        type=int,
        default=3,
        help="Max few-shot examples passed to ask (default: 3)",
    )
    eval_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write JSON report to this path (default: logs/eval_reports/eval_*.json)",
    )
    eval_parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not write a JSON report",
    )
    return parser


def format_pipeline_result(result: PipelineResult, *, max_print_rows: int = 20) -> str:
    """Pretty-print a PipelineResult for CLI / demo."""
    lines: list[str] = [
        f"status: {'ok' if result.ok else 'failed'}"
        + (" (degraded)" if result.degraded else "")
        + (" (corrected)" if result.corrected else ""),
        f"stage: {result.stage or '-'}",
        f"question: {result.question}",
    ]
    if result.tables:
        lines.append(f"tables: {', '.join(result.tables)}")
    if result.sql:
        lines.append("sql:")
        lines.append(result.sql)
    if result.rationale:
        lines.append(f"rationale: {result.rationale}")
    if result.message:
        lines.append(f"message: {result.message}")
    if result.probe_suggestions:
        lines.append("probe suggestions:")
        for tip in result.probe_suggestions:
            lines.append(f"  - {tip}")

    if result.ok and result.columns:
        lines.append(f"rows: {result.row_count}")
        lines.append(" | ".join(result.columns))
        for row in result.rows[:max_print_rows]:
            lines.append(" | ".join("" if v is None else str(v) for v in row))
        if result.row_count > max_print_rows:
            lines.append(f"... ({result.row_count - max_print_rows} more rows not shown)")

    return "\n".join(lines)


def format_eval_report(report: EvalReport) -> str:
    """Pretty-print an EvalReport summary (CLI / demo_eval)."""
    lines: list[str] = [
        f"EX: {report.matched_count}/{report.total} = {report.accuracy:.1%}  "
        f"failed={report.failed_ids}  "
        f"p50_ms={report.p50_ms}  p95_ms={report.p95_ms}"
    ]
    for item in report.results:
        flag = "OK" if item.matched else "FAIL"
        lines.append(
            f"  [{flag}] id={item.case_id} stage={item.stage} "
            f"ask_ok={item.ask_ok} gold_ok={item.gold_ok} "
            f"total_ms={item.timing.total_ms:.0f}"
        )
        if item.error:
            lines.append(f"       error={item.error[:160]}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "ask":
        from querypilot.agent import ask

        question = " ".join(args.question).strip()
        result = ask(
            question,
            max_rows=args.max_rows,
            max_few_shots=args.max_few_shots,
        )
        print(format_pipeline_result(result, max_print_rows=args.max_rows))
        return 0 if result.ok else 1

    if args.command == "eval":
        if args.no_save and args.output is not None:
            parser.error("--output and --no-save are mutually exclusive")

        from querypilot.eval import run_eval, save_eval_report

        report = run_eval(
            path=args.path,
            limit=args.limit,
            max_rows=args.max_rows,
            max_few_shots=args.max_few_shots,
        )
        print(format_eval_report(report))
        if not args.no_save:
            out = save_eval_report(report, args.output)
            print(f"report saved: {out}")
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
