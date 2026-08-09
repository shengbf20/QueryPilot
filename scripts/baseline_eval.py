"""Run phase-3 full-set baseline eval and write summary artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from querypilot.cli import format_eval_report
from querypilot.eval import (
    build_baseline_summary,
    build_review_queue,
    default_baseline_stem,
    diagnose_failures,
    format_baseline_markdown,
    format_review_queue,
    run_eval,
    save_baseline,
    save_diagnoses,
    save_review_queue,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase-3 baseline closeout eval")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="optional case limit (default: all gold cases)",
    )
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="Gold Q&A xlsx path (default: data/Q&A.xlsx)",
    )
    parser.add_argument(
        "--paths",
        type=str,
        action="append",
        default=None,
        help="Additional gold xlsx path(s); repeatable",
    )
    parser.add_argument(
        "--max-few-shots",
        type=int,
        default=3,
        help="Max few-shot examples passed to ask (default: 3)",
    )
    parser.add_argument(
        "--no-exact-few-shot",
        action="store_true",
        help="Disable exact-match few-shot short-circuit",
    )
    parser.add_argument(
        "--stem",
        type=str,
        default=None,
        help="output stem path without suffix (default: logs/eval_reports/phase3_baseline)",
    )
    parser.add_argument(
        "--no-llm-diagnose",
        action="store_true",
        default=True,
        help="heuristic diagnose only (default: true for reproducible closeout)",
    )
    parser.add_argument(
        "--llm-diagnose",
        action="store_true",
        help="use LLM for diagnosis (overrides --no-llm-diagnose)",
    )
    parser.add_argument(
        "--dry-run-summary",
        action="store_true",
        help="skip live eval; only validate helpers with empty report (CI smoke)",
    )
    args = parser.parse_args(argv)

    stem = Path(args.stem) if args.stem else default_baseline_stem()
    use_llm = bool(args.llm_diagnose)

    if args.dry_run_summary:
        from querypilot.eval.models import EvalReport

        report = EvalReport(total=0, matched_count=0, accuracy=0.0)
        summary = build_baseline_summary(report, label="phase3_baseline_dry")
        print(format_baseline_markdown(summary))
        json_path, md_path = save_baseline(summary, stem=stem)
        print(f"baseline saved: {json_path}")
        print(f"baseline md: {md_path}")
        return 0

    report = run_eval(
        path=args.path,
        paths=args.paths,
        limit=args.limit,
        max_few_shots=args.max_few_shots,
        allow_exact_few_shot=not args.no_exact_few_shot,
    )
    print(format_eval_report(report))

    diagnoses = diagnose_failures(report, use_llm=use_llm)
    queue = build_review_queue(report, diagnoses)
    print(format_review_queue(queue))

    summary = build_baseline_summary(
        report,
        diagnoses=diagnoses,
        queue=queue,
        label="phase3_baseline",
    )
    print(format_baseline_markdown(summary))

    json_path, md_path = save_baseline(summary, stem=stem, report=report)
    diag_path = save_diagnoses(diagnoses, Path(str(stem) + "_diag.json"))
    queue_path = save_review_queue(queue, Path(str(stem) + "_review.json"))
    print(f"baseline saved: {json_path}")
    print(f"baseline md: {md_path}")
    print(f"diagnoses saved: {diag_path}")
    print(f"review queue saved: {queue_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
