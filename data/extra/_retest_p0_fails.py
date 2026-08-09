"""Retest Extra-A cases after P0 prompt fixes (Step 4.3)."""

from __future__ import annotations

import json
from pathlib import Path

from querypilot.eval.dataset import load_qa_cases
from querypilot.eval.runner import run_eval, save_eval_report

ROOT = Path(__file__).resolve().parents[2]
ALL = ROOT / "data" / "extra" / "Q&A_all.xlsx"
# P0-targeted failures first; then remaining Extra-A fails for visibility
P0_IDS = ["M08", "H05", "H11"]
ALL_FAIL_IDS = ["E02", "M08", "M11", "H03", "H05", "H11"]
OUT_DIR = ROOT / "logs" / "eval_reports"


def main() -> None:
    cases = {c.id: c for c in load_qa_cases(ALL)}
    for label, ids in (("p0", P0_IDS), ("all6", ALL_FAIL_IDS)):
        subset = [cases[i] for i in ids]
        report = run_eval(
            cases=subset,
            allow_exact_few_shot=False,
            max_few_shots=3,
            save_path=False,
        )
        path = OUT_DIR / f"extra_p0_retest_{label}.json"
        save_eval_report(report, path)
        print(
            f"=== {label} EX {report.matched_count}/{report.total} "
            f"= {report.accuracy:.1%} failed={report.failed_ids}"
        )
        for r in report.results:
            mark = "OK" if r.matched else "FAIL"
            print(f"  [{mark}] {r.case_id} stage={r.stage} err={r.error or '-'}")


if __name__ == "__main__":
    main()
