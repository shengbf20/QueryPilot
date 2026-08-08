"""QueryPilot CLI entry point."""

from __future__ import annotations

import argparse
from typing import Sequence

from querypilot import __version__
from querypilot.agent.models import PipelineResult


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

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
