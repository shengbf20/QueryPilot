"""QueryPilot CLI entry point."""

from __future__ import annotations

import argparse
from typing import Sequence

from querypilot import __version__
from querypilot.agent.models import PipelineResult
from querypilot.eval.models import Diagnosis, EvalReport


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
    eval_parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Run Eval-Agent attribution on failed cases",
    )
    eval_parser.add_argument(
        "--diagnose-output",
        type=str,
        default=None,
        help="Write diagnosis JSON path (default: logs/eval_reports/diag_*.json)",
    )
    eval_parser.add_argument(
        "--no-llm-diagnose",
        action="store_true",
        help="With --diagnose, use heuristic attribution only (no LLM)",
    )
    eval_parser.add_argument(
        "--review",
        action="store_true",
        help="Build HITL review queue (runs diagnose on failures if needed)",
    )
    eval_parser.add_argument(
        "--review-output",
        type=str,
        default=None,
        help="Write review queue JSON (default: logs/review/queue_*.json)",
    )

    review_parser = sub.add_parser("review", help="HITL review queue / Few-Shot reflux")
    review_sub = review_parser.add_subparsers(dest="review_command")

    build_p = review_sub.add_parser("build", help="Build review queue from saved eval report")
    build_p.add_argument("--report", required=True, help="EvalReport JSON path")
    build_p.add_argument("--diagnoses", default=None, help="Optional diagnoses JSON path")
    build_p.add_argument("--output", default=None, help="Queue output path")
    build_p.add_argument(
        "--no-llm-diagnose",
        action="store_true",
        help="If diagnoses omitted, attribute failures with heuristic only",
    )

    reflux_p = review_sub.add_parser("reflux", help="Append a Few-Shot example manually")
    reflux_p.add_argument("--question", required=True, help="Natural language question")
    reflux_p.add_argument("--sql", required=True, help="SQL to store as few-shot")
    reflux_p.add_argument("--rationale", default="", help="Optional rationale")
    reflux_p.add_argument(
        "--few-shots",
        default=None,
        help="Target YAML (default: metadata/few_shots/examples.yaml)",
    )

    approve_p = review_sub.add_parser(
        "approve",
        help="Approve a queue ticket and reflux gold/override SQL to Few-Shot",
    )
    approve_p.add_argument("--queue", required=True, help="Review queue JSON path")
    approve_p.add_argument("--case-id", required=True, help="Ticket case id")
    approve_p.add_argument("--sql", default=None, help="Override SQL (default: gold_sql)")
    approve_p.add_argument("--rationale", default=None, help="Override rationale")
    approve_p.add_argument(
        "--few-shots",
        default=None,
        help="Target YAML (default: metadata/few_shots/examples.yaml)",
    )
    approve_p.add_argument(
        "--write-queue",
        default=None,
        help="Optional path to rewrite updated queue JSON",
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
    t = result.timing
    lines.append(
        "timing_ms: "
        f"total={t.total_ms:.1f} prune={t.prune_ms:.1f} generate={t.generate_ms:.1f} "
        f"l1={t.l1_ms:.1f} l2={t.l2_ms:.1f} execute={t.execute_ms:.1f} "
        f"probe={t.probe_ms:.1f} cache_hit={t.cache_hit}"
    )
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


def format_diagnoses(diagnoses: Sequence[Diagnosis]) -> str:
    """Pretty-print Eval-Agent diagnoses (Markdown blocks)."""
    if not diagnoses:
        return "diagnoses: (none)"
    return "\n".join(d.markdown.rstrip() for d in diagnoses)


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
        if args.no_save and args.diagnose_output is not None:
            parser.error("--diagnose-output and --no-save are mutually exclusive")
        if args.no_save and args.review_output is not None:
            parser.error("--review-output and --no-save are mutually exclusive")
        if args.diagnose_output is not None and not args.diagnose:
            parser.error("--diagnose-output requires --diagnose")
        if args.review_output is not None and not args.review:
            parser.error("--review-output requires --review")

        from querypilot.eval import (
            build_review_queue,
            diagnose_failures,
            format_review_queue,
            run_eval,
            save_diagnoses,
            save_eval_report,
            save_review_queue,
        )

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

        diagnoses = []
        need_diagnose = args.diagnose or args.review
        if need_diagnose:
            diagnoses = diagnose_failures(
                report,
                use_llm=not args.no_llm_diagnose,
            )
            if args.diagnose:
                print(format_diagnoses(diagnoses))
                if not args.no_save:
                    diag_path = save_diagnoses(diagnoses, args.diagnose_output)
                    print(f"diagnoses saved: {diag_path}")

        if args.review:
            queue = build_review_queue(report, diagnoses)
            print(format_review_queue(queue))
            if not args.no_save:
                qpath = save_review_queue(queue, args.review_output)
                print(f"review queue saved: {qpath}")
        return 0

    if args.command == "review":
        return _main_review(args, parser)

    parser.print_help()
    return 2


def _main_review(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    import json
    from pathlib import Path

    from querypilot.eval import (
        Diagnosis,
        append_few_shot,
        approve_and_reflux,
        build_review_queue,
        diagnose_failures,
        find_ticket,
        format_review_queue,
        load_eval_report,
        load_review_queue,
        save_review_queue,
    )

    if args.review_command is None:
        parser.print_help()
        return 0

    if args.review_command == "build":
        report = _report_from_dict(load_eval_report(args.report))
        if args.diagnoses:
            diag_raw = json.loads(Path(args.diagnoses).read_text(encoding="utf-8"))
            fields = Diagnosis.__dataclass_fields__
            diagnoses = [
                Diagnosis(**{k: v for k, v in item.items() if k in fields})
                for item in (diag_raw.get("diagnoses") or [])
            ]
        else:
            diagnoses = diagnose_failures(
                report,
                use_llm=not args.no_llm_diagnose,
            )
        queue = build_review_queue(report, diagnoses)
        print(format_review_queue(queue))
        path = save_review_queue(queue, args.output)
        print(f"review queue saved: {path}")
        return 0

    if args.review_command == "reflux":
        written, path = append_few_shot(
            args.question,
            args.sql,
            rationale=args.rationale,
            path=args.few_shots,
        )
        print(f"few-shot {'written' if written else 'skipped(duplicate)'}: {path}")
        return 0

    if args.review_command == "approve":
        queue = load_review_queue(args.queue)
        ticket = find_ticket(queue, args.case_id)
        if ticket is None:
            print(f"case_id not found: {args.case_id}")
            return 1
        written, path, ticket = approve_and_reflux(
            ticket,
            sql=args.sql,
            rationale=args.rationale,
            few_shots_path=args.few_shots,
        )
        print(
            f"approved case={ticket.case_id} "
            f"few-shot={'written' if written else 'skipped(duplicate)'}: {path}"
        )
        if args.write_queue:
            save_review_queue(queue, args.write_queue)
            print(f"review queue saved: {args.write_queue}")
        return 0

    parser.print_help()
    return 2


def _timing_from_dict(timing_raw: dict) -> "TimingInfo":
    from querypilot.eval.models import TimingInfo

    kwargs: dict = {}
    for name, f in TimingInfo.__dataclass_fields__.items():
        if name not in timing_raw:
            continue
        raw_val = timing_raw[name]
        if f.type in ("bool", bool) or name == "cache_hit":
            kwargs[name] = bool(raw_val)
        else:
            kwargs[name] = float(raw_val or 0.0)
    return TimingInfo(**kwargs)


def _report_from_dict(raw: dict) -> EvalReport:
    from querypilot.eval.models import CaseEvalResult

    results = []
    for item in raw.get("results") or []:
        timing_raw = item.get("timing") or {}
        results.append(
            CaseEvalResult(
                case_id=str(item.get("case_id", "")),
                question=str(item.get("question", "")),
                matched=bool(item.get("matched")),
                score=float(item.get("score") or 0.0),
                gold_sql=str(item.get("gold_sql", "")),
                pred_sql=str(item.get("pred_sql", "")),
                ask_ok=bool(item.get("ask_ok")),
                gold_ok=bool(item.get("gold_ok")),
                error=str(item.get("error", "")),
                match_reason=str(item.get("match_reason", "")),
                difficulty=item.get("difficulty"),
                timing=_timing_from_dict(timing_raw),
                stage=str(item.get("stage", "")),
                extras=dict(item.get("extras") or {}),
            )
        )
    return EvalReport(
        total=int(raw.get("total") or len(results)),
        matched_count=int(
            raw.get("matched_count") or sum(1 for r in results if r.matched)
        ),
        accuracy=float(raw.get("accuracy") or 0.0),
        results=results,
        failed_ids=list(raw.get("failed_ids") or []),
        by_difficulty=dict(raw.get("by_difficulty") or {}),
        p50_ms=raw.get("p50_ms"),
        p95_ms=raw.get("p95_ms"),
        mean_ms=raw.get("mean_ms"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
