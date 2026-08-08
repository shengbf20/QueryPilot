"""Smoke demo: run EX eval on a small gold subset and save a JSON report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from querypilot.cli import format_eval_report
from querypilot.eval import run_eval, save_eval_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QueryPilot EX eval smoke demo")
    parser.add_argument("--limit", type=int, default=2, help="max gold cases (default 2)")
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="do not write JSON under logs/eval_reports/",
    )
    args = parser.parse_args(argv)

    report = run_eval(limit=args.limit)
    print(format_eval_report(report))
    if not args.no_save:
        path = save_eval_report(report)
        print(f"report saved: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
